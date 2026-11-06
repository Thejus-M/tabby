"""Prepare an uploaded photo for OCR."""

import io

from PIL import Image, ImageOps

from tabby.scan.schema import ScanError

MAX_SIDE = 3000
MIN_WIDTH = 1000


def prepare_image(data: bytes) -> Image.Image:
    """Decode, fix rotation, drop EXIF, scale so small thermal print stays readable, stretch contrast.

    No binarisation: PP-OCR is trained on natural images and reads worse on thresholded ones.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:
        raise ScanError("Could not read that image.") from exc
    if img.width < MIN_WIDTH:
        scale = min(2.0, MIN_WIDTH / img.width)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(img, cutoff=1)
