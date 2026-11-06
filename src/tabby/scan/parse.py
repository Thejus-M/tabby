"""Rule-based bill parser: positioned OCR fragments -> ScannedBill. Pure, no I/O."""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from tabby.engine.gst import _ROUND, classify
from tabby.models import ChargeKind
from tabby.scan import keywords as kw
from tabby.scan.layout import Fragment, Row, Token, deskew, estimate_skew, group_rows
from tabby.scan.numbers import has_decimals, parse_amount
from tabby.scan.schema import ScanError, ScannedBill, ScannedCharge, ScannedItem

MAX_QTY = 50
_LETTERS = re.compile(r"[A-Za-z]")
_MODIFIER = re.compile(r"^\s*([-+*>]|add\b|extra\b|with\b|\()", re.I)
_QTY_MARK = re.compile(r"^[x×*]$", re.I)
_LONE_ONE = {"l", "I", "|", "i"}


@dataclass
class Num:
    value: Decimal
    token: Token
    decimals: bool


@dataclass
class Line:
    """A row split into its words and its numbers."""

    row: Row
    lead: list[Num]  # numbers before the first word (serial no. or quantity)
    name_tokens: list[Token]
    mids: list[Num]  # numbers between the name and the amount
    money: Num | None  # rightmost number in the amount column

    @property
    def name(self) -> str:
        return kw.clean_label(" ".join(t.text for t in self.name_tokens))

    @property
    def text(self) -> str:
        return self.row.text

    @property
    def label(self) -> str:
        """Row text without the amount, for matching charge and total labels."""
        tokens = [t for t in self.row.tokens if not (self.money and t is self.money.token)]
        return kw.clean_label(" ".join(t.text for t in tokens))

    def conf(self) -> float:
        tokens = list(self.name_tokens) + ([self.money.token] if self.money else [])
        return min((t.conf for t in tokens), default=1.0)


@dataclass
class _Item:
    name: str
    quantity: float
    amount: Decimal
    conf: float
    notes: list[str] = field(default_factory=list)


def _read_line(row: Row, left: float, right: float) -> Line:
    width = max(right - left, 1.0)
    nums: list[tuple[int, Num]] = []
    alpha_idx: list[int] = []
    for i, tok in enumerate(row.tokens):
        value = parse_amount(tok.text)
        nxt = row.tokens[i + 1].text if i + 1 < len(row.tokens) else ""
        if value is None and tok.text in _LONE_ONE and alpha_idx and parse_amount(nxt) is not None:
            value = Decimal(1)  # a quantity "1" read as "l" or "I" between the name and the prices
        if value is not None:
            nums.append((i, Num(value, tok, has_decimals(tok.text))))
        elif _LETTERS.search(tok.text):
            alpha_idx.append(i)
    first_alpha = alpha_idx[0] if alpha_idx else len(row.tokens)
    last_alpha = alpha_idx[-1] if alpha_idx else -1
    money = None
    if nums and nums[-1][0] > last_alpha and (nums[-1][1].token.x1 - left) / width >= 0.55:
        money = nums[-1][1]
    lead = [n for i, n in nums if i < first_alpha and n is not money]
    mids = [n for i, n in nums if i > last_alpha and n is not money]
    name_tokens = row.tokens[first_alpha : last_alpha + 1] if alpha_idx else []
    return Line(row, lead, name_tokens, mids, money)


def _is_qty(n: Decimal) -> bool:
    return n == n.to_integral_value() and 0 < n <= MAX_QTY


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal("0.5"), abs(b) / 100)


def _dropped_point(expected: Decimal, amount: Decimal) -> Decimal | None:
    """'18000' or '1800' read for 180.00 / 180.0: return the corrected amount when qty x rate says so."""
    for div in (100, 10):
        if amount >= div and not _close(expected, amount) and _close(expected, amount / div):
            return amount / div
    return None


def _qty_and_amount(line: Line) -> tuple[float, Decimal, list[str]]:
    """Work out quantity from the numbers around the name; fix a dropped decimal point."""
    amount = line.money.value
    notes: list[str] = []
    qty: Decimal = Decimal(1)
    rate: Decimal | None = None
    mids = [n.value for n in line.mids]
    name = line.name_tokens
    if len(mids) >= 2:
        a, b = mids[-2], mids[-1]
        na, nb = line.mids[-2], line.mids[-1]
        # Either column order is possible ("Qty Rate" or "Rate Qty"). When both fit,
        # the quantity is the one printed without decimals, then the smaller one.
        fits = [(q, r, n) for q, r, n in ((a, b, na), (b, a, nb)) if _is_qty(q) and _close(q * r, amount)]
        fits.sort(key=lambda f: (f[2].decimals, f[0]))
        if fits:
            qty, rate = fits[0][0], fits[0][1]
        elif not line.money.decimals and _dropped_point(a * b, amount) and (_is_qty(a) or _is_qty(b)):
            qty, rate = (a, b) if _is_qty(a) else (b, a)
        else:
            qty = a if _is_qty(a) else (b if _is_qty(b) else Decimal(1))
            notes.append("Qty × rate ≠ amount")
    elif len(mids) == 1:
        n = mids[0]
        if _close(n, amount):
            rate = n  # rate column with qty 1
        elif _is_qty(n):
            qty = n
        elif n and _is_qty(amount / n):
            qty, rate = amount / n, n
    elif line.lead and _is_qty(line.lead[-1].value) and (name and _QTY_MARK.match(name[0].text) or not mids):
        qty = line.lead[-1].value  # "2 x Cold Coffee 360.00" or "2 Cold Coffee 360.00"
    if rate is not None and not line.money.decimals and (fixed := _dropped_point(qty * rate, amount)):
        amount = fixed
        notes.append("Decimal point added")
    return float(qty), amount, notes


def _strip_name(name: str) -> str:
    name = re.sub(r"^[x×*]\s+", "", name, flags=re.I)  # left over from "2 x Name"
    name = re.sub(r"^\d{4,8}\s+", "", name)  # HSN code
    return name.strip(" .:-*")


def _is_end_label(label: str) -> bool:
    return bool(
        kw.SUBTOTAL.search(label)
        or kw.GRAND.search(label)
        or kw.TOTAL_ONLY.search(label)
        or kw.COUNT_LINE.search(label)
        or _is_charge_label(label)
    )


def _is_charge_label(label: str) -> bool:
    return classify(label)[0] is not ChargeKind.OTHER or bool(_ROUND.search(label) or kw.EXTRA_CHARGE.search(label))


def _is_meta(text: str) -> bool:
    return bool(kw.META.search(text) or kw.GSTIN.search(text) or kw.DATE_TIME.search(text))


def _find_start(lines: list[Line]) -> int:
    for i, line in enumerate(lines[:-1]):
        if kw.is_header(line.text):
            return i + 1
    for i, line in enumerate(lines):
        if line.money and line.name_tokens and not _is_meta(line.text) and not _is_end_label(line.label):
            return i
    return len(lines)


def _parse_items(lines: list[Line], start: int) -> tuple[list[_Item], int]:
    items: list[_Item] = []
    prefix: list[str] = []
    end = len(lines)
    for i in range(start, len(lines)):
        line = lines[i]
        if kw.SEPARATOR.match(line.text) or not line.row.tokens:
            continue
        if kw.COUNT_LINE.search(line.text):
            end = i
            break
        if _is_end_label(line.label) and (line.money or kw.TOTAL_ONLY.search(line.label)):
            end = i
            break
        if line.money:
            qty, amount, notes = _qty_and_amount(line)
            name = _strip_name(" ".join([*prefix, line.name]).strip())
            prefix = []
            if amount > 0:
                items.append(_Item(name, qty, amount, line.conf(), notes))
            continue
        if not line.name_tokens or _is_meta(line.text):
            continue
        # A row with words and no amount: part of a wrapped name, or a section heading.
        text = line.name
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        next_wants_prefix = bool(
            nxt and nxt.money and (not nxt.name_tokens or not nxt.name[:1].isupper()) and not _is_end_label(nxt.label)
        )
        if next_wants_prefix and not text.startswith("("):
            prefix.append(text)
        elif items and _MODIFIER.match(text):
            items[-1].name += f" {text}" if text.startswith("(") else f" ({text.lstrip('-+*> ')})"
        elif items and not (text.isupper() and not items[-1].name.isupper()):
            items[-1].name += f" {text}"
        # else: a heading such as "STARTERS"; drop it
    return items, end


@dataclass
class _Charges:
    charges: list[ScannedCharge] = field(default_factory=list)
    subtotal: Decimal | None = None
    printed_total: Decimal | None = None
    warnings: list[str] = field(default_factory=list)


def _canonical(label: str) -> str:
    label = re.sub(r"\s*@\s*", " ", label)
    label = re.sub(r"\s+(on|of)\s+[\d.,]+$", "", label, flags=re.I)
    return re.sub(r"\s{2,}", " ", label).strip(" :-")


def _parse_charges(lines: list[Line]) -> _Charges:
    out = _Charges()
    provisional: Decimal | None = None
    for line in lines:
        if not line.money:
            continue
        label, amount = line.label, line.money.value
        conf = line.conf()
        if kw.COUNT_LINE.search(label):
            continue
        if kw.SUBTOTAL.search(label):
            out.subtotal = out.subtotal or abs(amount)
            continue
        if kw.GRAND.search(label):
            out.printed_total = abs(amount)
            break
        if kw.TOTAL_ONLY.search(label):
            provisional = abs(amount)
            continue
        if kw.PAYMENT.search(label) or _is_meta(label):
            continue
        if provisional is not None and not out.charges:
            out.subtotal = out.subtotal or provisional  # "Total" followed by taxes was really a subtotal
            provisional = None
        if _is_charge_label(label):
            value = amount if _ROUND.search(label) else abs(amount)
            out.charges.append(ScannedCharge(name=_canonical(label), amount=float(value), confidence=conf))
        elif _LETTERS.search(label):
            unknown = ScannedCharge(name=_canonical(label), amount=float(abs(amount)), confidence=conf)
            unknown.note = "Unrecognised line"
            out.charges.append(unknown)
    if out.printed_total is None and provisional is not None:
        out.printed_total = provisional
    return out


def _find_restaurant(lines: list[Line]) -> str | None:
    best: tuple[float, int, str] | None = None
    for idx, line in enumerate(lines[:8]):
        text = line.text.strip()
        letters = sum(ch.isalpha() for ch in text)
        digits = sum(ch.isdigit() for ch in text)
        if letters < 3 or digits > 0.3 * len(text) or kw.ADDRESS.search(text) or _is_meta(text) or kw.is_header(text):
            continue
        if kw.SEPARATOR.match(text):
            continue
        score = (line.row.h, -idx)
        if best is None or score > best[:2]:
            best = (*score, text)
    return kw.clean_label(best[2]) if best else None


def parse_bill(frags: list[Fragment]) -> ScannedBill:
    if not frags:
        raise ScanError("No text found. Try a sharper, well-lit photo.")
    frags = deskew(frags, estimate_skew(frags))
    rows = group_rows(frags)
    left = min(f.x0 for f in frags)
    right = max(f.x1 for f in frags)
    lines = [_read_line(r, left, right) for r in rows]

    start = _find_start(lines)
    items, end = _parse_items(lines, start)
    if not items:
        raise ScanError("Couldn't find any items on that bill. Try a straighter photo, or type them in.")
    found = _parse_charges(lines[end:])
    warnings = list(found.warnings)

    # Lines inside the item table that are really charges (bills without a subtotal row).
    for item in list(items):
        if _is_charge_label(item.name) and not kw.is_alcohol(item.name):
            items.remove(item)
            found.charges.insert(0, ScannedCharge(name=_canonical(item.name), amount=float(item.amount)))

    items_sum = sum((i.amount for i in items), Decimal(0))
    if found.subtotal is not None and abs(items_sum - found.subtotal) > Decimal("0.05"):
        warnings.append(f"Items add up to ₹{items_sum:.2f} but the bill's subtotal says ₹{found.subtotal:.2f}.")
    if found.printed_total is None:
        warnings.append("Couldn't find the grand total on the bill.")

    scanned_items = [
        ScannedItem(
            name=i.name,
            quantity=i.quantity,
            amount=float(i.amount),
            is_alcohol=kw.is_alcohol(i.name),
            confidence=i.conf,
            note=i.notes[0] if i.notes else None,
        )
        for i in items
    ]
    has_vat = any(re.search(r"\bvat\b", c.name, re.I) for c in found.charges)
    if has_vat and not any(i.is_alcohol for i in scanned_items):
        warnings.append("The bill has VAT but no drinks were recognised. Mark the drinks with 🍺.")
    return ScannedBill(
        restaurant=_find_restaurant(lines[:start]) if start else None,
        items=scanned_items,
        charges=found.charges,
        printed_total=float(found.printed_total) if found.printed_total is not None else None,
        warnings=warnings[:8],
    )
