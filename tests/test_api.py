import asyncio
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tabby.config import Settings, get_settings
from tabby.main import create_app
from tabby.ratelimit import RateLimiter
from tabby.share.store import ShareStore
from tests.ocr_fixtures import fragments_from_ascii

RECEIPT = """
#      PARADISE
  Item              Qty    Rate   Amount
  Chicken Biryani     1  350.00   350.00
  KF Beer             1  250.00   250.00
  Sub Total                       600.00
  CGST 2.5%                         8.75
  SGST 2.5%                         8.75
  VAT 10%                          25.00
  Grand Total                     642.50
"""

BILL = {
    "title": "Paradise",
    "people": [{"id": "a", "name": "Asha"}, {"id": "b", "name": "Ben"}],
    "items": [
        {"id": "1", "name": "Biryani", "amount": 35000},
        {"id": "2", "name": "Beer", "amount": 25000, "category": "liquor"},
    ],
    "charges": [{"id": "g", "name": "GST 5%", "amount": 1750, "scope": "food"}],
    "assignments": {"1": {"a": 1, "b": 1}, "2": {"b": 1}},
    "payer_id": "a",
}


class FakeOcr:
    def __init__(self, text=RECEIPT, delay=0.0, low_conf=None):
        self.text, self.delay, self.low_conf = text, delay, low_conf

    def read(self, img):
        time.sleep(self.delay)
        return fragments_from_ascii(self.text, low_conf=self.low_conf)


@pytest.fixture
def app():
    app = create_app()
    app.state.ocr = FakeOcr()
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def test_pages_render(client):
    home = client.get("/").text
    assert "tabby(" in home
    assert "Scan the bill" in home
    assert "sharedView(" in client.get("/s/ABC234").text
    assert client.get("/sw.js").headers["content-type"].startswith("text/javascript")


def test_split(client):
    r = client.post("/api/split", json=BILL)
    assert r.status_code == 200
    data = r.json()
    assert {p["person_id"]: p["total"] for p in data["people"]} == {"a": 17500 + 875, "b": 17500 + 875 + 25000}
    assert data["unclaimed"] == 0


def test_split_rejects_unknown_person(client):
    bad = {**BILL, "assignments": {"1": {"zz": 1}}}
    assert client.post("/api/split", json=bad).status_code == 422


def test_share_round_trip(client):
    code = client.post("/api/share", json=BILL).json()["code"]
    assert len(code) == 6
    r = client.get(f"/api/share/{code.lower()}")
    assert r.status_code == 200
    assert r.json()["bill"]["title"] == "Paradise"
    assert client.get("/api/share/ZZZZZZ").status_code == 404


async def test_share_expires(tmp_path):
    store = ShareStore(tmp_path / "s.db", ttl_seconds=1)
    await store.init()
    code = await store.put("{}")
    assert await store.get(code) == "{}"
    time.sleep(1.1)
    assert await store.get(code) is None
    assert await store.purge_expired() == 1


def test_qr(client):
    r = client.post("/api/qr", json={"vpa": "asha@okaxis", "name": "Asha", "amount": 12345, "note": "Dinner"})
    assert r.status_code == 200
    data = r.json()
    assert data["link"] == "upi://pay?pa=asha%40okaxis&pn=Asha&am=123.45&cu=INR&tn=Dinner"
    assert data["svg"].startswith("<svg")
    assert client.post("/api/qr", json={"vpa": "nope", "name": "A", "amount": 1}).status_code == 422


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _upload(client):
    return client.post("/api/scan", files={"image": ("bill.jpg", _jpeg(), "image/jpeg")})


def test_scan_reads_bill_locally(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["bill"]["title"] == "PARADISE"
    assert [i["name"] for i in data["bill"]["items"]] == ["Chicken Biryani", "KF Beer"]
    assert data["bill"]["items"][1]["category"] == "liquor"
    names = {c["name"]: c for c in data["bill"]["charges"]}
    assert names["GST 5%"]["amount"] == 1750
    assert names["VAT 10%"]["scope"] == "liquor"
    assert data["mismatch"] == 0
    assert data["flags"] == {}


def test_scan_flags_hard_to_read_rows(app, client):
    app.state.ocr = FakeOcr(low_conf={"KF Beer": 0.4})
    assert _upload(client).json()["flags"] == {"i2": "Hard to read"}


def test_scan_bad_image(client):
    r = client.post("/api/scan", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 422


def test_scan_no_items(app, client):
    app.state.ocr = FakeOcr(text="#  BLURRY\n  nothing useful here\n")
    r = _upload(client)
    assert r.status_code == 422
    assert "items" in r.json()["detail"]


def test_scan_timeout(app, client):
    app.state.ocr = FakeOcr(delay=0.5)
    app.dependency_overrides[get_settings] = lambda: Settings(ocr_timeout_s=0.1)
    assert _upload(client).status_code == 504


def test_scan_busy(app, client):
    app.state.scan_slots = asyncio.Semaphore(0)
    app.dependency_overrides[get_settings] = lambda: Settings(ocr_queue_wait_s=0.05)
    assert _upload(client).status_code == 503


def test_rate_limiter():
    limiter = RateLimiter(2)
    limiter.check("ip")
    limiter.check("ip")
    with pytest.raises(Exception) as exc:
        limiter.check("ip")
    assert exc.value.status_code == 429
