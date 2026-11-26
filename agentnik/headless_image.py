"""Pillow raster codec for machines without Qt."""

from io import BytesIO


def decode(data, max_pixels):
    from PIL import Image

    try:
        with Image.open(BytesIO(data), formats=("PNG", "JPEG", "WEBP")) as image:
            if image.width * image.height > max_pixels:
                raise ValueError("Image dimensions exceed the supported limit")
            image.load()
            return image.format.lower(), image.copy()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("Only valid PNG, JPEG, and WebP images are supported") from exc


def encode(data, target, max_pixels):
    _, image = decode(data, max_pixels)
    if target == "JPEG":
        if "A" in image.getbands() or "transparency" in image.info:
            raise ValueError("Use a PNG or WebP destination to preserve transparency")
        image = image.convert("RGB")
    buffer = BytesIO()
    try:
        image.save(buffer, target)
    except OSError as exc:
        raise ValueError("Cannot encode the generated image in the requested format") from exc
    return buffer.getvalue()
