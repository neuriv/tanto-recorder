# Tanto Recorder

Read-only Nioh move recorder. The portable `TantoRecorder.exe` embeds its interface, capture worker, wallpaper and sounds; recipients need only that file.

`desktop/` contains Electron, TypeScript and CSS. Its main process owns sessions, descriptions, the global shortcut and streamed ZIP export; the sandboxed page handles presentation. Run `npm ci`, then `Recorder.ps1 -PythonRuntime <python.exe>` for development with the sibling Engine.

`src/action_capture.py` samples readable action nodes through two read-only Engine modules. IDs reach the journal first; a bounded background reader collects full action payloads, transitions and resource context. Actor generations, missed counters and sampling gaps expose uncertainty. Death and pause do not have verified markers yet.

Choose a boss and press Enter for **Selected** feedback. Keep one session for that boss: Start, Stop, describe, then Start the next take. The interface distinguishes starting, synced IDs, final save and incomplete capture. Quick guide/F1 reopens the short tutorial.

New sessions use `encounter.json` for descriptions/take boundaries and `events.jsonl` for observations. Settings can reuse an old recording library. Export writes one ZIP directly to Downloads, retaining selected sessions and drafts; `recording_bundle.py` validates incoming archives for review.

`Build.ps1` uses Engine's version, pin, dependency, validation and checksum gates. See [CODE_GUIDE.md](CODE_GUIDE.md) for mechanisms. Offline checks do not establish gameplay acceptance.
