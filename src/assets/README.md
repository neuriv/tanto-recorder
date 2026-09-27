# Recorder assets

`background.png` is the accepted 1672 × 941 dimmed, dithered edit of the user-supplied William/guardian-spirit artwork. Bright text and subtle shadows provide contrast without section backgrounds. The wallpaper bytes remain unchanged; no glass or blur is applied.

`start.wav` comes from `t2wxkfk.wav` (5.110 seconds); `stop.wav` comes from `6s3fj0w.wav` (6.041 seconds). Both retain the supplied stereo, 48 kHz, signed 32-bit PCM bytes. The build manifest records their hashes.

Electron plays the original WAVs with application-local gain, default 40%. Zero skips playback; Stop replaces unfinished Start audio. No scaled temporary WAVs are needed.

The interface uses Windows' Segoe UI Variable/Segoe UI fonts. Historical [Source Serif 4.005](https://github.com/adobe-fonts/source-serif/releases/tag/4.005R) files and their SIL license remain here for older releases; the Electron package excludes them.
