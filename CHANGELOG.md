# Release notes

## 0.5.2 — October 19, 2026

- Compact export compresses the largest screenshots first and stops as soon as
  the report fits. Untouched images keep their original bytes and are checked
  for invalid or truncated image data before the compact copy is saved. (#15, #19)
- Vocabulary hints keep whole terms within faster-whisper's token limit instead
  of silently cutting a term. Unused hints are reported in the UI and saved in
  the session and transcript metadata. (#16)
- Stop retries locked session metadata and retains the complete session in memory
  for background retries. New recordings wait until the pending metadata saves.
  Audio errors remain visible after saving and reopening, and require explicit
  recovery instead of automatic transcription. (#17)
- A screenshot whose PNG and timing sidecar were saved no longer reports failure
  when only the session index is temporarily locked. (#17)
- Existing settings, sessions, and downloaded models can be reused.

## 0.5.1 — October 19, 2026

- Exported screenshot labels remove Unicode control and format characters,
  including bidirectional overrides, zero-width characters, and C1 controls.
  Each app/title field is limited to 200 characters before Markdown/HTML escaping,
  with an ellipsis for shortened fields. Emoji joiners are also removed. Original
  context in session files and screenshot sidecars is preserved. (#18)
- Pressing a screenshot shortcut while paused now displays
  "Screenshot skipped: recording paused." and captures no image. The shortcut
  remains reserved until Stop, as before. (#18)
- Updated the README's download and build examples and documented label formatting
  and paused-shortcut feedback. Existing settings, sessions, and models can be reused.

## 0.5.0 — October 15, 2026

- Optional screenshot context records the focused window title and executable name,
  off by default. Markdown escapes the labels and identifies the focused window
  for monitor captures. Unavailable metadata does not prevent screenshots. (#5)
- The preference saves immediately and applies to new screenshots. Disabling it
  does not remove context from existing sessions or exports. Only the executable
  basename is stored, never its full path. Context survives sidecar recovery.
- Updated README screenshots show the new setting. Existing settings, sessions,
  and downloaded models can be reused; models are still downloaded separately.

Vocabulary hints shipped in 0.4.0. Larger models remain deferred under #6 pending
Windows CPU performance and compatibility validation; contributions are welcome.

## 0.4.0 — October 15, 2026

### Added

- Optional vocabulary hints for product names, UI terms, acronyms, and phrases.
  Enter them in Settings or pass `--vocabulary` with `--process`. Hints are saved
  with the session and transcript; the CLI can reuse, override, or clear them.

### Fixed

- Compact export preserves image bytes, format, and resolution when the complete
  report already fits the 24 MB target. Oversized reports still use progressive
  compression. The final size guarantee uses an explicit error check. (#4)
- Metadata write failures retry without stopping microphone capture or duplicating
  warning events. Stop finalizes the WAV before reporting outstanding metadata
  errors. Transient atomic-replacement permission failures have bounded retries. (#7)
- Keyboard shortcuts are reserved only during recording. Recorded shortcuts retain
  native Windows key codes on non-US layouts, including shifted tilde. Previously
  saved backtick shortcuts keep their old mapping until recorded again. (#1, #10)
- Mouse shortcuts share one hook on a dedicated message thread, independent of
  GUI work and session writes. (#2)
- First-time microphone selection prefers WASAPI while preserving saved choices.
  Input overflow produces a warning and continues recording, retaining gaps as
  silence with estimated timing when ADC timestamps are unavailable. (#8)
- Fallback audio timing compensates for input latency. Paused time remains excluded
  from saved audio and overflow-gap durations. Queued screenshots skipped by Pause
  or Stop report what happened. (#9)
- Null or invalid monitor settings no longer crash launch. Successful transcription
  retries keep manually edited Markdown and show a clear success message. (#9)

### Documentation and distribution

- Recommend linked screenshots for coding-agent handoffs and explain embedded-image
  text-reading limits. The 25 MB sharing threshold is an application target. (#3)
- Include a repeatable release-packaging command, version verification, ZIP integrity
  checks, bundled documentation, and a SHA-256 checksum.
- The Windows x64 app remains portable and unsigned. Models are downloaded separately;
  existing settings, sessions, and models can be reused. Physical microphone/keyboard
  acceptance and clean-machine deployment remain manual checks.

Vocabulary hints address part of #6; optional larger-model support remains open.

Earlier releases: [v0.3.0](https://github.com/ariesyous/qa-tool/releases/tag/v0.3.0),
[v0.2.0](https://github.com/ariesyous/qa-tool/releases/tag/v0.2.0), and
[v0.1.0](https://github.com/ariesyous/qa-tool/releases/tag/v0.1.0).
