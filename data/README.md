# Recorder data

`bosses.json` supplies encounter names and optional action/animation fingerprints. A chosen name is the player's label; only a validated fingerprint can attribute an actor. Unknown names must remain recordable. Action IDs from William and unidentified actors are useful evidence too.

`catalogue.json` and `encounters/` support historical offline research. The catalogue helps `summarize.py` recognize previously reviewed sword actions; it does not decide which IDs the recorder should collect. Reconstruction files are derived reports, not substitutes for original recordings or proof that a move is playable.

Keep original action observations and descriptions together. Start review at the last few executions before Stop or the description's sampled-time anchor, then work backward until the ordered IDs match the described movement. Collapse repeated polling of one execution, retain genuine repeated attacks, and inspect all actor roles. Idle/recovery actions at the end and observation gaps prevent blindly choosing the final number.

Use full action IDs with animation, timing, actor/source context and game build. Memory addresses can be reused, and different actors can share numeric IDs. `low`, `mid` and `high` in descriptions are review priorities unless the author explicitly means a stance; neither meaning establishes move correctness.

Legacy sessions store raw takes in `take-*/events.jsonl` and saved descriptions in `labels.jsonl`. Draft text is a separate unfinished note; legacy exports omit it. A session folder or a stopped status alone does not prove that any action IDs were captured. Intake checks file hashes and marks evidence pending review; it never changes MWM definitions automatically.

Version 2 session archives retain every selected folder in one ordinary ZIP, including legacy drafts and sessions without action evidence. Intake streams and verifies each file, then publishes it under `submissions/<archive SHA-256>/` with the original manifest and a review report. It counts all `action_state` rows, keeps malformed-line warnings and flags sessions without raw action rows; imported descriptions still require matching against the recording's ending.
