"""UPI deep links and QR codes."""

import re
from urllib.parse import quote, urlencode

import segno

from tabby.engine.money import to_rupees

VPA = re.compile(r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z][a-zA-Z0-9.\-]{1,64}$")


def is_valid_vpa(vpa: str) -> bool:
    return bool(VPA.fullmatch(vpa.strip()))


def upi_link(*, vpa: str, payee_name: str, amount_paise: int, note: str = "") -> str:
    if not is_valid_vpa(vpa):
        raise ValueError("invalid UPI ID")
    params = {"pa": vpa.strip(), "pn": payee_name.strip()[:50], "am": f"{to_rupees(amount_paise)}", "cu": "INR"}
    if note:
        params["tn"] = note.strip()[:80]
    return "upi://pay?" + urlencode(params, quote_via=quote)


def qr_svg(data: str) -> str:
    return segno.make(data, error="m").svg_inline(scale=8, border=2, dark="#111", light="#fff")
