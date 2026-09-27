# How Recorder works

Recorder observes Nioh; it never sends game input, injects hooks, writes game memory or records the screen. A boss name is your encounter label. Capture includes every readable action node because the described movement may belong to any actor in the final observations.

`desktop/main.ts` owns the lifecycle, OS shortcut and user workflow. `preload.ts` exposes a small command bridge to a sandboxed page; `renderer.ts` and `style.css` handle presentation. The page gets no process handle or arbitrary filesystem API. A renderer restart does not stop the capture worker.

`launch.py` starts `src/action_capture.py`. It reuses Engine's researched process/build checks and read-only discovery. It writes a coherent full action ID before requesting optional motion/transition metadata. Missing fingerprints and controllers cannot prevent capture. The user's boss name never assigns actor identity.

Discovery uses a separate read-only handle while known actors keep sampling. A vanished actor becomes a gap; others continue. The metadata cache holds at most 8,192 entries and UI memory retains twelve observations. Sampling targets 10 ms and records long gaps; brief actions can still be missed.

The worker appends the journal independently of renderer IPC. Flush and fsync run at approximately one-second health checkpoints and Stop; displayed counts advance only after successful sync. Abrupt termination may lose the unfinished checkpoint. Disk errors end capture visibly. An OS byte lock excludes another writer without a lock sidecar.

New sessions have two files: `events.jsonl` stores observations, diagnostics and take IDs; `encounter.json` stores boss context, take boundaries, descriptions and draft/edit target. Each Start gets a unique take and elapsed clock. `storage.ts` syncs temporary metadata before replacing the previous document. Close drains queued draft saves, then waits for the worker's final sync.

Restoration streams the journal to recover counts without loading all observations. A truncated final row is retained, separated from later appended rows and reported. Older raw takes, `labels.jsonl` and `draft.json` remain untouched. Legacy revisions fold by `label_id` for display; their original history remains in exports.

Review starts with the final action executions before Stop and matches their ordered IDs to the description. Retain all actors as candidates. Merge repeated polling only within the same execution; preserve actual repetitions and look past idle/recovery when needed. Full IDs, source context and timestamps matter. Review priority and stance are separate; adjacency never proves a playable combo.

`desktop/export.ts` accepts selected sessions or a parent library. It streams regular files, hashes the exact bytes and supports ZIP64. Draft-only sessions remain included. Folder dialogs suspend recording actions; export locks editing. Output failure aborts upstream streams and removes its partial file. Only a closed, synced archive receives its final ZIP name in Windows' actual Downloads directory.

`recording_bundle.py` accepts the new flat archive and both legacy ZIP formats. Intake streams hashes/extraction, rejects unsafe paths and conflicting identities, checks free space and stages complete evidence by archive hash. It flags empty sessions and malformed rows. Legacy reconstruction/report functions remain offline developer tools; intake never installs MWM moves.

Preferences live under `%LOCALAPPDATA%/Tanto/Recorder`; the default library is its `Recordings` subfolder. Existing libraries need no migration or move. Electron owns the bindable shortcut and suspends it during binding. Supplied WAV cues use application-local volume, default 40%; Stop replaces unfinished Start audio. These are sounds, not controller vibration.

The original wallpaper moves through a slow CSS transform instead of a large GIF; reduced motion disables animation. Five tutorial pages remain available through Quick guide/F1. What's new displays the shipped changelog with the same image in its banner; it does not fetch or install updates.

The release gate bundles only `action_capture`, `boss_probe` discovery/metadata and `nioh_memory` in the worker; Electron carries assets once. Recorder's EXE excludes Tk, controller reading, gameplay DLLs, historical captures and offline intake. The npm lock pins desktop dependencies. Engine's two entrypoints remain under `Test-Offline.ps1`; packaged `--ui-smoke` disables game access and uses temporary settings. Gameplay and another-PC acceptance remain separate.
