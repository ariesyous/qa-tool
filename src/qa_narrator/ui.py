"""Minimal Qt interface; expensive work runs outside the GUI thread."""

import sys
from concurrent.futures import CancelledError, ThreadPoolExecutor
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .capture import CaptureEngine
from .compact import LARGE_EXPORT_BYTES, shrink_markdown, size_notice
from .export import export_markdown, timestamp
from .shortcut import AdditionalShortcutsDialog, ShortcutDialog
from .storage import Session, list_sessions
from .transcription import MODELS, download_model, model_root, process_session
from .windows import MAX_ADDITIONAL_SHORTCUTS, ScreenshotShortcuts, capture_target, shortcut_label


class Signals(QObject):
    finished = Signal(object, object, object)
    notice = Signal(str, str)
    progress = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local QA Narrator")
        self.resize(650, 680)
        self.settings = QSettings("LocalQANarrator", "QANarrator")
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="processing")
        self.signals = Signals()
        # Even an already-finished Future must queue completion after its progress updates.
        self.signals.finished.connect(self._finished, Qt.QueuedConnection)
        self.signals.notice.connect(self._notice)
        self.signals.progress.connect(self._progress)
        self.engine, self.session, self.hotkey = None, None, None
        # Whether the configured shortcuts last registered successfully. Registrations are
        # only held while recording; see _release_shortcuts.
        self._shortcuts_ready = False
        self.busy = False
        self._cancel_event = None
        self.root = Path(
            self.settings.value("output", str(Path.home() / "Documents" / "qa-sessions"))
        )
        self.shortcut = self.settings.value("shortcut", "Ctrl+Alt+F9")
        self.additional_shortcuts = self.settings.value("additional_shortcuts", [], type=list)
        self._build()
        self._devices()
        self._sessions()
        try:
            self.hotkey = ScreenshotShortcuts(
                QApplication.instance(), self._capture, self._shortcuts()
            )
        except Exception as exc:
            self._notice("error", str(exc))
        # Registering at launch still surfaces conflicts early, but nothing stays registered.
        self._release_shortcuts()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)
        self._controls()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        title = QLabel("Local QA Narrator")
        title.setStyleSheet("font-size: 23px; font-weight: 600; margin-bottom: 6px")
        layout.addWidget(title)
        layout.addWidget(QLabel("Record your observations. Capture evidence. Export locally."))
        self.status = QLabel("Ready · microphone is off")
        self.status.setStyleSheet("font-size: 17px; padding: 12px 0; font-weight: 600")
        layout.addWidget(self.status)
        self.stats = QLabel("00:00  ·  0 screenshots")
        layout.addWidget(self.stats)
        row = QHBoxLayout()
        self.mics = QComboBox()
        self.mics.setMinimumWidth(300)
        self.refresh_mics = QPushButton("Refresh microphones")
        self.refresh_mics.clicked.connect(self._devices)
        row.addWidget(self.mics, 1)
        row.addWidget(self.refresh_mics)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.start = QPushButton("Start Recording")
        self.pause = QPushButton("Pause")
        self.stop = QPushButton("Stop Recording")
        for button, slot in (
            (self.start, self._start),
            (self.pause, self._pause),
            (self.stop, self._stop),
        ):
            button.clicked.connect(slot)
            row.addWidget(button)
        layout.addLayout(row)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setMinimumHeight(42)
        layout.addWidget(self.message)
        self.processing = QLabel("Transcription/export: no session selected")
        self.processing.setWordWrap(True)
        layout.addWidget(self.processing)
        self.activity = QProgressBar()
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.activity.setFixedHeight(10)
        self.activity.setAccessibleName("Background task in progress")
        self.activity.hide()
        self.cancel_shrink = QPushButton("Cancel")
        self.cancel_shrink.setToolTip("Stop shrinking after the current image operation finishes")
        self.cancel_shrink.clicked.connect(self._cancel_shrink)
        self.cancel_shrink.hide()
        row = QHBoxLayout()
        row.addWidget(self.activity, 1)
        row.addWidget(self.cancel_shrink)
        layout.addLayout(row)

        group = QGroupBox("Sessions")
        form = QVBoxLayout(group)
        self.sessions = QComboBox()
        self.sessions.currentIndexChanged.connect(self._select_session)
        form.addWidget(self.sessions)
        self.location = QLabel(str(self.root))
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(self.location.textInteractionFlags())
        form.addWidget(self.location)
        row = QHBoxLayout()
        self.open_folder = QPushButton("Open Session Folder")
        self.open_md = QPushButton("Open Markdown")
        self.browse_session = QPushButton("Open Saved Session…")
        self.open_folder.clicked.connect(lambda: self._open(self.session.folder))
        self.open_md.clicked.connect(lambda: self._open(self.session.folder / "feedback.md"))
        self.browse_session.clicked.connect(self._browse_session)
        for button in (self.open_folder, self.open_md, self.browse_session):
            row.addWidget(button)
        form.addLayout(row)
        row = QHBoxLayout()
        self.retry = QPushButton("Recover / Retry Transcription")
        self.regenerate = QPushButton("Regenerate Markdown")
        self.retry.clicked.connect(self._process)
        self.regenerate.clicked.connect(self._export)
        self.shrink = QPushButton("Shrink Markdown…")
        self.shrink.clicked.connect(self._shrink_markdown)
        row.addWidget(self.retry)
        row.addWidget(self.regenerate)
        row.addWidget(self.shrink)
        form.addLayout(row)
        layout.addWidget(group)

        self.options = QGroupBox("Settings")
        form = QFormLayout(self.options)
        self.shortcut_button = QPushButton(f"{shortcut_label(self.shortcut)}  ·  Change…")
        self.shortcut_button.clicked.connect(lambda: self._choose_shortcut())
        form.addRow("Screenshot shortcut", self.shortcut_button)
        self.additional_shortcuts_button = QPushButton()
        self.additional_shortcuts_button.clicked.connect(self._manage_shortcuts)
        form.addRow("", self.additional_shortcuts_button)
        self._refresh_shortcuts()
        row = QHBoxLayout()
        self.output_text = QLineEdit(str(self.root))
        choose = QPushButton("Browse…")
        choose.clicked.connect(self._choose_root)
        row.addWidget(self.output_text)
        row.addWidget(choose)
        form.addRow("Save sessions to", row)
        self.mode = QComboBox()
        for text, value in (
            ("Active window (monitor fallback)", "window"),
            ("Selected monitor", "monitor"),
            ("All monitors", "desktop"),
        ):
            self.mode.addItem(text, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.settings.value("mode", "window"))))
        form.addRow("Capture", self.mode)
        self.window_context = QCheckBox("Include focused window title and app name")
        self.window_context.setChecked(self.settings.value("window_context", False, type=bool))
        self.window_context.setToolTip(
            "Off by default. Titles can contain private document, email, or chat names. "
            "When enabled, they are saved with new screenshots and included in Markdown. "
            "For monitor captures, this describes only the focused window."
        )
        self.window_context.toggled.connect(self._save_window_context)
        form.addRow("Screenshot context", self.window_context)
        self.monitors = QComboBox()
        try:
            import mss

            with mss.mss() as screen:
                for i, monitor in enumerate(screen.monitors[1:], 1):
                    self.monitors.addItem(
                        f"Monitor {i} · {monitor['width']} × {monitor['height']}", i
                    )
        except Exception as exc:
            self._notice("error", str(exc))
        try:
            saved_monitor = int(self.settings.value("monitor", 1))
        except (TypeError, ValueError):
            saved_monitor = 1
        index = self.monitors.findData(saved_monitor)
        self.monitors.setCurrentIndex(max(0, index))
        form.addRow("Monitor / fallback", self.monitors)
        self.model = QComboBox()
        self.model.addItems(MODELS)
        self.model.setCurrentText(self.settings.value("model", "base.en"))
        row = QHBoxLayout()
        row.addWidget(self.model)
        self.download = QPushButton("Download Model (one-time)")
        self.download.clicked.connect(self._download)
        row.addWidget(self.download)
        form.addRow("English CPU model", row)
        self.vocabulary = QLineEdit(self.settings.value("vocabulary", ""))
        self.vocabulary.setPlaceholderText("Optional: product names, UI terms, acronyms")
        self.vocabulary.setToolTip(
            "A few hint words or phrases, separated by commas. Used for new transcription and retries."
        )
        self.vocabulary.editingFinished.connect(self._save_vocabulary)
        form.addRow("Vocabulary hints", self.vocabulary)
        self.embed_images = QCheckBox("Embed screenshots in Markdown (portable)")
        self.embed_images.setChecked(self.settings.value("embed_images", False, type=bool))
        self.embed_images.toggled.connect(self._save_export_preference)
        form.addRow("Export", self.embed_images)
        self.image_quality = QComboBox()
        self.image_quality.addItem("Compact — under 25 MB", "compact")
        self.image_quality.addItem("Raw — original PNGs, no size limit", "raw")
        self.image_quality.setCurrentIndex(
            max(0, self.image_quality.findData(self.settings.value("image_quality", "compact")))
        )
        self.image_quality.setEnabled(self.embed_images.isChecked())
        self.embed_images.toggled.connect(self.image_quality.setEnabled)
        self.image_quality.currentIndexChanged.connect(self._save_image_quality)
        form.addRow("Embedded image quality", self.image_quality)
        export_hint = QLabel(
            "Compact preserves images when the report fits within 24 MB.\n"
            "For coding agents, leave embedding off and share the screenshots folder."
        )
        export_hint.setWordWrap(True)
        export_hint.setMinimumHeight(export_hint.fontMetrics().lineSpacing() * 2 + 4)
        form.addRow("", export_hint)
        apply = QPushButton("Apply Settings")
        apply.clicked.connect(lambda: self._apply())
        form.addRow(apply)
        layout.addWidget(self.options)
        privacy = QLabel(
            "Audio, screenshots, and transcription stay on this computer.\n"
            "Only Download Model uses the internet. Capture is disabled while paused."
        )
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

    def _devices(self):
        import sounddevice as sd

        selected = self.mics.currentText() or self.settings.value("microphone", "")
        self.mics.clear()
        try:
            devices, hosts = sd.query_devices(), sd.query_hostapis()
            default = sd.default.device[0]
            wasapi = [
                i for i, device in enumerate(devices)
                if device["max_input_channels"] > 0
                and hosts[device["hostapi"]]["name"] == "Windows WASAPI"
            ]
            # Keep the same endpoint when names match across host APIs. MME's
            # Sound Mapper alias/truncated names may not match; use the WASAPI
            # default in that case. Saved or currently selected choices win below.
            if default not in wasapi:
                matches = [
                    i for i in wasapi if 0 <= default < len(devices)
                    and devices[i]["name"].casefold() == devices[default]["name"].casefold()
                ]
                preferred = matches[0] if len(matches) == 1 else next((
                    host["default_input_device"] for host in hosts
                    if host["name"] == "Windows WASAPI" and host["default_input_device"] in wasapi
                ), default)
                default = preferred
            for index, device in enumerate(devices):
                if device["max_input_channels"] > 0:
                    host = hosts[device["hostapi"]]["name"]
                    self.mics.addItem(f"{device['name']} ({host})", index)
                    if index == default:
                        self.mics.setCurrentIndex(self.mics.count() - 1)
            saved = self.mics.findText(selected)
            if saved >= 0:
                self.mics.setCurrentIndex(saved)
            if not self.mics.count():
                self._notice(
                    "error", "No microphone found. Connect one and click Refresh microphones."
                )
        except Exception as exc:
            self._notice("error", f"Cannot enumerate microphones: {exc}")
        self._controls()

    def _sessions(self, selected=None):
        self.sessions.blockSignals(True)
        self.sessions.clear()
        items = list_sessions(self.root)
        if selected and all(s.folder != selected.folder for s in items):
            items.insert(0, selected)
        for session in items:
            data = session.data
            label = f"{session.folder.name} · {data['status']} · export: {data.get('export_status', 'pending')}"
            self.sessions.addItem(label, str(session.folder))
        desired = str(selected.folder) if selected else self.settings.value("recent", "")
        index = self.sessions.findData(desired)
        self.sessions.setCurrentIndex(max(0, index) if items else -1)
        self.sessions.blockSignals(False)
        self._select_session()

    def _select_session(self):
        folder = self.sessions.currentData()
        self.session = Session.load(folder) if folder else None
        if self.session:
            self.settings.setValue("recent", folder)
            self.location.setText(folder)
            data = self.session.data
            self.processing.setText(
                f"Transcription: {data['transcription_status']} · Export: {data['export_status']}"
            )
            output = self.session.folder / "feedback.md"
            if output.exists():
                self.processing.setText(
                    self.processing.text() + "\nMarkdown: " + size_notice(output.stat().st_size)
                )
            self.stats.setText(
                f"{timestamp(data['duration'])}  ·  {len(self.session.screenshots())} screenshots"
            )
            if data["status"] in ("recording", "paused", "stopping", "capture_error"):
                self._notice(
                    "warning",
                    "Incomplete session found. Click Recover / Retry Transcription to process saved audio.",
                )
        self._controls()

    def _controls(self):
        if not hasattr(self, "options"):
            return
        active, idle = self.engine is not None, not self.busy and self.engine is None
        self.start.setEnabled(idle and self.mics.count() > 0 and self._shortcuts_ready)
        self.pause.setEnabled(active and not self.busy)
        self.stop.setEnabled(active and not self.busy)
        for widget in (
            self.options,
            self.sessions,
            self.mics,
            self.refresh_mics,
            self.browse_session,
            self.shrink,
        ):
            widget.setEnabled(idle)
        self.retry.setEnabled(idle and self.session is not None)
        self.regenerate.setEnabled(
            idle
            and self.session is not None
            and (self.session.folder / "transcription.json").exists()
        )
        self.open_folder.setEnabled(self.session is not None)
        self.open_md.setEnabled(
            self.session is not None and (self.session.folder / "feedback.md").exists()
        )

    def _run(self, operation, success, failure=None, cancel_event=None):
        self.busy = True
        self._cancel_event = cancel_event
        self.cancel_shrink.setText("Cancel")
        self.cancel_shrink.setEnabled(cancel_event is not None)
        self.cancel_shrink.setVisible(cancel_event is not None)
        self.activity.show()
        self._controls()
        future = self.pool.submit(operation)

        def done(result):
            try:
                value, error = result.result(), None
            except Exception as exc:
                value, error = None, exc
            self.signals.finished.emit((success, failure), value, error)

        future.add_done_callback(done)

    def _finished(self, callbacks, result, error):
        success, failure = callbacks
        self.busy = False
        self._cancel_event = None
        self.cancel_shrink.hide()
        self.activity.hide()
        try:
            if error and failure:
                failure(error)
            elif error:
                self.status.setText(
                    "Needs attention · microphone is off"
                    if not self.engine
                    else "Recording needs attention"
                )
                self._notice("error", str(error))
                if not self.engine:
                    self._sessions(self.session)
            else:
                success(result)
        finally:
            if self.engine is None:
                # Covers Stop and a failed Start, even if a callback raised:
                # never leave shortcuts registered while idle.
                self._disarm_shortcuts()
        self._controls()

    def _notice(self, kind, text):
        self.message.setStyleSheet("color: #b42318" if kind == "error" else "color: #286343")
        self.message.setText(text)
        if kind == "screenshot":
            QApplication.alert(self, 800)  # taskbar flash, no focus stealing or screen overlay

    def _progress(self, text):
        if self._cancel_event is not None and self._cancel_event.is_set():
            return  # Keep the cancellation acknowledgement visible until the worker stops.
        self.processing.setText(text)

    def _cancel_shrink(self):
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.cancel_shrink.setEnabled(False)
            self.cancel_shrink.setText("Cancelling…")
            self.processing.setText("Cancelling… waiting for the current operation to finish.")

    def _start(self):
        # Register shortcuts before opening the microphone so a conflict stops Start cleanly.
        if not self._apply(arm=True):
            return
        device, name = self.mics.currentData(), self.mics.currentText()
        self.settings.setValue("microphone", name)
        self.status.setText("Starting microphone…")
        self._run(
            lambda: CaptureEngine(self.root, device, name, self.signals.notice.emit).start(),
            self._started,
        )

    def _started(self, engine):
        self.engine = engine
        self.session = engine.session
        self.location.setText(str(self.session.folder))
        self.settings.setValue("recent", str(self.session.folder))
        self.message.clear()
        self.processing.setText("Transcription begins after Stop Recording.")
        self.pause.setText("Pause")
        self._tick()

    def _pause(self):
        try:
            self.engine.pause_resume()
            self.pause.setText("Resume" if self.engine.timeline.state == "paused" else "Pause")
        except Exception as exc:
            self._notice("error", str(exc))
            self._stop()

    def _stop(self):
        engine = self.engine
        if not engine or self.busy:
            return
        self.engine = None
        self.status.setText("Stopping and saving audio…")
        self._run(engine.stop, self._stopped)

    def _stopped(self, session):
        self.session = session
        self.status.setText("Stopped · microphone is off")
        self._sessions(session)
        self._process()

    def _capture(self):
        if self.engine and not self.busy and self.engine.timeline.state == "recording":
            try:
                self.engine.capture(
                    capture_target(
                        self.mode.currentData(), self.monitors.currentData(),
                        include_window_context=self.window_context.isChecked(),
                    )
                )
            except Exception as exc:
                self._notice("error", str(exc))

    def _tick(self):
        if self.engine:
            timeline = self.engine.timeline
            self.status.setText(
                "● Recording · microphone is on"
                if timeline.state == "recording"
                else "Ⅱ Paused · audio is not being saved"
            )
            self.status.setStyleSheet(
                "font-size: 17px; padding: 12px 0; font-weight: 600; color: "
                + ("#c02a2a" if timeline.state == "recording" else "#805600")
            )
            self.stats.setText(
                f"{timestamp(timeline.elapsed())}  ·  {len(self.engine.session.screenshots())} screenshots"
            )
            error = self.engine.check_error()
            if error:
                try:
                    self.engine.session.event(
                        {"kind": "warning", "t": timeline.elapsed(), "message": error}
                    )
                except OSError:
                    pass  # Stop/close the device even when the disk is full.
                self._notice("error", error)
                self._stop()

    def _process(self):
        session, model = self.session, self.model.currentText()
        embed_images = self.embed_images.isChecked()
        image_quality = self.image_quality.currentData()
        if not session:
            return
        vocabulary = self._save_vocabulary()

        def work():
            session.recover()
            if not (session.folder / "audio.wav").exists():
                session.finalize_audio()
            return process_session(
                session,
                model,
                self.signals.progress.emit,
                embed_images=embed_images,
                image_quality=image_quality,
                vocabulary=vocabulary,
            )

        self.status.setText("Processing · microphone is off")
        self._run(work, self._processed)

    def _processed(self, path):
        self.status.setText(
            "Transcript updated · edited Markdown kept" if path is None
            else "Complete · microphone is off"
        )
        self._sessions(self.session)
        if path is None:
            self.processing.setText(
                "Transcript updated; use Regenerate Markdown to replace your edited feedback.md."
            )
            self._notice("warning", "Your edited Markdown was kept. The new transcript is saved.")
        else:
            self._export_notice(path)

    def _export_notice(self, path):
        size = path.stat().st_size
        self._notice(
            "warning" if size >= LARGE_EXPORT_BYTES else "success",
            f"Ready: {path}\n{size_notice(size)}",
        )

    def _save_image_quality(self, _index):
        self.settings.setValue("image_quality", self.image_quality.currentData())
        self.settings.sync()

    def _save_vocabulary(self):
        vocabulary = " ".join(self.vocabulary.text().split())
        self.settings.setValue("vocabulary", vocabulary)
        self.settings.sync()
        return vocabulary

    def _save_window_context(self, enabled):
        self.settings.setValue("window_context", enabled)
        self.settings.sync()

    def _shrink_markdown(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Shrink embedded-image Markdown (original is kept)",
            str(self.session.folder if self.session else self.root),
            "Markdown (*.md *.markdown)",
        )
        if path:
            cancel_event = Event()
            self.processing.setText("Shrinking Markdown to a separate copy…")

            def done(output):
                self.processing.setText("Compact copy saved: " + size_notice(output.stat().st_size))
                self._export_notice(output)

            def failed(error):
                if isinstance(error, CancelledError):
                    self.processing.setText("Shrinking cancelled; original Markdown kept.")
                    self._notice("success", "No compact copy was saved. You can try again anytime.")
                    return
                self.processing.setText("Shrink failed; original Markdown kept.")
                self._notice("error", str(error))

            self._run(
                lambda: shrink_markdown(
                    path, progress=self.signals.progress.emit, cancelled=cancel_event.is_set
                ),
                done,
                failed,
                cancel_event=cancel_event,
            )

    def _save_export_preference(self, checked):
        self.settings.setValue("embed_images", checked)
        self.settings.sync()

    def _export(self, overwrite=False):
        session, embed_images = self.session, self.embed_images.isChecked()
        image_quality = self.image_quality.currentData()
        if not session:
            return

        def failed(error):
            if isinstance(error, FileExistsError):
                answer = QMessageBox.question(
                    self,
                    "Replace edited Markdown?",
                    "feedback.md has changed since the last export. Replace your edits?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if answer == QMessageBox.Yes:
                    self._export(overwrite=True)
                else:
                    self.processing.setText("Export cancelled; existing Markdown kept.")
            else:
                self.processing.setText("Export failed; existing Markdown kept.")
                self._notice("error", str(error))

        self.processing.setText(
            "Writing portable Markdown…" if embed_images else "Writing Markdown…"
        )
        self._run(
            lambda: export_markdown(
                session,
                overwrite=overwrite,
                embed_images=embed_images,
                image_quality=image_quality,
                progress=self.signals.progress.emit,
            ),
            self._processed,
            failed,
        )

    def _choose_root(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Choose session output directory", self.output_text.text()
        )
        if folder:
            self.output_text.setText(folder)

    def _browse_session(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Open folder containing session.json", str(self.root)
        )
        if folder:
            try:
                self._sessions(Session.load(folder))
            except Exception as exc:
                self._notice("error", str(exc))

    def _shortcuts(self):
        return [self.shortcut, *self.additional_shortcuts]

    def _release_shortcuts(self):
        """Remember whether the shortcuts registered, then release them unless recording.

        RegisterHotKey reserves a key combination system-wide: the focused app never
        receives it. Holding registrations while idle would, for example, stop a
        standalone backtick from typing anywhere for as long as this window is open.
        """
        self._shortcuts_ready = self.hotkey is not None
        if self.engine is None:
            self._disarm_shortcuts()

    def _disarm_shortcuts(self):
        if self.hotkey is not None:
            self.hotkey.close()
            self.hotkey = None

    def _refresh_shortcuts(self):
        self.shortcut_button.setText(f"{shortcut_label(self.shortcut)}  ·  Change…")
        self.additional_shortcuts_button.setText(
            f"Additional shortcuts ({len(self.additional_shortcuts)}/{MAX_ADDITIONAL_SHORTCUTS})…"
        )
        self.hint.setText(
            "Switch to your application and press "
            + " or ".join(map(shortcut_label, self._shortcuts())) + " to capture."
        )

    def _save_shortcuts(self, shortcuts):
        self.shortcut, *self.additional_shortcuts = shortcuts
        self.settings.setValue("shortcut", self.shortcut)
        self.settings.setValue("additional_shortcuts", self.additional_shortcuts)
        self.settings.sync()
        self._refresh_shortcuts()

    def _manage_shortcuts(self):
        AdditionalShortcutsDialog(self).exec()

    def _choose_shortcut(self, index=0, picker_parent=None):
        if index is None and len(self.additional_shortcuts) >= MAX_ADDITIONAL_SHORTCUTS:
            return f"You can add up to {MAX_ADDITIONAL_SHORTCUTS} additional shortcuts."
        # Release all registrations so the picker can receive existing combinations.
        previous = self._shortcuts()
        if self.hotkey:
            self.hotkey.close()
            self.hotkey = None
        dialog = ShortcutDialog(picker_parent or self)
        chosen = dialog.shortcut if dialog.exec() else None
        candidate = previous.copy()
        if chosen:
            if index is None:
                candidate.append(chosen)
            else:
                candidate[index] = chosen
        error = None
        try:
            self.hotkey = ScreenshotShortcuts(QApplication.instance(), self._capture, candidate)
        except Exception as exc:
            error = str(exc)
            candidate = previous
            try:
                self.hotkey = ScreenshotShortcuts(QApplication.instance(), self._capture, previous)
            except Exception as restore_error:
                error = f"{exc} Previous shortcuts could not be restored: {restore_error}"
        if self.hotkey:
            self._save_shortcuts(candidate)
        if error:
            self._notice("error", error)
        self._release_shortcuts()
        self._controls()
        return error

    def _remove_shortcut(self, index):
        if not 1 <= index <= len(self.additional_shortcuts):
            return "Only additional shortcuts can be removed."
        candidate = self._shortcuts()
        del candidate[index]
        self._save_shortcuts(candidate)  # Removing cannot add a conflict; always keep it.
        error = None
        try:
            if self.hotkey:
                self.hotkey.configure(candidate)
            else:
                self.hotkey = ScreenshotShortcuts(QApplication.instance(), self._capture, candidate)
        except Exception as exc:
            error = str(exc)  # Another app took a remaining key while idle.
            self._notice("error", error)
        self._release_shortcuts()
        self._controls()
        return error

    def _apply(self, arm=False):
        """Save settings and check the shortcuts register.

        With arm=True (Start Recording) the registrations are kept for the session;
        otherwise they are released again so idle keys keep working in other apps.
        """
        try:
            root = Path(self.output_text.text()).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            if self.hotkey is None:
                self._shortcuts_ready = False
                self.hotkey = ScreenshotShortcuts(
                    QApplication.instance(), self._capture, self._shortcuts()
                )
            self._shortcuts_ready = True
            changed = root != self.root
            self.root = root
            for key, value in (
                ("output", str(root)),
                ("mode", self.mode.currentData()),
                ("monitor", self.monitors.currentData() or 1),
                ("model", self.model.currentText()),
                ("vocabulary", " ".join(self.vocabulary.text().split())),
            ):
                self.settings.setValue(key, value)
            self.settings.sync()
            self._refresh_shortcuts()
            if changed:
                self._sessions()
            if not arm:
                self._disarm_shortcuts()
            self._controls()
            return True
        except Exception as exc:
            if self.engine is None:
                self._disarm_shortcuts()
            self._notice("error", str(exc))
            self._controls()
            return False

    def _download(self):
        name = self.model.currentText()
        self.processing.setText(f"Downloading {name} to {model_root()}…")
        self._run(
            lambda: download_model(name),
            lambda path: self.processing.setText(f"Model installed. Ready for offline use: {path}"),
        )

    def _open(self, path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._notice(
                "error", f"Could not open {path}. Configure a default app for Markdown in Windows."
            )

    def closeEvent(self, event):
        if self.engine or self.busy:
            QMessageBox.information(
                self,
                "Session in progress",
                "Stop recording and wait for processing to finish before closing. "
                "You can minimize this window while it works.",
            )
            event.ignore()
            return
        if self.hotkey:
            self.hotkey.close()
        self.pool.shutdown(wait=False)
        event.accept()


def run():
    from .windows import enable_dpi_awareness

    enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()
