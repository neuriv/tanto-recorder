# Tanto Recorder

Read-only Nioh move recorder. The portable `TantoRecorder.exe` embeds its interface, capture worker, wallpaper and sounds; recipients need only that file.

`desktop/` contains Electron, TypeScript and CSS. Its main process owns sessions, descriptions, the global shortcut and streamed ZIP export; the sandboxed page handles presentation. Run `npm ci`, then `npm start` for development with the sibling Engine and Python.

`src/action_capture.py` samples all readable action nodes through two read-only Engine modules. It appends IDs before optional metadata, periodically syncs the journal and reports saved counts. Boss names label sessions without blocking capture.

New sessions use `encounter.json` for descriptions/take boundaries and `events.jsonl` for observations. Settings can reuse an old recording library. Export writes one ZIP directly to Downloads, retaining selected sessions and drafts; `recording_bundle.py` validates incoming archives for review.

`Build.ps1` uses Engine's version, pin, dependency, validation and checksum gates. See [CODE_GUIDE.md](CODE_GUIDE.md) for mechanisms. Offline checks do not establish gameplay acceptance.
