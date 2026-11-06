"""Money helpers. All amounts inside the engine are integer paise."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISE_PER_RUPEE = 100


def to_paise(value: str | int | float | Decimal) -> int:
    """Convert a rupee amount (e.g. "123.45" or 123.45) to integer paise."""
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError(f"not a money amount: {value!r}") from exc
    return int((d * PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / PAISE_PER_RUPEE).quantize(Decimal("0.01"))


def format_inr(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{abs(to_rupees(paise)):,.2f}"
