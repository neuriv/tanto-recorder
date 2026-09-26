# Tanto Recorder

A standalone, read-only Windows application for collecting Nioh boss move data. Contributors receive `TantoRecorder.exe`; they do not install Tanto Engine, Python or developer tools. The application does not modify the game, inject a runtime, control the character or capture the screen.

Choose a boss and press **Record new**. Wait for **Ready to fight** before beginning. Recording continues through moves and attempts to reacquire the boss after reloads. Pause Nioh yourself after a meaningful sequence, choose **Describe last move**, and enter an ordinary description. Select the take and edit start/end seconds; add **Repeat**, **Unsure** or **Interrupted** when appropriate. Boundaries are estimates within the take's recorded duration. Double-click a saved label to correct it; earlier revisions remain in the evidence. Press **Stop**, wait for **Stopped**, then **Export**.

**Open session** reopens a folder under `Downloads\Tanto Recordings` for labeling or export without attaching to the game. **Resume session** retains that session's identity and starts a new numbered take, preserving earlier data, including interrupted captures.

Export writes one ZIP to Downloads and opens its folder. It contains raw JSONL takes, label revision history, a hash manifest, `Descriptions.csv` with current labels, and `Summary.json` with source action identities, ordered sequences, occurrence counts, capture gaps and confidence. Sharing is manual. A change of action identity is an observed entry; the first observation after a gap is censored. Counter or pointer changes alone are uncertain re-entries. Repeated sequences and matching native transition rows are candidates for review; recorded conditions do not prove a combo executed. Unassigned actors remain unattributed.

## Development

Clone the private `neuriv/tanto-engine` repository next to this checkout. Source launch: `python -B launch.py`. Build with `Build.ps1`, using a Python environment containing the engine's pinned build requirements. The build checks the engine commit in `product.json` and copies only four read-only backend modules. There is one maintained implementation of those readers in the engine; this repository owns recording lifecycle, boss signatures, labels, export and UI.

`data/bosses.json` is the only data file shipped with the application. `captures/` retains the shared Okatsu/Jin/Maria source stream and annotations, with hashes in `captures/index.json`. `data/catalogue.json` and `data/encounters/` retain curated historical observations for development; they are excluded from the package. Raw captures keep their original bytes. Historical paths inside raw events are provenance, not current runtime dependencies.

The two existing integration test entrypoints remain in Tanto Engine and cover recording, export and package boundaries alongside the Sword integration. Packaged startup is checked without game access. Live recording across death, reload and different contributor machines still requires gameplay validation.

Contributor intake is offline: `python -B launch.py --intake "submission.zip" --intake-dir "review-folder"`. It checks bundle paths, sizes, hashes and annotation bounds before staging evidence. Raw takes are stored once per SHA-256; repeated submissions return the same review report. Overlapping conflicting labels and conflicting boss attribution are flagged in `submissions\<bundle-sha256>.json`. Every report stays `pending`; intake never edits curated definitions. Review raw evidence, gaps and label conflicts before making a separate curated change.

Current identification remains limited to configured Okatsu, Jin and Maria fingerprints. Older Maria data still lacks reliable attribution. No new boss identity or live pause/death/reload behavior is certified by offline tests. The next gameplay check is a continuous Jin session, explicitly deferred until the user resumes live verification. No new EXE build or release accompanies these source changes.
