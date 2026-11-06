"""Build fake OCR output from a monospace drawing of a bill, so parser tests need no OCR engine."""

import math
import random
import re

from tabby.scan.layout import Fragment


def fragments_from_ascii(
    text: str,
    *,
    char_w: float = 12,
    line_h: float = 30,
    skew_deg: float = 0.0,
    jitter: float = 0.0,
    conf: float = 0.97,
    low_conf: dict[str, float] | None = None,
    seed: int = 0,
) -> list[Fragment]:
    """Each run of text separated by 2+ spaces becomes one box. A line starting with '#' is printed 1.8x tall."""
    rng = random.Random(seed)
    angle = math.radians(skew_deg)
    c, s = math.cos(angle), math.sin(angle)
    frags = []
    for row, raw in enumerate(text.strip("\n").splitlines()):
        scale = 1.0
        if raw.startswith("#"):
            raw, scale = " " + raw[1:], 1.8
        for m in re.finditer(r"\S+(?: \S+)*", raw):
            x0, x1 = m.start() * char_w, m.end() * char_w
            y0 = row * line_h
            y1 = y0 + 0.7 * line_h * scale
            dy = rng.uniform(-jitter, jitter)
            quad = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            rotated = [(x * c - (y + dy) * s, x * s + (y + dy) * c) for x, y in quad]
            score = (low_conf or {}).get(m.group(), conf)
            frags.append(Fragment.from_box(rotated, m.group(), score))
    return frags
