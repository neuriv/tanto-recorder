# Recorder assets

`background.png` is the accepted 1672 × 941 dimmed, dithered edit of the user-supplied William/guardian-spirit artwork. Solid dark panels keep text readable. The wallpaper bytes remain unchanged; no glass or blur is applied.

`start.wav` comes from `t2wxkfk.wav` (5.110 seconds); `stop.wav` comes from `6s3fj0w.wav` (6.041 seconds). Both retain the supplied stereo, 48 kHz, signed 32-bit PCM bytes. The build manifest records their hashes.

Volume scales temporary PCM copies without changing sample rate, channels or duration. Zero skips playback; other levels play asynchronously. Temporary copies are removed when volume changes or Recorder closes.

The bundled [Source Serif 4.005](https://github.com/adobe-fonts/source-serif/releases/tag/4.005R) Small Text regular and semibold TTFs load privately. Their SIL Open Font License is included in `fonts/LICENSE.txt`; no installation or separate font download is needed. Inter and the glass renderer have been removed.
