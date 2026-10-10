# Local QA Narrator

A Windows 10/11 utility for recording spoken QA feedback, capturing screenshots with
**Ctrl+Alt+F9**, and exporting a chronological Markdown walkthrough. Everything stays
on your computer. No accounts, telemetry, cloud transcription, uploads, LLM analysis,
or automatic sharing.

## Download and launch

Download **QANarrator-v0.1.0-windows-x64.zip** from the
[latest release](https://github.com/ariesyous/qa-tool/releases/latest).
Extract the ZIP, then double-click **`QANarrator\QANarrator.exe`**.
Keep the entire `QANarrator` folder together, including `_internal`; the separate
`.exe` release asset requires that companion folder and cannot run by itself.

On first launch, use **Download Model (one-time)** to install `base.en`, or follow
the offline model setup below. Models are separate from the executable and are
not included in the release. Windows 10/11 x64 is required. The build is unsigned;
clean-machine deployment and SmartScreen reputation have not been tested.

## Setup from source

Use Windows x64, Python 3.12 or 3.13, and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```powershell
uv python install 3.12
uv sync --locked --extra dev
uv run qa-narrator --download-model base.en
uv run qa-narrator
```

`uv.lock` pins the tested dependency set. Without uv, create a Python 3.12 virtual
environment and run `python -m pip install -e ".[dev]"`; this resolves within the
declared compatible ranges instead of using the lock. Microsoft Visual C++ 2015–2022
x64 Redistributable may be needed if an inference DLL cannot load.

## Use

1. Select your microphone. Prefer its **Windows WASAPI** entry if available.
2. In Settings choose the output folder and capture mode; apply. Click the
   **Screenshot shortcut** button to record a keyboard combination or a **middle / side
   mouse button** (buttons 4 and 5), optionally with Ctrl/Alt/Shift/Win. The captured
   shortcut saves immediately. Esc or Cancel keeps your previous shortcut. Left and
   right clicks are not assigned. Mouse shortcuts pass through, so the button also
   retains its normal behavior in the reviewed app.
3. Click **Start Recording**, then switch to the app you are reviewing.
4. Speak naturally and press **Ctrl+Alt+F9** for each screenshot. The taskbar flashes
   on success; the app does not steal focus or overlay your screenshot.
5. Pause/Resume when needed. Paused audio is discarded and screenshots are disabled.
6. Click **Stop Recording**. Local CPU transcription and export run in the background.
7. Use **Open Markdown** or **Open Session Folder**. Give `feedback.md` and its
   `screenshots` folder to your coding agent yourself, or provide the full session.

Recording continues while minimized. The microphone remains open during Pause so
resume is immediate, but paused samples are neither queued nor written. Closing is
blocked during recording/processing; minimize the window to leave it working.

## Offline model setup

**Download Model (one-time)** is the only application action that accesses the
internet. It fetches public faster-whisper model files from Hugging Face. `base.en`
with CPU int8 is the default; `tiny.en` trades accuracy for speed, and `small.en`
trades processing time and memory for accuracy. All three are English models.

Models live in `%LOCALAPPDATA%\QANarrator\models\<model-name>`. For an offline
machine, copy the entire downloaded model directory there. It must include
`model.bin`, `config.json`, `tokenizer.json`, and `vocabulary.txt`.
Set `QA_NARRATOR_MODEL_DIR` to use another model root (containing `base.en`, etc.).
Normal inference always loads an existing local directory with local-only loading;
it does not silently download missing models. Failed inference preserves the session.

## Session files and recovery

```text
qa-sessions/2026-10-09_184500_a1b2c3d4/
  feedback.md
  session.json
  transcription.json
  audio.wav
  audio.pcm
  screenshots/
    001.png
    001.json
```

`session.json` stores settings, state, ordered events, clock calibration, and timing.
`transcription.json` stores original recognized text and word timestamps. Each PNG
has a small timing sidecar so recovery can restore a capture interrupted while
updating the session index. Filenames are sequential and Markdown links are relative.

Microphone buffers go to a separate writer, which persists mono signed 16-bit PCM
incrementally and requests a disk flush approximately every second during capture.
Audio is converted to WAV on Stop. Keep `audio.pcm` until you no longer need crash
recovery; both files are retained deliberately, roughly doubling audio storage.
Metadata and PNGs use flushed temporary files plus atomic replacement.
Power loss can still lose recent buffers or writes held by storage hardware.

On restart, choose an incomplete session and click **Recover / Retry Transcription**.
**Open Saved Session…** opens sessions from other directories. Recovery rebuilds the
WAV from complete PCM samples. It never deletes previous recordings or screenshots.
An interrupted transcription can be retried without recording again.

**Regenerate Markdown** uses the saved transcript. Automatically generated output
can be replaced; if its bytes have changed, replacement requires confirmation.
Transcription retry also preserves manually edited Markdown.

Command-line recovery/export:

```powershell
uv run qa-narrator --process "C:\path\to\session"
uv run qa-narrator --export "C:\path\to\session"
```

The CLI refuses to overwrite edited Markdown. Use the UI for confirmed replacement.

### Portable Markdown with embedded screenshots

Enable **Settings → Export → Embed screenshots in Markdown (portable PNG/base64)**.
The preference saves immediately. New sessions embed their screenshots on export.
For an existing session, select it and click **Regenerate Markdown**; no new recording
or transcription is required. Uncheck the option and regenerate to return to relative
image links. Existing manual edits still require confirmation before replacement.
Export encoding runs in the background so large screenshots do not freeze the UI.

With this option, share **only `feedback.md`**: each image uses
`![Screenshot 001](data:image/png;base64,...)` containing the original PNG bytes.
The source screenshots and audio remain in the session folder. The exported document
contains the feedback and screenshots; audio is not embedded. Base64 adds roughly
one third to the image data size, so the Markdown can be large.

Data-URL image display depends on the viewer. Some renderers filter these URLs;
[GitHub's markup tracker](https://github.com/github/markup/issues/1614) documents this
limitation. An agent may need to extract/decode the base64 to PNG before visually
inspecting it; reading encoded text alone is not equivalent to viewing an image.
Relative-image export remains the default for compatibility.

```powershell
uv run qa-narrator --export "C:\path\to\session" --embed-images
uv run qa-narrator --export "C:\path\to\session" --linked-images
```

Both flags also work with `--process`. If neither flag is passed, CLI regeneration
uses that session's last successful export mode (linked images for older sessions).

## Timing and capture tradeoffs

- Audio and screenshots use one monotonic active-session timeline. Pauses are removed
  from both. PortAudio ADC timestamps are bridged to Python's monotonic clock and audio
  buffers are cropped at pause boundaries. Missing ADC timestamps use a continuous
  sample clock anchored to the first callback; the session records a warning. This
  fallback avoids dropping speech due to callback scheduling jitter, but can have
  initial latency error or clock drift. WASAPI is preferable to legacy MME drivers.
- Screenshots use the time immediately before the pixel grab, with the shortcut request
  time also retained. Screenshots inside a transcribed word follow that whole word;
  equal-time screenshots precede words starting at that time. Multiple screenshots
  within one sentence are supported. Missing/inconsistent word boundaries use evenly
  spaced original segment tokens, explicitly marked as estimates in the document.
- Whisper recognition and word timings are estimates. Errors or invented words can
  occur, including on silence. No second model rewrites the result. Original audio
  and the full transcript remain available for checking.
- Active-window capture uses visible screen pixels clipped to the window's DWM bounds.
  It includes overlapping windows, cannot capture hidden content, and may not work with
  protected surfaces, secure desktops, or exclusive fullscreen rendering. Invalid
  window bounds fall back to the selected monitor and report that fallback.
  Switch away from QA Narrator before capturing. Monitor/all-monitor modes may include
  other visible windows. All-black/empty captures are rejected and PNGs are validated.
- Windows per-monitor DPI awareness is enabled before creating windows. Monitor
  positions can be negative. Select the monitor again after changing display topology.
- Devices that overflow, disconnect, or stop responding end recording and preserve
  the saved portion; reconnect and start a new session. The app does not splice device
  changes into an existing recording. Sleep/suspend during recording is unsupported.
- A session must fit standard WAV's 4 GB limit (many hours for mono audio). CPU inference
  can take time and is not cancellable in v1. The UI stays responsive during inference.

## Build and test

```powershell
uv sync --locked --extra dev
New-Item -ItemType Directory -Path .validation -Force | Out-Null
uv run pytest -q --basetemp=.validation/pytest
uv run ruff check src tests
.\scripts\build.ps1
```

The PyInstaller build is a portable **one-folder** Windows x64 distribution. Models
are not embedded. It is unsigned; distribution/signing and a clean-machine install
test are separate from building locally. PyAV is constrained below 17 because version
19 removed `metadata_errors`, used by the tested faster-whisper release.
Use the build script: it isolates DLL lookup from unrelated tools on your `PATH`.

See [VALIDATION.md](VALIDATION.md) for actual results, native smoke-test commands,
and the human acceptance checklist. Automated mocks do not prove native integration.

## Troubleshooting

- **Start disabled:** connect/refresh a microphone and resolve any shortcut registration
  error in Settings. F12 is reserved by Windows and intentionally rejected.
- **Hotkey conflict:** close the competing app or choose another modifier plus F1–F11,
  letter, or digit. Windows error 5 indicates access denied (including restricted
  sandboxes). Run the app normally on your interactive desktop.
- **No audio/device error:** allow desktop microphone access in Windows privacy settings;
  check device connections, selected input, and exclusive access by other applications.
  If a newly connected device does not appear after Refresh, restart QA Narrator to
  reinitialize PortAudio's device enumeration.
- **Model missing:** download it explicitly, or copy the complete directory for offline
  use. Audio remains saved if Stop cannot transcribe.
- **Black screenshot:** try monitor mode for the visible application. Protected content
  may be unavailable in any mode. An entirely black but legitimate screen is also rejected.
- **Disk full:** free space in the output location, reopen the session and recover. Do
  not delete its PCM or screenshot sidecars before recovery.
- **Markdown won't open:** associate `.md` with VS Code or your preferred editor in Windows.

## Source layout

`capture.py` / `timeline.py` / `windows.py` handle recording and capture; `storage.py`
handles durable sessions; `transcription.py` handles local inference; `export.py`
handles deterministic Markdown; `ui.py` provides the PySide6 interface. No database,
plugin system, service container, or agent integration is used.

## Future ideas (not implemented)

- Region capture and optional cursor capture.
- Cancellable transcription with measured progress.
- Signed distribution and additional tested microphone/display configurations.

## License

The application source is available under the [MIT License](LICENSE).
Bundled dependencies retain their own licenses, included in the portable distribution.

