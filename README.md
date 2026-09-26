# Tanto Recorder

A standalone, read-only Windows application for collecting Nioh boss move data. Contributors receive `TantoRecorder.exe`; they do not install Tanto Engine, Python or developer tools. The application does not modify the game, inject a runtime, control the character or capture the screen.

Choose a boss and press **Record**. Wait for **Ready to fight** before beginning. Recording continues through moves and reacquires the boss after reloads. Pause Nioh yourself after a meaningful sequence, choose **Describe last move**, and enter an ordinary description. Mention any intervening attack or uncertainty. Press **Stop**, wait for **Stopped**, then **Export**.

Export writes one ZIP to Downloads and opens its folder. It contains raw JSONL takes, labels, a hash manifest and `Descriptions.csv`, readable in Excel. Sharing is manual. Human labels are associated with sampled time; they are not exact animation boundaries. Repeated action sequences are candidates for review, not automatically verified combos.

## Development

Clone the private `neuriv/tanto-engine` repository next to this checkout. Source launch: `python -B launch.py`. Build with `Build.ps1`, using a Python environment containing the engine's pinned build requirements. The build checks the engine commit in `product.json` and copies only four read-only backend modules. There is one maintained implementation of those readers in the engine; this repository owns recording lifecycle, boss signatures, labels, export and UI.

`data/bosses.json` is the only data file shipped with the application. `captures/` retains the shared Okatsu/Jin/Maria source stream and annotations, with hashes in `captures/index.json`. `data/catalogue.json` and `data/encounters/` retain curated historical observations for development; they are excluded from the package. Raw captures keep their original bytes. Historical paths inside raw events are provenance, not current runtime dependencies.

The two existing integration test entrypoints remain in Tanto Engine and cover recording, export and package boundaries alongside the Sword integration. Packaged startup is checked without game access. Live recording across death, reload and different contributor machines still requires gameplay validation.
