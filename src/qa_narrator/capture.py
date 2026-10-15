"""Independent PortAudio callback, PCM writer, and serial screenshot worker."""

import io
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .storage import Session, atomic_bytes, atomic_json
from .timeline import Timeline


class CaptureEngine:
    def __init__(self, root, device, microphone, notify=lambda *_: None):
        import sounddevice as sd

        self.sd = sd
        self.rate = int(sd.query_devices(device, "input")["default_samplerate"])
        self.session = Session.create(root, self.rate, microphone)
        self.notify = notify
        self.audio_queue = queue.Queue(maxsize=300)
        self.errors = queue.SimpleQueue()
        self.warnings = queue.SimpleQueue()
        self.writer_error = None
        self.metadata_pending = threading.Event()
        self.metadata_error = None
        self.timeline = None
        self.stream = None
        self.accepting = False
        self.last_callback = time.perf_counter()
        self.writer = threading.Thread(target=self._write_audio, name="pcm-writer", daemon=True)
        self.screens = ThreadPoolExecutor(max_workers=1, thread_name_prefix="screenshot")
        self.screen_pending = threading.BoundedSemaphore(3)
        self.device = device
        self.timing_fallback_reported = False
        self.sample_anchor = None
        self.captured_frames = 0
        self.use_adc = None
        self.input_latency = 0.0
        self.last_audio_end = None

    def start(self):
        try:
            self.stream = self.sd.RawInputStream(
                device=self.device,
                samplerate=self.rate,
                channels=1,
                dtype="int16",
                blocksize=0,
                callback=self._callback,
            )
            before = time.perf_counter_ns()
            self.stream_anchor = self.stream.time
            self.clock_anchor = (before + time.perf_counter_ns()) // 2
            self.timeline = Timeline()
            self.input_latency = self.stream.latency
            self.session.update(
                audio_clock={
                    "portaudio_anchor": self.stream_anchor,
                    "anchor_relative_ns": self.clock_anchor - self.timeline.origin,
                    "input_latency_seconds": self.stream.latency,
                    "fallback": (
                        "continuous sample clock anchored at callback minus the greater of "
                        "reported input latency and buffer duration; reanchored after overflow"
                    ),
                }
            )
            self.session.event({"kind": "started", "t": 0, "monotonic_ns": 0})
            self.writer.start()
            self.accepting = True
            self.stream.start()
        except Exception:
            self.accepting = False
            if self.stream:
                self.stream.close()
            if self.writer.is_alive():
                self.audio_queue.put(None)
                self.writer.join()
            self.screens.shutdown(wait=True)
            self.session.update(status="capture_error")
            raise
        return self

    def _callback(self, data, frames, timing, status):
        self.last_callback = time.perf_counter()
        if not self.accepting:
            return
        overflow = False
        if status:
            # Copy the flags: clearing overflow must not mutate PortAudio's status.
            other_status = self.sd.CallbackFlags()
            other_status |= status
            overflow = other_status.input_overflow
            other_status.input_overflow = False
        if status and (not overflow or other_status):
            self.errors.put(
                f"Microphone stream error: {status}. Recording stopped to preserve alignment."
            )
            self.accepting = False
            raise self.sd.CallbackAbort
        adc = timing.inputBufferAdcTime
        valid_adc = bool(adc) and abs(adc - timing.currentTime) < 10
        if self.use_adc is None:
            self.use_adc = valid_adc
        if self.use_adc and valid_adc:
            start = self.clock_anchor + round((adc - self.stream_anchor) * 1e9)
        else:
            if self.sample_anchor is None or overflow:
                # PortAudio input latency already refers to the first sample, so
                # do not also subtract a full buffer. Keep its duration as a floor
                # when a driver reports zero/insufficient latency.
                estimate = time.perf_counter_ns() - round(
                    max(self.input_latency, frames / self.rate) * 1e9
                )
                self.sample_anchor = max(
                    estimate, self.last_audio_end if self.last_audio_end is not None else estimate
                )
                self.captured_frames = 0
            self.use_adc = False
            start = self.sample_anchor + round(self.captured_frames / self.rate * 1e9)
            if not self.timing_fallback_reported:
                self.timing_fallback_reported = True
                message = (
                    "Microphone has no reliable ADC timestamps; timing uses a continuous sample "
                    "clock estimated from the first callback. Prefer a WASAPI microphone for better timing."
                )
                self.warnings.put(
                    {"kind": "warning", "t": self.timeline.elapsed(), "message": message}
                )
                self.notify("warning", message)
        if overflow:
            estimated = not (self.use_adc and valid_adc)
            active_start = self.timeline.elapsed(start)
            gap = (
                max(0, active_start - self.timeline.elapsed(self.last_audio_end))
                if self.last_audio_end is not None else None
            )
            message = "Microphone input overflow: some audio was lost; recording continues. " + (
                "Gap timing is estimated from the callback clock and input latency."
                if estimated else "Timestamped gaps are kept as silence."
            )
            self.warnings.put({
                "kind": "warning", "t": active_start, "message": message,
                "audio_gap_seconds": gap, "timing_estimated": estimated,
            })
            self.notify("warning", message)
        self.last_audio_end = start + round(frames / self.rate * 1e9)
        self.captured_frames += frames
        for dest, a, b in self.timeline.slices(start, frames, self.rate):
            try:
                self.audio_queue.put_nowait((dest, bytes(data[a * 2 : b * 2])))
            except queue.Full:
                self.errors.put(
                    "Audio disk writer could not keep up. Recording stopped; saved audio is recoverable."
                )
                self.accepting = False
                raise self.sd.CallbackAbort

    def _write_audio(self):
        try:
            with (self.session.folder / "audio.pcm").open("wb", buffering=0) as output:
                position, flushed = 0, time.monotonic()
                while True:
                    try:
                        item = self.audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        if time.monotonic() - flushed >= 1:
                            os.fsync(output.fileno())
                            self._persist_metadata()
                            flushed = time.monotonic()
                        continue
                    if item is None:
                        break
                    dest, data = item
                    # Pad clock/device gaps; trim overlapping frames caused by clock rounding.
                    gap = max(0, dest - position) * 2
                    while gap:
                        size = min(gap, 65536)
                        output.write(b"\0" * size)
                        gap -= size
                        position += size // 2
                    data = data[max(0, position - dest) * 2 :]
                    output.write(data)
                    position += len(data) // 2
                    if time.monotonic() - flushed >= 1:
                        os.fsync(output.fileno())
                        self._persist_metadata()
                        flushed = time.monotonic()
                os.fsync(output.fileno())
        except Exception as exc:
            self.writer_error = exc
            self.errors.put(f"Could not persist microphone audio: {exc}")
            self.accepting = False
        # Metadata failures must never be classified as PCM write failures. Failed
        # saves leave events in memory, so retry saving rather than appending again.
        self._persist_metadata()

    def _persist_metadata(self):
        while not self.warnings.empty():
            self.session.event(self.warnings.get_nowait(), persist=False)
            self.metadata_pending.set()
        if not self.metadata_pending.is_set():
            return
        # Clear before saving so a concurrent pause cannot lose its pending save.
        self.metadata_pending.clear()
        try:
            self.session.save()
        except OSError as exc:
            self.metadata_pending.set()
            if self.metadata_error is None:
                self.notify(
                    "warning",
                    f"Could not save session metadata: {exc}. "
                    + (
                        "Audio capture continues; retrying."
                        if self.accepting
                        else "Saved audio is retained; metadata still needs saving."
                    ),
                )
            self.metadata_error = exc
        else:
            self.metadata_error = None

    def pause_resume(self):
        state = "paused" if self.timeline.state == "recording" else "recording"
        event = self.timeline.transition(state)
        self.session.event(event, persist=False)
        self.session.update(status=state, persist=False)
        self.metadata_pending.set()

    def capture(self, target):
        if not self.accepting or self.timeline.state != "recording":
            self._screenshot_skipped()
            return
        if not self.screen_pending.acquire(blocking=False):
            self.notify("error", "Screenshot capture is busy; try again in a moment.")
            return
        requested = time.perf_counter_ns()
        self.screens.submit(self._screenshot, target, requested)

    def _screenshot(self, target, requested):
        try:
            import mss
            from PIL import Image

            from .windows import foreground, window_rect

            if self.timeline.state != "recording" or not self.accepting:
                self._screenshot_skipped()
                return
            with mss.mss() as screen:
                monitors = screen.monitors
                index = target["monitor"]
                if not 0 <= index < len(monitors):
                    raise ValueError(
                        "Selected monitor is no longer connected; select another monitor"
                    )
                mode = target["mode"]
                fallback = None
                if mode == "window":
                    try:
                        rect = window_rect(target["hwnd"])
                        bounds = monitors[0]
                        left, top = (
                            max(rect["left"], bounds["left"]),
                            max(rect["top"], bounds["top"]),
                        )
                        right = min(rect["left"] + rect["width"], bounds["left"] + bounds["width"])
                        bottom = min(rect["top"] + rect["height"], bounds["top"] + bounds["height"])
                        if right <= left or bottom <= top:
                            raise ValueError("Active window is off screen")
                        rect = {
                            "left": left,
                            "top": top,
                            "width": right - left,
                            "height": bottom - top,
                        }
                    except (OSError, ValueError) as exc:
                        rect, fallback = monitors[index], str(exc)
                else:
                    rect = monitors[0 if mode == "desktop" else index]
                if foreground()[0] != target["hwnd"]:
                    raise ValueError(
                        "Active window changed before capture; press the shortcut again"
                    )
                if self.timeline.state != "recording" or not self.accepting:
                    self._screenshot_skipped()
                    return
                captured = time.perf_counter_ns()
                pixels = screen.grab(rect)
            image = Image.frombytes("RGB", pixels.size, pixels.rgb)
            if min(image.size) < 2 or all(high == 0 for low, high in image.getextrema()):
                raise ValueError(
                    "Screenshot was empty or black (possibly a protected window); no image saved"
                )
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            payload = buffer.getvalue()
            with Image.open(io.BytesIO(payload)) as check:
                check.verify()
            number = max([e["number"] for e in self.session.screenshots()] + [0]) + 1
            # Include orphaned files so an interrupted commit is never overwritten.
            while (self.session.folder / f"screenshots/{number:03d}.png").exists():
                number += 1
            path = f"screenshots/{number:03d}.png"
            event = {
                "kind": "screenshot",
                "number": number,
                "path": path,
                "t": self.timeline.elapsed(captured),
                "monotonic_ns": captured - self.timeline.origin,
                "requested_monotonic_ns": requested - self.timeline.origin,
                "mode": mode,
                "bounds": rect,
                "fallback": fallback,
            }
            # Timing first, then PNG, then session index. Recovery rejoins completed pairs.
            atomic_json(self.session.folder / f"screenshots/{number:03d}.json", event)
            atomic_bytes(self.session.folder / path, payload)
            self.session.event(event)
            self.notify(
                "screenshot",
                f"Screenshot {number:03d} saved"
                + (f" (monitor fallback: {fallback})" if fallback else ""),
            )
        except Exception as exc:
            self.notify("error", f"Screenshot failed: {exc}")
        finally:
            self.screen_pending.release()

    def _screenshot_skipped(self):
        reason = "paused" if self.timeline.state == "paused" else "stopped"
        self.notify("warning", f"Screenshot skipped: recording {reason}.")

    def check_error(self):
        try:
            return self.errors.get_nowait()
        except queue.Empty:
            if self.accepting and (
                not self.stream.active or time.perf_counter() - self.last_callback > 3
            ):
                return "Microphone stopped responding. Check its connection and Windows microphone permission."
            return None

    def stop(self):
        # Called off the UI thread; close callbacks before draining the audio writer.
        event = self.timeline.transition("stopped")
        stop_error = None
        try:
            self.stream.stop()
        except Exception as exc:
            stop_error = exc
        finally:
            self.accepting = False
            try:
                self.stream.close()
            except Exception as exc:
                stop_error = stop_error or exc
            self.screens.shutdown(wait=True)
            if self.writer.is_alive():
                while self.writer.is_alive():
                    try:
                        self.audio_queue.put(None, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                self.writer.join()
        self.session.event(event, persist=False)
        self.session.finalize_audio(event["t"], persist=False)
        self.session.update(status="stopped", persist=False)
        self.metadata_pending.set()
        self._persist_metadata()
        if self.writer_error:
            raise OSError(f"Audio write failed; saved portion retained: {self.writer_error}")
        if stop_error:
            raise OSError(f"Microphone failed while stopping; saved audio retained: {stop_error}")
        if self.metadata_error:
            raise OSError(
                f"Audio saved, but session metadata could not be saved: {self.metadata_error}"
            )
        return self.session
