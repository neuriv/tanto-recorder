# Release notes

## 0.3.0-alpha.2

- Dim the wallpaper further and brighten text, labels and placeholders.
- Remove the static footer disclaimer and section/field divider lines.

## 0.3.0-alpha.1

- Replace the Python window with Electron, TypeScript and CSS: cleaner text, subtle wallpaper motion and lightweight controls.
- Capture action IDs from all readable actors. Boss labels and optional metadata no longer gate collection.
- Save one append-only action journal plus one session file; sync regularly and show actual saved-ID counts and failures.
- Restore drafts and interrupted sessions, including older recording libraries.
- Export selected sessions or the entire library into one ZIP directly in Downloads, including drafts and empty sessions.
- Add a fitted five-page guide, reopenable release notes and 40% default start/stop sound volume.

Live-game recording, extended play sessions and another-PC acceptance remain pending. Actor names remain encounter context; recorded IDs require review before becoming playable moves.

## 0.2.0-alpha.6

- Restore the full tutorial across six short pages: library setup, recording, descriptions, editing, exports, shortcuts and sounds.
- Show the updated tutorial once after upgrading. Quick guide, its header link and F1 always reopen it.
- Remove opaque section and tutorial backgrounds. Brighter serif text with subtle shadows sits directly over the unchanged wallpaper; inputs and buttons retain restrained surfaces.

Focused checks cover every tutorial page at default/minimum sizes, navigation, reopening and completion persistence. Packaged startup checks all six pages. Broad suites remain skipped; live-game and another-PC acceptance remain pending.

## 0.2.0-alpha.5

- Remove glass, blur and beveled image controls. Use solid dark panels, warm text and bundled Source Serif 4 Small Text.
- Restore compact 960×740 sizing, capped to the usable desktop. Correct panel alignment and preserve native dropdown text fields and arrows.
- Shorten the inline intro to four steps; fit the complete guide at default sizes and describe disabled hotkeys correctly. Settings text wraps with the window.

Focused layout checks cover 100%, 150% and 200% text scaling. Packaged startup checks guide fit, dropdown structure and font loading; broad offline suites remain skipped. Live-game and another-PC acceptance remain pending.

## 0.2.0-alpha.4

- Fix startup: reserve the volume label's width in its layout instead of passing an unsupported widget argument.
- Default new recording libraries to local AppData, keeping Downloads clear. Existing selected libraries still work.
- Share only `TantoRecorder.exe`; Python, fonts, wallpaper, sounds and the required read-only runtime are embedded.
- Shorten READMEs and release notes. A focused packaged startup check replaces the broad offline suites for this fix; its result is recorded in the release receipts.

Live-game, audible playback and another-PC acceptance remain pending.

## 0.2.0-alpha.3

Packaged as an untested prerelease for the user's external tester. Automated suites and packaged UI smoke execution were explicitly skipped at the user's request; receipts record this exception rather than borrowing older results.

- Settings adds remembered 0–100% volume for both recording cues, including mute, with Test start / Test stop buttons. Volume changes stop the current cue and apply to the next sound. Preview buttons are disabled while recording or exporting.
- Lower levels attenuate temporary PCM copies; packaged sounds, game audio and Windows mixer settings remain unchanged. Cached copies are removed on volume changes and shutdown.
- Includes the supplied start/stop sounds and ZIP verification from 0.2.0-alpha.2, which was compiled locally before the volume request and not published.

Volume behavior has not been tested. Audible playback, live-game and another-PC acceptance remain pending.

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
