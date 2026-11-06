"""Reading money, quantities and rates out of OCR tokens."""

import re
from decimal import Decimal, InvalidOperation

# Letters OCR commonly returns in place of digits. Applied only to tokens that are already mostly numeric.
_CONFUSABLE = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8"})
_CURRENCY_PREFIX = re.compile(r"^(?:₹|rs\.?|inr)\s*", re.I)
_NUMERIC_BODY = re.compile(r"^\d[\d,.]*$")
_PERCENT = re.compile(r"@?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%")


def fix_numeric(tok: str) -> str:
    """'32O.OO' -> '320.00', but leave words like 'Soda' or 'Bill' alone."""
    if not re.search(r"\d", tok):
        return tok
    fixed = tok.translate(_CONFUSABLE)
    return fixed if re.fullmatch(r"[\d,.\-()₹]+", fixed) else tok


def parse_amount(token: str) -> Decimal | None:
    """Parse '1,23,456.50', '120,00', '1.234,50', '₹120', 'Rs.99', '(50.00)', '-0.25'. None if not money."""
    t = token.strip().rstrip("/-=:")
    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative, t = True, t[1:-1]
    if t.startswith("-"):
        negative, t = True, t[1:]
    t = _CURRENCY_PREFIX.sub("", t)
    t = fix_numeric(t)
    if not _NUMERIC_BODY.fullmatch(t):
        return None
    seps = [i for i, ch in enumerate(t) if ch in ",."]
    if seps:
        last = seps[-1]
        decimals = len(t) - last - 1
        if 1 <= decimals <= 2:
            t = t[:last].replace(",", "").replace(".", "") + "." + t[last + 1 :]
        elif decimals == 3:
            t = t.replace(",", "").replace(".", "")
        else:
            return None
    elif len(t) > 6:
        return None  # long digit runs are phone numbers, bill numbers, GSTIN fragments
    try:
        value = Decimal(t)
    except InvalidOperation:
        return None
    return -value if negative else value


def has_decimals(token: str) -> bool:
    return bool(re.search(r"[.,]\d{1,2}\)?$", token.strip()))


def percent_in(text: str) -> Decimal | None:
    m = _PERCENT.search(text)
    return Decimal(m.group(1).replace(",", ".")) if m else None


def is_percent(token: str) -> bool:
    return token.strip().endswith("%")
