# Tanto Recorder

Read-only Nioh boss and enemy recording for contributors. The Windows EXE is a private test build; live game/hardware acceptance remains pending. It does not modify the game, inject a runtime, control the character, or capture the screen.

## Record a sequence

1. Enter the **boss or enemy name** before starting. Known names are suggestions; any name is accepted. Keep one named encounter per session.
2. Press **Start recording** or the global hotkey (**F8** by default). Wait for **Recording** before fighting. Discovery can take time.
3. After the interesting sequence, pause Nioh yourself and press the same key to stop. Wait for **Stopped** so the raw take is flushed.
4. Write in the always-visible **Sequence description** box. Drafts save automatically, even before samples exist. Click **Save description** or **Ctrl+S** after stopping. Include the weapon, opening motion, strikes, and whether you were hit. The description covers the latest take since its previous description; exact frame boundaries remain unverified.
5. Resume with the same hotkey for another sequence. Pending text is saved against the stopped take first. **New session** keeps the previous session and draft. **Open session** restores descriptions and unfinished text. The last session reopens at startup. Double-click a saved description to revise it.
6. Stop, save descriptions, then **Export ZIP**. Share the ZIP from Downloads / Tanto Recordings / Exports manually. Nothing uploads automatically.

The hotkey uses Windows registration. Choose F6–F11, Ctrl+Shift+R, or Off. Holding it does not repeat the toggle. Conflicts appear beside the selector. Hotkeys are ignored during export and shutdown; typing notes does not block Stop. A rising tone confirms sampling has begun; a falling tone acknowledges the finished worker. Waiting for Nioh does not produce a recording-start sound. These are local audio cues, not controller vibration. The indicator is static; Reduce motion was removed.

Preferences, boss name, last session and draft live in `%LOCALAPPDATA%/Tanto/Recorder/settings.json`. Each session also keeps `draft.json`. Writes use flushed temporary files and atomic replacement. Save failures remain visible and prevent close/session changes from discarding current text. The menu includes 42 boss names and remembers custom names after recording starts. Added names remain unverified. Menu names were checked against the [boss roster](https://nioh.fandom.com/wiki/Category%3ANioh%3A_Bosses) and [Complete Edition index](https://steamcommunity.com/sharedfiles/filedetails/?id=2994481092).

The red/black/gold window uses a subdued Japanese-character-dithered wallpaper. Labels and layout backgrounds sample the wallpaper; editable fields have a distinct dark surface. Rounded controls retain readable Windows UI fonts; headings use installed Japanese fonts with fallbacks. The inline editor resizes with the window. Export runs on a worker so the UI remains responsive. Closing waits for recording/export to finish rather than terminating evidence writes. A short local guide opens on first normal launch; click **Quick guide** or press **F1** to reopen it. It never opens a browser, remains available while recording, and does not block F8. Completing it stores a per-user preference.

## Identification and evidence

A typed name supplies **encounter context**, not proof of actor identity. Okatsu, Jin Hayabusa, and Maria have configured action/motion fingerprints. A unique validated match is displayed as **boss verified**. Other names record discovered actors as **identity unverified**. Record the intended enemy away from unrelated fights where possible, and describe any other enemies present. William's observations remain separate player context; collection of his base moveset is a later developer task.

Unknown encounters rediscover actors after each 30-second scout take and after actor/process loss. These are separate takes with explicit gaps, not an uninterrupted timeline. Unknown actors retain bounded source transition metadata (up to 32 rows per descriptor); this does not promote them to a verified boss. Pausing the game does not itself split a take. Hotkey start/stop brackets a capture; polling and discovery cannot establish exact animation-frame boundaries.

Sessions live in `Downloads\Tanto Recordings` and exports in its `Exports` subfolder. Windows resolves the current user's actual Downloads location, including moved or redirected folders; no account name or fixed drive is embedded. The ZIP includes raw JSONL takes, description revision history, a hash manifest, `Descriptions.csv`, and `Summary.json`. The original entered name survives export and intake. Reports are reconstructed from the exact exported raw bytes. A ZIP is published only after its write completes; failed writes leave no partial shareable archive.

An observed change of action identity counts as an entry. The first observation after a gap is censored; counter/pointer changes alone are uncertain re-entries. Repeated action sequences and native transition rows support candidates for review, not verified strings or executable combos. Unassigned actors remain unattributed. Correcting a description retains earlier revisions.

## Development and review

On Windows, clone private `neuriv/tanto-engine` beside this checkout at the revision in `product.json`. Run `python -B launch.py` with Python 3.12 and Tk installed. For source development, install `requirements.txt` (Pillow supplies wallpaper scaling); the EXE bundles it. Both private source checkouts are needed for this workflow; the intended later contributor package will include only the read-only backend and need neither Python nor the development engine. Build the current EXE with `Build.ps1 -PythonRuntime <build-python>` using the pinned engine build requirements. The EXE bundles Python/Tk and only the read-only engine subset; contributors do not need the engine checkout. Older EXEs are not automatically updated.

`data/bosses.json` is the only shipped data file. `captures/` retains shared Okatsu/Jin/Maria evidence with hashes in `captures/index.json`. `data/catalogue.json` and `data/encounters/` hold historical observations for development and are excluded from packaging. Raw bytes and historical provenance paths remain unchanged. The builder selects only four engine modules: `nioh_memory`, `boss_probe`, `action_banks`, and `controller_reader`. MinHook and gameplay modifications are excluded.

Run the two existing test entrypoints through `tanto-engine\Test-Offline.ps1`. They cover actual wallpaper dimensions/pixel alignment, local-guide opening and persistence, evidence handling, package boundaries, hotkey registration/conflict/release and Windows-message-to-worker start/stop delivery without key injection, start/stop/shutdown, background export, and layouts at multiple font scales. No additional test command is maintained here. Live hotkey operation with Nioh focused, actual captures across death/reload, and a friend's machine still need validation. Offline tests do not certify gameplay or every boss.

Contributor intake: `python -B launch.py --intake "submission.zip" --intake-dir "review-folder"`. It validates paths, sizes, hashes, manifest shapes, and description bounds before staging review evidence. Raw takes are stored once per SHA-256; duplicate submissions return the same report. Conflicting labels, duplicate evidence submitted under different bosses, and disagreement with raw encounter context are flagged. Every report stays `pending`; intake never edits curated definitions.

Next: validate one short known-boss session and one unknown-enemy session; check their labels and intake reports before a longer friend recording session. A private Recorder EXE is prepared for this validation; it is not a claim of live compatibility. The Sword product GUI and William's base data remain separate later work.

## Capture model and next simplification

The current model is an encounter (entered name and verified identity when available), numbered raw takes (split on rediscovery), and editable descriptions tied to intervals within a take. Stop requests reach the capture worker cooperatively; the UI waits for final flush and reconstruction before allowing resume/export. Windows posts the registered hotkey to its owning thread, which queues a toggle for Tk. Tk alone changes UI state; the capture thread never calls Tk. `MOD_NOREPEAT` prevents key auto-repeat, and a generation discards messages from an old registration after remapping.

The next useful abstraction is a **clip**: one user-requested start/stop interval plus a description, containing references to one or more raw takes. Discovery gaps would remain explicit inside a clip instead of forcing contributors to understand take files. A later explicit Armed state could validate actors before a clip starts and optionally retain bounded pre-roll, reducing missed openings; it must visibly distinguish memory observation from writing a recording. Neither multi-take clips nor pre-roll is implemented yet. Boss names remain context, and sampled sequences remain evidence requiring review.

The `--ui-smoke` check exercises rendering, the local guide, real description writes/readback, and draft restoration in a temporary fixture with game access and global hotkeys disabled. It records callback errors instead of reporting success before the event loop has run. Packaging includes `src/assets/background.png`, `start.wav`, and `stop.wav`; source and packaged launches use the same asset path contract.
