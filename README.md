# Tanto Recorder

Read-only Nioh move recorder. Share only `TantoRecorder.exe` from this private repository's Releases. Python, the required runtime, wallpaper, fonts and sounds are embedded; no companion assets or repositories are needed.

A worker samples game state into session/take files. Tk handles the interface, and a bindable Windows hotkey queues Start / Stop. Saved descriptions keep revision history; unfinished text autosaves as a draft.

Sessions default to `%LOCALAPPDATA%/Tanto/Recorder/Recordings`. Settings can reuse another library. Export packages selected sessions into a ZIP under `Downloads/tanto-zips`, preserving each take, description history and file hashes.

Start and Stop play bundled WAVs at a remembered volume. Lower levels scale temporary PCM copies; zero mutes. Glass panels reuse the bundled wallpaper without screen capture.

Boss names provide context; only Okatsu, Jin and Maria have identification fingerprints. Recorded moves require developer review before use in a mod. Recorder does not change moves or control Nioh.

`Build.ps1` packages the pinned read-only Engine subset and records release provenance. Developers use the sibling Engine checkout; users need only the EXE. See [CODE_GUIDE.md](CODE_GUIDE.md) for details and the built-in Guide for usage.
