# Recorder assets

`background.png` is an imagegen edit of the user-supplied `recorder background.png` (William and guardian spirit), not claimed as original artwork. The built-in tool returned **1672 × 941**; the user chose to keep that resolution after a 4K retry returned the same size. The app blends this dim image at 65% against ink black; glass panels sample, blur and tint that same wallpaper. Labels sample the composed panel surface.

Final asset prompt (built-in imagegen; first edit selected):

> Edit the supplied image for the Tanto Recorder application wallpaper. Preserve the exact scene composition, William kneeling with sword, guardian spirit, rain and background. Output a 4K 3840 x 2160 landscape PNG. Apply fine ordered dithering with subtle ASCII marks and tiny Japanese glyph texture, integrated into shading, not large readable text. Dim the entire image substantially to about 30 percent of original brightness so cream application text can remain readable directly over it. Retain blue-black, muted crimson colors and recognizable scene. No panels, rectangles, labels, UI, logos, extra characters or added objects. The image is a wallpaper, not a screenshot.

`start.wav` and `stop.wav` are generated PCM tones: mono, 44.1 kHz, signed 16-bit, 200 ms, with tapered edges. Start rises 660 to 990 Hz; stop falls 660 to 440 Hz. No external sound assets are used.


`fonts/Inter-Regular.ttf` and `Inter-SemiBold.ttf` come from [Inter 4.1](https://github.com/rsms/inter/releases/tag/v4.1). Their SIL Open Font License accompanies them as `fonts/LICENSE.txt`. Fonts load privately with AddFontResourceExW; they are not installed system-wide.

Glass design reference: [PyGlass](https://github.com/neomosh8/pyglass), especially `pyglass/refract.py` and its explanation of clear interiors, refracting rims, frosting and contrast tints. Recorder uses an independently implemented static Pillow approximation. It does not bundle Qt, NumPy, PyGlass code or any screen-capture path. Bevels and tint support readability; this is not a physically exact refraction renderer.
