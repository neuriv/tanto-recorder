# Read Recorder as a Nioh player

Recorder watches game memory and saves observations for later move review. It does not play Nioh, inject gameplay hooks, change moves or capture the screen. Typing a boss name labels the encounter; only a configured action/motion fingerprint can verify an actor.

Keep 3–5 direct opening comments per function/callback: player-facing purpose, mechanism and the important constraint. Use inline explanations for thread ownership, native API contracts, atomic writes and evidence boundaries rather than comments that merely repeat names.

## The recording vocabulary

- A **library** contains saved sessions. It defaults to `%LOCALAPPDATA%/Tanto/Recorder/Recordings`; Settings can select another folder, including an older Downloads library.
- A **session** belongs to one named encounter and owns a manifest, numbered takes, saved description history and a draft. Its directory survives upgrades.
- A **take** is one raw observation file. Actor rediscovery can split one user recording interval into several takes; gaps remain explicit.
- An **annotation** describes a sampled interval in a take. Editing it adds a revision; it does not rewrite earlier wording or raw events.
- A **collection** is the new shareable ZIP containing several session ZIPs and an outer hash manifest. Different bosses and repeated folder/take names remain separate.
- A **fingerprint** compares stable source identities. An address is temporary; a name is context; consecutive observations are not proof of an executable combo.

## Follow Start, Stop, Save and Export

`launch.py` selects source or packaged paths and exposes only the read-only Engine subset. `src/recorder.py` owns the window and user workflow. Tk's thread changes widgets; capture/export threads publish messages into a queue. `poll` consumes those messages and rejects stale session or hotkey-generation events.

Start saves pending text, creates or resumes a session and launches `record_encounter`. Stop sets a cooperative event; the worker finishes writing before the UI permits another operation. The start sound requires a confirmed sampling state, not merely successful discovery. Settings saves `cue_volume` (0–100, default 100) for both cues. Lower levels scale temporary PCM copies; mute skips playback. A volume change stops the current cue and clears its cache before the next sound. Close waits for recording/export completion and keeps the window open if saving the draft fails.

`src/encounter_recording.py` owns discovery, take allocation, reconstruction and annotation history. It locks a session against competing writers, retains previous take files and reacquires changed actors. Reconstruction counts observed identity changes, preserves uncertain repeats and breaks sequences at gaps. `latest_sample_time` inspects the final 64 KiB of a take to bound a note; these sampled times are not exact animation-frame certification.

`src/recording_bundle.py` snapshots raw takes and saved labels, derives Summary.json and Descriptions.csv from those bytes, and hashes members. Collection export uses numbered inner ZIPs to prevent path collisions. Intake validates all sessions before staging evidence, rejects nested collections and caps expanded evidence at 512 MiB. It deduplicates raw bytes by SHA-256, flags conflicting descriptions/boss context and leaves review pending. An I/O failure during staging is still a failure; validation-first is not a multi-file database transaction.

`src/windows_paths.py` asks Windows for redirected Downloads and uses Explorer's COM folder picker for multi-selection. COM is Windows' interface-based object API: a GUID identifies an interface, a vtable slot selects its method, HRESULT reports success/failure, and acquired objects/path strings must be released. Picker cancellation returns an empty selection. Exports always go to Downloads/tanto-zips independently of the recording-library path.

## Keys and the interface

`src/recording_hotkey.py` translates readable shortcuts into Windows modifier/virtual-key numbers. A dedicated thread owns RegisterHotKey and its message queue. MOD_NOREPEAT suppresses held-key repetition; closing/rebinding unregisters the old key. Listener generations prevent already queued old-key messages from toggling a new session. No key is synthesized for the game.

`src/recorder_theme.py` places solid dark panels over the bundled wallpaper. Nested labels share their panel's color; frame backgrounds include padding so their pixels align. Native control layouts preserve dropdown fields and arrows. Window bounds and local text scaling keep the minimum layout inside the usable desktop; no other application or Windows preference is changed.

Bundled Source Serif 4 Small Text fonts load privately, with installed serif fallbacks. The four-step `QuickGuide` fits the default window and scrolls when necessary. Guide/F1 reopens it; Start/Stop remains above every tab. `SequenceList` shortens previews while keeping complete descriptions. Double-click/Return opens the full text for revision.

## Files, schemas and packaging

| Location | Contents and interpretation |
|---|---|
| `product.json`, `Build.ps1`, `requirements.txt` | Product name/version/Engine pin, the shared release-gate launcher, and the pinned Pillow dependency. |
| `data/bosses.json` | Shipped name suggestions and the supported encounter metadata. Name coverage exceeds fingerprint coverage. |
| `data/catalogue.json`, `data/encounters/` | Historical development observations/reconstructions, excluded from the consumer package. |
| `captures/` | Retained raw JSONL evidence; `index.json` records provenance/hashes and `summary.json` records derived reporting. Never add comments or alter raw events. |
| `summarize.py` | Rebuilds the development capture report against known source identities without changing raw evidence or playable definitions. |
| `src/assets/` | The unchanged wallpaper, local cue WAVs, bundled font files and their licenses/provenance README. Binary assets are explained, not rewritten as code. |
| `%LOCALAPPDATA%/Tanto/Recorder/settings.json` | Chosen library, shortcut, guide version, last session and unfinished draft. Each active session also has its own draft.json. |
| Session `encounter.json`, `take-*/events.jsonl`, `labels.jsonl` | Encounter context, sampled events, and append-only description revisions. Older labels receive explicit legacy IDs during parsing. |
| `.gitignore`, `.gitattributes` | Keep generated runtime/build output out of commits and preserve text/binary handling. |

JSON/JSONL does not permit comments. These schema explanations and the source validators provide the commentary without corrupting evidence. Hex addresses, unknown flags and opaque byte slices are not assigned invented meanings.

Every EXE uses Engine's `RELEASES.md` contract. Engine's two entrypoints are reused through `Test-Offline.ps1`; `--ui-smoke` checks the packaged window using temporary data and disabled game access. Offline checks, native picker/visual review, live-game acceptance and another-PC acceptance are separate evidence. Comment-only source changes do not replace or re-tag the published 0.2.0-alpha.1 package.
