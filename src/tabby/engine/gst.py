"""Turn raw charge lines from an Indian restaurant bill into typed, scoped charges."""

import re
from dataclasses import dataclass
from decimal import Decimal

from tabby.models import Charge, ChargeKind, Scope

_DISCOUNT = re.compile(r"\b(disc(ount)?|off|coupon|promo|less)\b", re.I)
_SERVICE = re.compile(r"\bservice\b|\bs\.?\s?c(harge)?\b", re.I)
_SPLIT_GST = re.compile(r"\b(c|s|ut)gst\b", re.I)
_GST = re.compile(r"\b(i?gst|cess)\b", re.I)
_VAT = re.compile(r"\bvat\b", re.I)
_ROUND = re.compile(r"\bround(ing|ed)?\s*(off)?\b", re.I)
_RATE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


@dataclass
class RawCharge:
    name: str
    amount: int  # paise, as printed (discounts may be printed positive)


def _rate(name: str) -> Decimal | None:
    m = _RATE.search(name)
    return Decimal(m.group(1)) if m else None


def classify(name: str) -> tuple[ChargeKind, Scope]:
    # Round off first: its "off" would otherwise match the discount pattern and flip the sign.
    if _ROUND.search(name):
        return ChargeKind.OTHER, Scope.ALL
    if _DISCOUNT.search(name):
        return ChargeKind.DISCOUNT, Scope.ALL
    if _SERVICE.search(name):
        return ChargeKind.SERVICE, Scope.ALL
    if _VAT.search(name):
        # In India, liquor is outside GST and carries state VAT instead.
        return ChargeKind.TAX, Scope.LIQUOR
    if _SPLIT_GST.search(name) or _GST.search(name):
        return ChargeKind.TAX, Scope.FOOD
    return ChargeKind.OTHER, Scope.ALL


def build_charges(raw: list[RawCharge], *, has_liquor: bool) -> list[Charge]:
    """Classify charges and collapse CGST + SGST/UTGST into one GST line."""
    charges: list[Charge] = []
    gst_amount = 0
    gst_rates: list[Decimal | None] = []

    for rc in raw:
        if rc.amount == 0:
            continue
        kind, scope = classify(rc.name)
        if not has_liquor and scope is Scope.LIQUOR:
            # VAT on a bill with no detected liquor: probably mis-tagged items; spread over all.
            scope = Scope.ALL
        if _SPLIT_GST.search(rc.name):
            gst_amount += rc.amount
            gst_rates.append(_rate(rc.name))
            continue
        amount = -abs(rc.amount) if kind is ChargeKind.DISCOUNT else rc.amount
        charges.append(Charge(id=f"c{len(charges) + 1}", name=rc.name.strip(), kind=kind, amount=amount, scope=scope))

    if gst_amount:
        rates = [r for r in gst_rates if r is not None]
        label = "GST"
        if rates and len(rates) == len(gst_rates):
            label = f"GST {sum(rates).normalize()}%" if len(set(rates)) == 1 else "GST"
        charges.insert(0, Charge(id="gst", name=label, kind=ChargeKind.TAX, amount=gst_amount, scope=Scope.FOOD))

    for i, c in enumerate(charges, start=1):
        if c.id != "gst":
            c.id = f"c{i}"
    return charges
