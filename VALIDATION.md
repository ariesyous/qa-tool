# Validation record

## v0.2.0 release

The release build at `dist/v0.2.0/QANarrator/QANarrator.exe` was rebuilt from source
with package version 0.2.0 on October 10, 2026. All **68 tests** and lint passed.
The final executable passed `smoke_packaged.py --exe
dist/v0.2.0/QANarrator/QANarrator.exe --embed-images`, covering offline synthetic
transcription, Markdown export, embedded PNG roundtrip verification, and GUI
launch/normal close. The release ZIP includes the complete application folder and
dependency licenses. SHA256SUMS.txt provides the ZIP checksum.

## Standalone backtick and Scroll Lock update

On October 10, 2026, **68 automated tests passed**
(`pytest --basetemp=.validation/pytest-standalone-shortcuts`), and lint passed.
New coverage checks both keys in the picker with and without modifiers, ignored
autorepeat events, native key codes and no-repeat flags, duplicate detection,
and settings persistence/reload. Backtick maps to the US-layout backtick/tilde key.

The native `scripts/smoke_shortcuts.py` check passed with standalone backtick and
Scroll Lock among six active bindings. Registration, posted-message dispatch,
cleanup, and reload passed. The additional-shortcuts preview was visually checked.
Physical key presses during recording are not covered by this automated check.

The rebuilt executable is at `dist/standalone-shortcuts/QANarrator/QANarrator.exe`.
`smoke_packaged.py --exe dist/standalone-shortcuts/QANarrator/QANarrator.exe
--embed-images` passed offline synthetic transcription, export, embedded PNG
roundtrip verification, and GUI launch/normal close.

## Multiple screenshot shortcuts update

On October 10, 2026, **61 automated tests passed**
(`pytest --basetemp=.validation/pytest-multiple-shortcuts`), and lint passed for
`src`, `tests`, and `scripts/smoke_shortcuts.py`. Coverage includes six keyboard
bindings, mixed keyboard/mouse bindings, unique native registration IDs, cleanup,
partial registration failure, duplicate detection regardless of modifier order or
case, legacy settings, persistence/reload, add/change/remove, the five-extra limit,
cancel, conflict restoration, and recovery after restoration fails.

`python scripts/smoke_shortcuts.py` passed on the native Windows desktop with
three keyboard and three mouse shortcuts active together. Each posted keyboard
message and mouse callback fixture dispatched once. Removal, cleanup, reload, and
the real Qt settings/dialog UI passed; the one-shortcut and six-shortcut previews
were visually inspected. The script uses isolated settings and records no audio.
Physical key/button presses while recording remain a human acceptance check.
The sandbox denies global keyboard registration (Windows error 5), so the native
check ran outside it.

The updated executable was rebuilt with
`scripts/build.ps1 -OutputDirectory dist/multiple-shortcuts` and is available at
`dist/multiple-shortcuts/QANarrator/QANarrator.exe`. The packaged smoke test passed
offline synthetic transcription/export, embedded PNG roundtrip verification, and
GUI launch/normal close using `smoke_packaged.py --exe
dist/multiple-shortcuts/QANarrator/QANarrator.exe --embed-images`.

## Portable Markdown update

**49 automated tests pass** (`pytest --basetemp=.validation/pytest-portable`); lint
passes. New checks decode every embedded image from a copied standalone Markdown
file and compare it byte-for-byte with the original PNG, verify image dimensions,
image/text ordering, linked-mode compatibility, saved session mode, mode switching,
manual-edit protection, missing/unsafe/corrupt image handling, empty sessions,
transcription-to-export preference forwarding, and both CLI flags.

The real Qt settings UI and immediate preference persistence passed the UI smoke test.
The layout was visually inspected. Embedded-image rendering is viewer-dependent;
these checks establish portable image bytes, not compatibility with every Markdown
renderer or automatic visual ingestion by every coding agent.
The current executable is built separately at `dist/portable-update/QANarrator`.
The final packaged executable passed offline synthetic transcription, portable export,
byte-for-byte decoding of all five embedded PNGs, and GUI launch/normal close using
`smoke_packaged.py --exe dist/portable-update/QANarrator/QANarrator.exe --embed-images`.
The real Qt worker completion path also passed the UI smoke check.

## Shortcut picker update

The current source has **38 passing tests** (`pytest --basetemp=.validation/pytest-shortcut-final`).
New checks cover recording keyboard and middle/side mouse presses, modifiers, cancel,
unsupported keys, immediate persistence, restoring the previous binding on registration
failure, and triggering only on button-down. Native `smoke_mouse.py` passed hook setup,
callback dispatch, keyboard/mouse reconfiguration, and cleanup; it calls the hook
callback with fixture events and does not claim physical mouse presses were tested.
The updated UI preview was visually inspected. Existing user shortcut settings are
preserved. The build is placed in `dist/shortcut-update/QANarrator` because the original
executable was still running. Close the old instance before using the updated build.
The updated executable passed the packaged inference/export and GUI launch/close
smoke test using `smoke_packaged.py --exe dist/shortcut-update/QANarrator/QANarrator.exe`.

Tested locally on Windows 11 x64 on October 9, 2026 using Python 3.12.13 and the
dependencies in `uv.lock`. This document distinguishes automated integration checks
from the full human acceptance scenario.

## Automated tests: PASS

`python -m pytest -q --basetemp=.validation/pytest-final-28`: **28 passed**.
`python -m ruff check src tests`: **all checks passed**.

Coverage includes:

- Monotonic timestamps and repeated pause/resume boundaries, including buffers that
  cross more than one state transition.
- Five screenshots interleaved through a sentence, exact word order, equal-time
  ordering, and screenshots completing out of timestamp order.
- Missing/inconsistent word timing fallback without changing the original text.
- Valid relative image paths; rejecting missing images and paths outside the session.
- Atomic session updates from concurrent writers, unique directories, reopening.
- Recovery from partial PCM samples and interrupted screenshot/index commits;
  recognizing interrupted transcription and avoiding duplicate recovery events.
- Markdown regeneration and protection of manually edited output.
- Failure during lazy transcription iteration, retry success, preserving previous
  audio and transcript on failed retry.
- PCM padding/overlap handling, disk errors, cleanup after device-stop failure,
  contiguous audio under callback jitter, disabling screenshots outside recording,
  persisting timing warnings without the UI, isolated screenshot failure, and rejecting
  a delayed capture after foreground focus changes.
- Hotkey syntax validation.

Tests use mocks for device/error scenarios. These are not proof of hardware behavior.

## Native Windows smoke checks: PASS

`python scripts/smoke_ui.py` constructed the real PySide6 UI, populated microphones
and monitors, registered the global hotkey, checked idle controls, rendered a preview,
and closed/released the hotkey. The offscreen preview was visually inspected.

`python scripts/smoke_native.py --record-microphone` explicitly recorded the default
physical microphone for about 4.7 seconds with a one-second pause. It produced about
3.7 seconds of WAV audio and five valid PNGs of a dedicated native test window.
Screenshot timestamps were chronological. The test image was visually inspected.
Registration of a conflicting hotkey failed as expected. A posted `WM_HOTKEY` was
received through Qt's actual Windows native event filter.

This tested the default MME microphone, which lacked reliable ADC timestamps and
therefore exercised the documented continuous sample-clock fallback. The machine
exposed two monitors (3840×2160 and 2560×1440); the native screenshot test used the
test window on one monitor. These tests needed a normal interactive Windows process:
the execution sandbox denied `RegisterHotKey` with Windows error 5.

Physical keypress delivery while another real app is focused is **not established**
by posting a Windows message. The test did not narrate or measure microphone speech
accuracy, unplug a microphone, change DPI scaling, suspend Windows, or remove a monitor.

## Real local transcription: PASS

A roughly 14-second English WAV was generated locally by Windows SAPI. No cloud
speech API was used. `python scripts/smoke_transcription.py` loaded the actual
`base.en` faster-whisper model on CPU with int8, decoded the WAV, returned word-level
timestamps, wrote transcription JSON, and exported five screenshot links. It also
reopened the completed session from disk.

The process set `HF_HUB_OFFLINE=1` and replaced Python socket connection functions
with failures. Inference and export succeeded. This verifies the exercised local
path; it is not an OS-wide packet-capture audit. The sample export was inspected,
including an image splitting the final sentence. Whisper appended an erroneous word
in the fixture result; the app preserved that recognition result instead of rewriting
it. Real human speech quality still needs acceptance testing.

An initial inference failure exposed incompatibility between PyAV 19 and
faster-whisper 1.2.1. PyAV 16.1.0 is now locked; inference was rerun successfully.

## Packaging

The reproducible command is `scripts\build.ps1`; the entry point is
`dist\QANarrator\QANarrator.exe`. The full sibling `_internal` directory is required.
The default model is stored separately under `%LOCALAPPDATA%\QANarrator\models`.

`scripts/smoke_packaged.py` passed real inference/export through the executable and
launched/closed its GUI normally. The build script sanitizes `PATH`: an initial build
incorrectly collected an incompatible ICU DLL from an unrelated Poppler installation,
preventing Qt from loading. Removing the unrelated DLL resolved the failure, and the
reproducible build uses only the virtual environment and Windows system directories
for its PATH-based dependency lookup.
The final clean build was repeated successfully; its generated dependency list contains
no Codex-runtime/Poppler DLLs. The final executable again passed synthetic offline
inference/export and normal GUI launch/close (`.validation/packaged-result.json`).
Clean-machine deployment, code signing, and SmartScreen reputation are not tested.

## Human acceptance checklist: still required

1. Launch the executable. Select the microphone's WASAPI entry and confirm the
   output folder and `base.en` model. Start Recording and minimize the app.
2. Open a real browser app. Narrate naturally for several minutes while switching
   between two browser windows. Use **physical Ctrl+Alt+F9 presses** at least five
   times, including twice within one sentence. Check the taskbar confirmations.
3. Pause for at least ten seconds, speak during the pause, and try the hotkey.
   Resume; confirm neither paused speech nor the attempted screenshot was saved.
4. Stop. Wait for local processing. Listen to `audio.wav`, compare its content to
   `transcription.json`, and inspect each image in `feedback.md`. Check chronological
   placement and all relative links. Model timing is approximate; record any material
   misalignment and whether the session reports an ADC fallback warning.
5. Close/relaunch, reopen the same session, and regenerate Markdown. Add a manual
   note to the Markdown and confirm regeneration asks before replacing it.
6. Repeat screenshot checks on each monitor at the normal DPI settings, with
   windowed/maximized apps, selected-monitor and all-monitor capture. Check that
   QA Narrator is not the foreground window when pressing the shortcut.
7. In a disposable session, unplug the selected microphone. Confirm the error is
   visible, recording stops, and saved audio/images remain. Reconnect and refresh.
8. In another disposable session, capture an image and record for ten seconds; end
   only the QA Narrator process in Task Manager. Relaunch and recover the incomplete
   session. Validate WAV playback, screenshot references, and retry transcription.
9. Disconnect the network after model installation and repeat a short session.
10. Give the completed folder to the chosen coding agent and confirm it can read
    the Markdown and every referenced image without special software.

## Reproducing integration checks

Native checks briefly open a test window; `smoke_native.py` records the microphone
only with the explicit `--record-microphone` flag. Fixtures/results remain local in
ignored `.validation/`. The offline speech fixture can be created with PowerShell:

```powershell
New-Item -ItemType Directory -Path .validation -Force | Out-Null
$voice = New-Object -ComObject SAPI.SpVoice
$audioFile = New-Object -ComObject SAPI.SpFileStream
$audioFile.Open((Join-Path $PWD '.validation\speech.wav'), 3)
$voice.AudioOutputStream = $audioFile
$null = $voice.Speak('I am creating a new program. This Save button should say Create. Now I am submitting the form. There is no confirmation message. The results page is taking a long time to load.')
$audioFile.Close()
uv run python scripts/smoke_ui.py
uv run python scripts/smoke_native.py --record-microphone
uv run python scripts/smoke_transcription.py
uv run python scripts/smoke_packaged.py
```

