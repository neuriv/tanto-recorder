# Recorder assets

`background.png` is the accepted 1672 × 941 dimmed, dithered edit of the user-supplied William/guardian-spirit artwork. Panels blur and tint this image; labels sample the panel surface. The original composition remains unchanged.

`start.wav` comes from `t2wxkfk.wav` (5.110 seconds); `stop.wav` comes from `6s3fj0w.wav` (6.041 seconds). Both retain the supplied stereo, 48 kHz, signed 32-bit PCM bytes. The build manifest records their hashes.

Volume scales temporary PCM copies without changing sample rate, channels or duration. Zero skips playback; other levels play asynchronously. Temporary copies are removed when volume changes or Recorder closes.

The bundled [Inter 4.1](https://github.com/rsms/inter/releases/tag/v4.1) fonts load privately. Their SIL Open Font License is included in `fonts/LICENSE.txt`; no system-wide installation is needed.

[PyGlass](https://github.com/neomosh8/pyglass) informed the beveled, frosted design. Recorder implements its own static Pillow treatment; it bundles no PyGlass code, Qt, NumPy or screen-capture component.
