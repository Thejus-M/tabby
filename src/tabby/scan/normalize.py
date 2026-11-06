"""Turn a ScannedBill into the engine's Bill model (paise, typed charges) plus review hints."""

import re

from pydantic import BaseModel, Field

from tabby.engine.gst import RawCharge, build_charges
from tabby.engine.money import to_paise
from tabby.models import Bill, Category, Item
from tabby.scan.schema import ScannedBill

LOW_CONFIDENCE = 0.8
_SPACES = re.compile(r"\s+")
_TOTAL_WORDS = re.compile(r"\b(sub\s*-?total|grand\s*total|net\s*amount|total)\b", re.I)
_SPLIT_GST = re.compile(r"\b(c|s|ut)gst\b", re.I)


class ScanResult(BaseModel):
    bill: Bill
    printed_total: int | None
    mismatch: int | None  # printed_total - computed total, when both known
    flags: dict[str, str] = Field(default_factory=dict)  # item/charge id -> why it needs a look
    warnings: list[str] = Field(default_factory=list)


def _word_case(word: str) -> str:
    # Short all-caps words are usually brands or abbreviations (KF, LIIT, BBQ): keep them.
    return word if word.isupper() and len(word) <= 4 else word.capitalize()


def _clean(name: str) -> str:
    """Tidy spacing; fix ALL CAPS / all lower names, leave mixed case as printed."""
    name = _SPACES.sub(" ", name).strip(" .-:*")[:120]
    if name.isupper() or name.islower():
        name = " ".join(_word_case(w) for w in name.split(" "))
    return name


def _reason(confidence: float, note: str | None) -> str | None:
    if note:
        return note
    return "Hard to read" if confidence < LOW_CONFIDENCE else None


def normalize(scanned: ScannedBill) -> ScanResult:
    flags: dict[str, str] = {}
    items = []
    for s in scanned.items:
        if s.amount <= 0:
            continue
        item = Item(
            id=f"i{len(items) + 1}",
            name=_clean(s.name),
            quantity=s.quantity if s.quantity > 0 else 1,
            amount=to_paise(s.amount),
            category=Category.LIQUOR if s.is_alcohol else Category.FOOD,
        )
        items.append(item)
        if reason := _reason(s.confidence, s.note):
            flags[item.id] = reason

    kept = [c for c in scanned.charges if not _TOTAL_WORDS.fullmatch(c.name.strip())]
    raw = [RawCharge(name=c.name.strip()[:80] or "Charge", amount=to_paise(c.amount)) for c in kept]
    charges = build_charges(raw, has_liquor=any(i.category is Category.LIQUOR for i in items))
    for c in kept:
        if reason := _reason(c.confidence, c.note):
            # CGST/SGST lines were merged into the single "gst" charge.
            matches = [x.id for x in charges if x.name == c.name.strip()]
            target = "gst" if _SPLIT_GST.search(c.name) else next(iter(matches), None)
            if target:
                flags[target] = reason

    bill = Bill(title=(scanned.restaurant or "").strip()[:120], items=items, charges=charges)
    printed = to_paise(scanned.printed_total) if scanned.printed_total else None
    mismatch = None
    if printed is not None:
        mismatch = printed - (sum(i.amount for i in items) + sum(c.amount for c in charges))
    return ScanResult(bill=bill, printed_total=printed, mismatch=mismatch, flags=flags, warnings=scanned.warnings)
