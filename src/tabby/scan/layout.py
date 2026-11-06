"""Geometry: OCR fragments -> deskewed rows of positioned tokens."""

import math
import re
from dataclasses import dataclass, field, replace
from statistics import median


@dataclass(frozen=True, slots=True)
class Fragment:
    """One OCR text box. Centre, size and the angle of its top edge (radians)."""

    text: str
    cx: float
    cy: float
    w: float
    h: float
    conf: float = 1.0
    angle: float = 0.0

    @property
    def x0(self) -> float:
        return self.cx - self.w / 2

    @property
    def x1(self) -> float:
        return self.cx + self.w / 2

    @classmethod
    def from_box(cls, box, text: str, conf: float = 1.0) -> "Fragment":
        """Accept a quad [[x, y] * 4] (TL, TR, BR, BL) or an [x0, y0, x1, y1] rectangle."""
        if len(box) == 4 and not isinstance(box[0], int | float):
            (x0, y0), (x1, y1), (x2, y2), (x3, y3) = ((float(x), float(y)) for x, y in box)
            w = math.hypot(x1 - x0, y1 - y0)
            h = math.hypot(x3 - x0, y3 - y0)
            cx, cy = (x0 + x1 + x2 + x3) / 4, (y0 + y1 + y2 + y3) / 4
            return cls(text, cx, cy, w, h, conf, math.atan2(y1 - y0, x1 - x0))
        x0, y0, x1, y1 = (float(v) for v in box)
        return cls(text, (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, conf)


@dataclass(slots=True)
class Token:
    text: str
    x0: float
    x1: float
    conf: float


@dataclass(slots=True)
class Row:
    frags: list[Fragment]
    cy: float
    h: float
    tokens: list[Token] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

    @property
    def x0(self) -> float:
        return min(f.x0 for f in self.frags)

    @property
    def x1(self) -> float:
        return max(f.x1 for f in self.frags)


def estimate_skew(frags: list[Fragment]) -> float:
    """Median angle of wide boxes; 0 when there is too little evidence or the tilt is negligible."""
    angles = [f.angle for f in frags if f.w > 3 * f.h]
    if len(angles) < 3:
        return 0.0
    angle = median(angles)
    return 0.0 if abs(angle) < math.radians(0.3) else angle


def deskew(frags: list[Fragment], angle: float) -> list[Fragment]:
    """Rotate box centres by -angle so printed rows become horizontal."""
    if not angle:
        return frags
    c, s = math.cos(-angle), math.sin(-angle)
    return [replace(f, cx=f.cx * c - f.cy * s, cy=f.cx * s + f.cy * c, angle=f.angle - angle) for f in frags]


def group_rows(frags: list[Fragment], tol: float = 0.5) -> list[Row]:
    """Cluster fragments whose vertical centres are within tol * median height."""
    if not frags:
        return []
    line_h = median(f.h for f in frags)
    rows: list[Row] = []
    for f in sorted(frags, key=lambda f: f.cy):
        best = None
        for row in rows[-4:]:  # only recent rows can still be open
            d = abs(f.cy - row.cy)
            fits = not any(f.x0 < g.x1 - 2 and g.x0 < f.x1 - 2 for g in row.frags)
            if d < tol * line_h and fits and (best is None or d < abs(f.cy - best.cy)):
                best = row
        if best is None:
            rows.append(Row([f], f.cy, f.h))
        else:
            best.frags.append(f)
            best.cy = sum(g.cy for g in best.frags) / len(best.frags)
            best.h = max(g.h for g in best.frags)
    rows.sort(key=lambda r: r.cy)
    for row in rows:
        row.frags.sort(key=lambda f: f.x0)
        row.tokens = _tokens(row.frags)
    return rows


_SPLIT_NUM_LEFT = re.compile(r"\d[.,]$|\d[.,]\d$")
_SPLIT_NUM_RIGHT = re.compile(r"^[.,]?\d")
_CURRENCY = re.compile(r"^(₹|rs\.?|inr)$", re.I)


def _tokens(frags: list[Fragment]) -> list[Token]:
    """Split fragments on spaces (x positions interpolated by character), then re-join split numbers."""
    tokens: list[Token] = []
    for f in frags:
        text = f.text.strip()
        if not text:
            continue
        per_char = f.w / max(len(text), 1)
        for m in re.finditer(r"\S+", text):
            tokens.append(Token(m.group(), f.x0 + m.start() * per_char, f.x0 + m.end() * per_char, f.conf))
    merged: list[Token] = []
    for t in tokens:
        prev = merged[-1] if merged else None
        if prev and (
            _CURRENCY.match(prev.text)  # "Rs." + "120"
            or (_SPLIT_NUM_LEFT.search(prev.text) and _SPLIT_NUM_RIGHT.match(t.text))  # "1,2" + "50.00"
            or (re.fullmatch(r"\d+", prev.text) and re.fullmatch(r"[.,]\d{1,2}", t.text))  # "120" + ".00"
        ):
            merged[-1] = Token(prev.text + t.text, prev.x0, t.x1, min(prev.conf, t.conf))
        else:
            merged.append(t)
    return merged
