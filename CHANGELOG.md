# Release notes

## 0.2.0-alpha.2

- Start recording plays the supplied `t2wxkfk.wav`; Stop plays `6s3fj0w.wav`. Both files are bundled without trimming or conversion. Playback remains asynchronous, and Stop replaces any unfinished Start sound.
- Updated the guide and asset documentation to describe the new sounds.
- Strengthened one focused ZIP round-trip test: three sessions across two bosses, duplicate folder names, two takes per session, description revisions, archive integrity, exact raw bytes, repeated intake and untouched originals.
- Player-readable function/callback comments, mechanistic explanations and a code guide; Engine source pin refreshed after its review. Recorder still excludes gameplay hooks and memory-writing modules.

The release gate requires both offline suites and the packaged UI smoke check; results are recorded in `release.json` and `ui-smoke.json`. Audible playback, live-game and another-PC acceptance remain pending. The published 0.2.0-alpha.1 EXE, tag and receipts remain immutable.

## 0.2.0-alpha.1

- Explorer multi-folder selection exports complete sessions from one or several bosses to Downloads/tanto-zips. Intake validates and processes the whole collection; old individual ZIPs still work.
- Settings remembers a chosen recording library across releases. Existing sessions and saved descriptions remain compatible; changing libraries does not alter old takes.
- Press-to-bind keyboard shortcuts, cancellation and conflict feedback; F8 remains the default.
- Beveled glass Record, Settings and Guide tabs over the unchanged wallpaper. Larger text, bundled Inter fonts and a scrollable inline guide. Start / Stop remains accessible on every tab.
- Mandatory versioned release artifacts, annotated tag, hashes, exact source pins, offline tests and packaged UI smoke check.

Validation: 225 workflow tests and 8 resource tests passed through Test-Offline.ps1. The release gate also checks the packaged UI. Native Explorer interaction and visual acceptance remain manual checks; desktop capture was unavailable during development.

EXE builds require clean source, an exact Engine pin, the two maintained offline suites and immutable versioned artifacts. Live game, physical controller and another-PC acceptance remain pending.

## 0.1.0-alpha.1

Historical standalone preview. Later unversioned local EXEs are development builds and are not retroactively assigned this release identity.
