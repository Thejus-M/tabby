from decimal import Decimal

import pytest

from tabby.scan.keywords import clean_label, is_alcohol, is_header
from tabby.scan.layout import Fragment, deskew, estimate_skew, group_rows
from tabby.scan.normalize import normalize
from tabby.scan.numbers import fix_numeric, parse_amount
from tabby.scan.parse import parse_bill
from tabby.scan.schema import ScanError
from tests.ocr_fixtures import fragments_from_ascii

BIRYANI_HOUSE = """
#          SHAH GHOUSE CAFE
     Tolichowki Road, Hyderabad 500008
  GSTIN: 36ABCDE1234F1Z5   Ph: 9876543210
  Bill No: 1182        Date: 14/10/2026 21:40
  ------------------------------------------
  Item                  Qty    Rate    Amount
  ------------------------------------------
  Chicken Dum Biryani     1  380.00    380.00
  (Family Pack)
  Mutton Haleem           2  180.00    360.00
  Rumali Roti             4   25.00    100.00
  Double Ka Meetha        1   90.00     90.00
  ------------------------------------------
  Sub Total                            930.00
  CGST @ 2.5%                           23.25
  SGST @ 2.5%                           23.25
  Round Off                              0.50
  Grand Total                          977.00
          Thank you, visit again!
"""

PUB = """
#            TOIT BREWPUB
  100 Feet Road, Indiranagar, Bengaluru 560038
  Table: 12   Pax: 4   Steward: Ravi
  Particulars                Rate   Qty      Amt
  KF Pitcher               650.00     1   650.00
  LIIT                     450.00     2   900.00
  Virgin Mojito            180.00     1   180.00
  Ginger Ale               120.00     1   120.00
  Prawn Cocktail           420.00     1   420.00
  Rumali Roti               40.00     3   120.00
  Sub Total                           Rs. 2,390.00
  Service Charge 10%                      239.00
  CGST 2.5%                                21.00
  SGST 2.5%                                21.00
  VAT 20%                                 310.00
  Less: Discount                         (100.00)
  Net Payable                           2,881.00
  Paid by UPI                           2,881.00
"""

CAFE_NO_HEADER = """
#        CHAI POINT
  MG Road Bengaluru
  2 x Cold Coffee              360.00
  Veg Puff                      45.00
  Masala Chai                   45.00
  Items: 3
  Total                        450.00
  CGST @ 2.5 %                  11.25
  SGST @ 2.5 %                  11.25
  Net Amt                      472.50
  Cash                        1000.00
  Change                       527.50
"""

NOISY = """
#        CAFE MOCHA
  Item               Qty    Rate    Amount
  Paneer Tikka         l   32O.OO   320,00
  Kingfisher Ultra
  650ml                2   225.00   450.00
  Garlic Naan          3    60.00     1800
  Sub Total                        950.00
  CG5T 2.5%                         13.75
  SG5T 2.5%                         13.75
  VAT 10%                           45.00
  Grand Total                     1022.50
"""


def _items(bill):
    return [(i.name, i.quantity, i.amount, i.is_alcohol) for i in bill.items]


def test_biryani_house_end_to_end():
    scanned = parse_bill(fragments_from_ascii(BIRYANI_HOUSE))
    assert scanned.restaurant == "SHAH GHOUSE CAFE"
    assert _items(scanned) == [
        ("Chicken Dum Biryani (Family Pack)", 1, 380, False),
        ("Mutton Haleem", 2, 360, False),
        ("Rumali Roti", 4, 100, False),
        ("Double Ka Meetha", 1, 90, False),
    ]
    assert scanned.printed_total == 977
    result = normalize(scanned)
    charges = {c.name: c.amount for c in result.bill.charges}
    assert charges == {"GST 5%": 4650, "Round Off": 50}  # positive round-off keeps its sign
    assert result.mismatch == 0
    assert result.warnings == []
    assert result.flags == {}


def test_pub_rate_before_qty_alcohol_and_discount():
    scanned = parse_bill(fragments_from_ascii(PUB))
    assert scanned.restaurant == "TOIT BREWPUB"
    assert [(n, q, a) for n, q, a, _ in _items(scanned)] == [
        ("KF Pitcher", 1, 650),
        ("LIIT", 2, 900),
        ("Virgin Mojito", 1, 180),
        ("Ginger Ale", 1, 120),
        ("Prawn Cocktail", 1, 420),
        ("Rumali Roti", 3, 120),
    ]
    assert [i.name for i in scanned.items if i.is_alcohol] == ["KF Pitcher", "LIIT"]
    result = normalize(scanned)
    by_name = {c.name: c for c in result.bill.charges}
    assert by_name["Less: Discount"].amount == -10000
    assert by_name["VAT 20%"].scope.value == "liquor"
    assert by_name["GST 5%"].amount == 4200
    assert result.printed_total == 288100
    assert result.mismatch == 0


def test_cafe_without_header_inline_qty_and_provisional_total():
    scanned = parse_bill(fragments_from_ascii(CAFE_NO_HEADER))
    assert _items(scanned) == [
        ("Cold Coffee", 2, 360, False),
        ("Veg Puff", 1, 45, False),
        ("Masala Chai", 1, 45, False),
    ]
    assert scanned.printed_total == 472.5
    assert [c.name for c in scanned.charges] == ["CGST 2.5 %", "SGST 2.5 %"]
    assert normalize(scanned).mismatch == 0


def test_noisy_skewed_bill():
    frags = fragments_from_ascii(NOISY, skew_deg=3, jitter=2, low_conf={"Garlic Naan": 0.55})
    scanned = parse_bill(frags)
    assert _items(scanned) == [
        ("Paneer Tikka", 1, 320, False),
        ("Kingfisher Ultra 650ml", 2, 450, True),
        ("Garlic Naan", 3, 180, False),  # "1800" with qty 3 x 60.00 -> decimal point restored
    ]
    result = normalize(scanned)
    assert result.flags["i3"] == "Decimal point added"
    assert {c.name for c in result.bill.charges} == {"GST 5%", "VAT 10%"}
    assert result.mismatch == 0


def test_low_confidence_item_is_flagged():
    result = normalize(parse_bill(fragments_from_ascii(BIRYANI_HOUSE, low_conf={"Mutton Haleem": 0.5})))
    assert result.flags == {"i2": "Hard to read"}


def test_subtotal_mismatch_warns():
    text = BIRYANI_HOUSE.replace("930.00", "990.00")
    scanned = parse_bill(fragments_from_ascii(text))
    assert any("subtotal" in w for w in scanned.warnings)


def test_no_items_raises():
    with pytest.raises(ScanError):
        parse_bill(fragments_from_ascii("#  HELLO\n  just some words\n"))
    with pytest.raises(ScanError):
        parse_bill([])


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("1,234.00", Decimal("1234.00")),
        ("1,23,456.50", Decimal("123456.50")),
        ("120,00", Decimal("120.00")),
        ("1.234,50", Decimal("1234.50")),
        ("₹120", Decimal("120")),
        ("Rs.99", Decimal("99")),
        ("(50.00)", Decimal("-50.00")),
        ("-0.25", Decimal("-0.25")),
        ("32O.OO", Decimal("320.00")),
        ("2.5%", None),
        ("14/10/2026", None),
        ("9876543210", None),
        ("Soda", None),
        ("1.", None),
    ],
)
def test_parse_amount(raw, value):
    assert parse_amount(raw) == value


def test_fix_numeric_leaves_words():
    assert fix_numeric("l2O") == "120"
    assert fix_numeric("Soda") == "Soda"
    assert fix_numeric("Bill") == "Bill"


@pytest.mark.parametrize(
    ("name", "drink"),
    [
        ("Kingfisher Premium", True),
        ("KF Pitcher", True),
        ("LIIT", True),
        ("Old Monk 60ml", True),
        ("Ginger Ale", False),
        ("Rumali Roti", False),
        ("Virgin Mojito", False),
        ("Prawn Cocktail", False),
        ("Water 500ml", False),
        ("Gin and Tonic", True),
        ("Ginger Chicken", False),
    ],
)
def test_is_alcohol(name, drink):
    assert is_alcohol(name) is drink


def test_clean_label_and_header():
    assert clean_label("C.G.5.T 2.5%") == "CGST 2.5%"
    assert clean_label("CG5T") == "CGST"
    assert is_header("ltem Qty Rate Amount")
    assert not is_header("Chicken Biryani 1 420.00")


def test_layout_skew_and_rows():
    text = "Chicken Biryani        420.00\nButter Naan            120.00\nDal Fry  90.00"
    frags = fragments_from_ascii(text, skew_deg=4)
    assert estimate_skew(frags) == pytest.approx(0.0698, abs=0.003)

    rows = group_rows(deskew(frags, estimate_skew(frags)))
    assert [r.text for r in rows] == ["Chicken Biryani 420.00", "Butter Naan 120.00", "Dal Fry 90.00"]


def test_fragment_from_rectangle():
    f = Fragment.from_box([10, 20, 110, 40], "x", 0.9)
    assert (f.x0, f.x1, f.cy, f.h, f.angle) == (10, 110, 30, 20, 0.0)
