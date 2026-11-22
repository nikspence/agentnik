# Agentnik branding

The approved transparent light and dark artwork is stored in `assets/agentnik-light-source.png` and `assets/agentnik-dark-source.png`. The packaged logo PNGs copy those sources, and the self-contained SVG wrappers embed the same raster artwork for the desktop interface. The robot icon is extracted from the light artwork and supplied as PNG, SVG, and a multi-resolution Windows ICO. These SVG files are raster-backed rather than vector paths.

Rebuild with `python tools/build_branding.py` using Pillow. The builder detects the transparent gap between the robot and wordmark; if a replacement source changes the layout, verify the resulting icon. Pillow is needed only to rebuild branding, not to run Agentnik.
