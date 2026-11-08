# Agentnik branding

The robot icon preserves the supplied artwork and colors. `assets/robot.svg` contains only robot geometry. The wordmark uses lowercase **agentnik**, with dark lettering for light backgrounds, light lettering for dark backgrounds, and warm red `#d63b4b` for **nik**. Interface accents use red `#c83545`.

All SVGs contain vector paths, with no embedded bitmaps or runtime font dependency. Matching transparent PNGs and a multi-resolution Windows ICO are included in the package.

Rebuild with `python tools/build_branding.py` using PySide6 and Pillow. The builder uses Segoe UI Black on Windows; another platform may substitute a font. Commit the generated assets to preserve the approved appearance across platforms. Pillow is optional for asset builds only.
