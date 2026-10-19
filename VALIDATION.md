# Validation record

## v0.5.1 release

On October 19, 2026, the Windows x64 release was built from main after PR #18 at
`dist/v0.5.1/QANarrator/QANarrator.exe`. All **178 tests**, Ruff for source/tests
and release scripts, the offline lockfile check, and `git diff --check` passed.
Source, installed package metadata, and the embedded executable report **0.5.1**.
Only the project version changed in the lockfile; dependency pins are unchanged.

The new regressions verify removal of invisible control/format characters, the
200-character label cap, and a paused shortcut press showing the skip message
without capturing an image. Packaged linked and embedded exports passed with
bidirectional overrides, zero-width characters, C1 controls, Markdown/HTML syntax,
and a 40,000-character title. Original session context remained intact, embedded
PNGs roundtripped exactly, and the packaged UI contains the paused-shortcut message.
Results are in ignored `.validation/release-v0.5.1/context/result.json`.

Native title/process lookup passed using a test widget, without microphone recording
or capturing other applications. Real offline CPU transcription with vocabulary
hints passed with the source socket guard, and the packaged executable passed
offline inference, exact embedded-PNG roundtrips, and native GUI launch/normal close.
Existing local model files were reused; models are not bundled in the release.

Packaged raw/compact/linked export and standalone shrinking passed. A within-budget
3840 × 2160 PNG retained its exact bytes. A 33,228,470-byte synthetic report compressed
to 7,411,154 bytes. Standalone shrinking preserved its input and manual notes.
Results are in ignored `.validation/release-v0.5.1/exports/result.json` and
`.validation/packaged-result.json`. The build dependency list contains no unrelated
Codex-runtime/Poppler DLLs. Existing README screenshots still match the layout.

The release ZIP includes updated documentation, screenshots, source license, and
bundled dependency licenses. Packaging verifies the executable version, complete
archive file list, and CRCs, and writes `SHA256SUMS.txt`.
The executable remains unsigned. Physical microphone/keyboard acceptance,
overflow/disconnect scenarios, and clean-machine deployment remain manual checks.

## v0.5.0 release

On October 15, 2026, the Windows x64 release was built from main after PR #14 at
`dist/v0.5.0/QANarrator/QANarrator.exe`. All **176 tests**, Ruff for source/tests
and release/window-context scripts, the offline lockfile check, and
`git diff --check` passed. Source and installed metadata both report **0.5.0**;
only the project version changed in the lockfile, with dependency pins unchanged.

Native title/process lookup passed using a test widget, without recording audio
or capturing other applications. Packaged linked and embedded exports retained
the executable basename, escaped title text, and focused-window label. Tests
cover opt-in defaults, immediate preference persistence, unavailable fields,
process-handle cleanup, monitor/fallback labels, and screenshot sidecar recovery.

Real offline CPU transcription with saved local `base.en` files and vocabulary
hints passed. The source smoke test blocked network access with a socket guard;
the packaged smoke used offline mode and also passed exact embedded-PNG roundtrips
and normal native GUI launch/close. The existing model files were reused from
the ignored validation directory; models are not bundled in the release.

Packaged raw/compact/linked export and standalone-shrink checks passed. An
in-budget 3840 × 2160 PNG retained its exact bytes. A 33,228,470-byte synthetic
report compressed to 7,411,154 bytes. Source files and manual notes were preserved.
Results are in ignored `.validation/release-v0.5.0/exports/result.json`,
`.validation/release-v0.5.0/context/result.json`, and
`.validation/packaged-result.json`.

The README previews were refreshed from actual widgets using an explicit isolated
INI file, example values, and no native shortcut registrations, then visually
inspected. The release ZIP includes the updated documentation and screenshots,
source license, and bundled dependency licenses. Packaging checks the embedded
version, complete archive file list, and CRCs, and writes `SHA256SUMS.txt`.

The executable remains unsigned. Physical microphone/keyboard acceptance,
overflow/disconnect scenarios, and clean-machine deployment remain manual checks.
Larger models were not added or benchmarked in this release.

## v0.4.0 release

On October 15, 2026, the Windows x64 release was built at
`dist/v0.4.0/QANarrator/QANarrator.exe`. Source and installed package metadata both
report **0.4.0**, and the embedded executable version was checked independently.
All **160 tests**, Ruff for source/tests and the new release scripts, the offline
lockfile check, and `git diff --check` passed. Only the local project version changed
in the dependency lock; dependency versions remain pinned.

A local `base.en` model was downloaded separately into the ignored validation
directory. Real CPU inference with vocabulary hints, word timestamps, and Markdown
export passed with network access blocked by the source smoke test. The packaged
executable also passed offline inference with hints, exact embedded-PNG roundtrips,
and native GUI launch/normal close. Models are not included in the release ZIP.

Packaged raw, compact, linked, and standalone-shrink checks passed. A within-budget
3840 × 2160 PNG retained its exact bytes; a 33,228,470-byte synthetic high-entropy
report compressed to 7,411,154 bytes. Standalone shrinking preserved manual notes
and its input; reports already within the target produced identical copies.
Results are in ignored `.validation/release-v0.4.0/exports/result.json` and
`.validation/packaged-result.json`.

Native mouse hook registration, dispatch, keyboard/mouse switching, and cleanup
passed on the Windows desktop. `smoke_shortcuts.py` also passed posted hotkey/mouse
callback dispatch, idle release, Start/Pause/Stop reservation, and settings reload.
These are synthetic dispatch checks; physical microphone recording, overflow/
disconnect acceptance, real keyboard-layout checks, and clean-machine deployment
remain manual. The executable remains unsigned.

README screenshots were refreshed from the actual widgets using an explicit,
isolated preview INI file and example output/vocabulary values. The previews were
visually inspected. Native shortcut registration was replaced only in this
documentation renderer; native shortcut behavior was checked separately above.

The ZIP includes the complete `QANarrator` folder, updated README/release notes,
validation record, screenshots, source license, and bundled dependency licenses.
`scripts/package_release.py` checks the embedded version, archive file list and CRCs,
then writes `SHA256SUMS.txt` beside the archive.

## Preserve images within budget and add vocabulary hints

On October 15, 2026, all **160 tests** passed with
`pytest -q --basetemp=.validation/preserve-vocabulary-all`; Ruff and
`git diff --check` passed. This addresses #4 and the vocabulary-hints portion of #6.

Compact export validates embedded images and returns the original Markdown bytes
when the complete report is at or below its target. Tests verify exact-boundary
and below-budget reports with 3840 × 2160 PNG and JPEG images, with image encoding
disabled to detect accidental re-encoding. Oversized-report compression, progressive
passes, quality-floor failures, invalid images, and previous-file preservation remain
covered. Compression/cancellation fixtures now explicitly exceed the target so those
tests still exercise image processing. Cancellation after the within-budget check
also leaves the original and existing copies intact. An explicit size check replaces
the final assertion after assembly.

Vocabulary tests verify whitespace normalization, Unicode, empty/default hints,
passing `hotwords` to the model while leaving previous-text conditioning disabled,
session and transcript metadata, reuse after failed inference and session reload,
explicit overrides, and clearing saved hints. GUI tests reopen saved preferences and
exercise retries using current/cleared field text. CLI tests cover omitted hints,
overrides, `--vocabulary=`, and invalid use without `--process`.

The installed faster-whisper source and its
[pinned v1.2.1 implementation](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)
support the `hotwords` argument used here. Inference tests use fake models; a real
offline smoke check was skipped because the local `base.en` model is unavailable.
Recognition quality has not been benchmarked. Larger models from #6 remain outside
this change, and no packaged build was made.

## Microphone overflow, remaining robustness fixes, and agent handoff

On October 15, 2026, all **144 tests** passed with
`pytest -q --basetemp=.validation/audio-guidance-final`; Ruff and
`git diff --check` passed. These changes address #8, the remaining #9 items,
and the documentation guidance requested in #3.

Device-enumeration tests cover matching a microphone's WASAPI endpoint, the Windows
Sound Mapper alias, a WASAPI default, saved/current selections, missing saved
devices, and the absence of WASAPI. No physical microphone selection was changed
during these tests.

Synthetic callbacks verify continuation after input overflow, exact silence padding
with ADC and fallback clocks, continued sample placement despite callback jitter,
repeated overflow without clock rewind, and removal of paused time from both audio
and reported gap duration. Overflow warnings persist with timestamps and an explicit
estimated-timing flag when ADC timing is unavailable. Mixed error flags,
disconnected/unresponsive streams, and a full audio writer queue remain fatal.

Fallback timing subtracts reported input latency with a one-buffer-duration floor.
It does not add the two delays: PortAudio defines reported input latency relative
to the callback buffer's first sample. See the
[PortAudio timing model](https://github.com/PortAudio/portaudio/wiki/BufferingLatencyAndTimingImplementationGuidelines#basic-bufferingtiming-model).
Without ADC timestamps, overflow gap duration remains an estimate that can include
callback scheduling delay.

Queued-screenshot tests pause or stop before worker execution and during capture
setup, checking the skip message, absence of a pixel grab, and slot cleanup.
Transcription-retry tests cover updated transcripts, byte-for-byte preservation of
manual Markdown edits, successful GUI/CLI messaging, later confirmed regeneration,
and propagation of unrelated export errors. Inference uses a fake model.

The README, settings hint, CLI help, and report headers recommend linked screenshots
for coding agents and explain why compact embedded images can still exceed text
reader limits. The 25 MB threshold is described as an application sharing target.
Real microphone overflow/disconnect recovery, listening checks, and packaged-app
validation remain manual; no packaged build was made for these changes.

## Recording reliability and shortcut fixes

On October 15, 2026, regression checks cover issues #7, #1, #2, and the saved-monitor
launch crash from #9. All **120 tests** passed with
`pytest -q --basetemp=.validation/issues-final-retry-pytest`; Ruff and
`git diff --check` passed. Metadata write failures preserve queued PCM, retry pending
events without duplicates, and do not prevent WAV finalization. Pause/resume saves
run on the writer, with a check that metadata is saved even without new audio.
Atomic replacement retries transient permission failures up to four attempts, with
at most 170 ms of backoff; checks cover exhausted retries, preserving the previous
file, temporary-file cleanup, and cancellation between attempts. A full-suite run
encountered a real transient `session.json` replacement denial before this retry
was added.

Synthetic Qt key events verify UK-style backtick, shifted tilde, German punctuation,
AltGr-style modifiers, and a letter whose native key differs from its Qt character.
Settings reload retains the native key, hides its storage suffix in labels, and
detects equivalent bindings. Invalid and null monitor settings reopen safely.

The mouse tests exercise one shared hook, dispatch while the owner thread waits,
queued Qt delivery, removal, registration failure/retry, and final thread shutdown.
A real Windows check passed shared hook registration on a separate thread, message
posting, partial subscription removal, and final unhook/join. The broader
`scripts/smoke_mouse.py` check reached keyboard registration but Windows denied
`RegisterHotKey` with error 5 in this environment. Physical keyboard-layout checks
and mouse input during a real recording remain manual. No packaged build was made.

## v0.3.0 release

On October 11, 2026, the release executable was rebuilt at
`dist/v0.3.0/QANarrator/QANarrator.exe`; its embedded package version was verified
as 0.3.0. All **95 tests**, lint, and the offline lockfile check passed.
The release executable passed compact/raw export, standalone shrinking, progress
callbacks, cancellation during save, offline synthetic transcription/export,
embedded PNG roundtrip verification, and GUI launch/normal close. The ZIP contains
the complete application folder, documentation, and bundled dependency licenses;
`SHA256SUMS.txt` provides the archive checksum.

## Cancel standalone Markdown shrinking

On October 11, 2026, **95 automated tests passed** with
`pytest --basetemp=.validation/pytest-shrink-cancel`; lint passed for `src` and
`tests`. Cancellation checks cover reading, scanning, image processing, assembly,
and the final save. A cancellation after the temporary output is flushed removes
that temporary file before it can replace the destination. Original files and
previous compact copies are preserved.

Qt worker tests verify the Cancel button, immediate cancellation acknowledgement,
suppression of stale progress updates, cleanup/restored controls, and a successful
retry with a fresh cancellation event. Cancellation during image encoding is
reported as cancellation rather than an invalid image. The ready-to-cancel and
cancellation-pending states were visually inspected with isolated settings and
mocked capture devices; the shrink worker itself ran normally.

The executable is `dist/shrink-cancel/QANarrator/QANarrator.exe`. Packaged
compact/raw exports, standalone shrinking, progress callbacks, and cancellation
during save passed, with no partial copy or temporary file left behind. Offline
transcription/export and GUI launch/normal close also passed.

## Screenshot optimization progress

On October 11, 2026, **87 automated tests passed** with
`pytest --basetemp=.validation/pytest-progress-final`; lint passed for `src` and
`tests`. Progress callbacks cover reading, scanning, screenshot preparation,
optimization by screenshot and pass, assembling, and saving. The multi-pass test
checks ordered progress across both images and compression passes. Transcription
forwards its progress callback into compact export.

Real Qt worker tests hold an image operation in progress to verify that its status
appears before completion, the activity bar is visible, and controls are disabled.
Success and failure both clear the activity bar and restore controls; shrink
failure replaces the in-progress status with an error. An offscreen preview of
the running task was also checked using isolated settings and mocked devices.
An additional regression test verifies that already-completed workers deliver
completion after queued progress, preventing a stale “Saving…” status. All 18
UI/shortcut tests passed after that correction, and lint passed again.

The final executable is `dist/shrink-progress/QANarrator/QANarrator.exe`.
Packaged compact/raw export, standalone shrinking, progress callbacks, offline
transcription, and GUI launch/normal close passed. The packaged Python archive
was also checked for the queued completion fix.

## Compact Markdown export

On October 11, 2026, **84 automated tests passed** with
`pytest --basetemp=.validation/pytest-compact-3`; lint passed for `src` and `tests`.
After the UI help-label layout correction, all 15 UI/shortcut tests passed again;
the expanded multi-image budget test also passed independently.

Coverage includes exact file-size accounting across images, progressive compression,
failure at the quality floor without overwriting an existing export, transparent
PNG preservation, invalid image handling, raw PNG byte preservation, preference
persistence, CLI and transcription forwarding, UI mode selection, size-warning
boundaries, and shrinking standalone Markdown without altering manual notes or
overwriting the original or a previous compact copy.

A deterministic high-entropy 3840×2160 fixture shrank from **33,227,636 bytes to
7,410,165 bytes**. A separate synthetic 4K interface with text and a noisy image
region shrank from 17.7 MB to 2.3 MB at 2560×1440; its text was visually inspected.
The Qt layout and background-worker completion were also checked with isolated
settings and mocked capture devices. Readability of every real screenshot and
support for data URLs in every Markdown viewer are not guaranteed by these checks.

The Windows build is at `dist/compact-export/QANarrator/QANarrator.exe`.
Packaged compact export, raw PNG roundtrip, and standalone shrinking all passed;
the embedded Python archive was checked for the final UI layout change.
`smoke_packaged.py --exe dist/compact-export/QANarrator/QANarrator.exe --embed-images`
passed offline synthetic transcription/export and GUI launch/normal close, with
`QA_NARRATOR_MODEL_DIR` pointing to the existing installed model folder because
the sandbox redirects the default application-data directory.

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

