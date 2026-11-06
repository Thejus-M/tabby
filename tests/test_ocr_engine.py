"""Smoke test with the real RapidOCR models on a rendered receipt. Run alone with: pytest -m ocr"""

import io

import pytest
from PIL import Image, ImageDraw, ImageFont

from tabby.scan.image import prepare_image
from tabby.scan.normalize import normalize
from tabby.scan.parse import parse_bill

pytestmark = pytest.mark.ocr

LINES = [
    "      UDUPI GARDEN",
    "  GSTIN: 29ABCDE1234F1Z5",
    "Item            Qty   Rate   Amount",
    "Masala Dosa       2  90.00   180.00",
    "Filter Coffee     3  40.00   120.00",
    "Sub Total                    300.00",
    "CGST 2.5%                      7.50",
    "SGST 2.5%                      7.50",
    "Grand Total                  315.00",
]


@pytest.fixture(scope="module")
def engine():
    pytest.importorskip("rapidocr")
    from tabby.scan.ocr import load_engine

    return load_engine()


def _receipt_jpeg() -> bytes:
    font = ImageFont.load_default(size=24)
    img = Image.new("RGB", (560, 30 + 36 * len(LINES)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        # Draw column by column so spacing survives a proportional font.
        x = 20
        for j, chunk in enumerate(line.split("  ")):
            if chunk:
                draw.text((x, 15 + 36 * i), chunk.strip(), fill="black", font=font)
            x += 14 * (len(chunk) + 2) if j else 14 * (len(chunk) + 2)
    buf = io.BytesIO()
    img.rotate(1.5, expand=True, fillcolor="white").save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def test_real_engine_reads_rendered_receipt(engine):
    result = normalize(parse_bill(engine.read(prepare_image(_receipt_jpeg()))))
    assert [(i.name, i.quantity, i.amount) for i in result.bill.items] == [
        ("Masala Dosa", 2, 18000),
        ("Filter Coffee", 3, 12000),
    ]
    assert result.printed_total == 31500
    assert result.mismatch == 0
