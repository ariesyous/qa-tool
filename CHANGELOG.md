# Release notes

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
