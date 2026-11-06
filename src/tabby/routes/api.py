from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from tabby.config import Settings, get_settings
from tabby.engine.split import compute_split
from tabby.models import Bill, SplitResult
from tabby.ratelimit import RateLimiter
from tabby.scan.normalize import ScanResult
from tabby.scan.ocr import OcrEngine
from tabby.scan.schema import ScanError
from tabby.scan.service import ScanBusy, ScanTimeout, run_scan
from tabby.share.store import ShareStore
from tabby.upi import is_valid_vpa, qr_svg, upi_link

router = APIRouter(prefix="/api")

_settings = get_settings()
scan_limit = RateLimiter(_settings.scan_rate_limit_per_min)
share_limit = RateLimiter(_settings.share_rate_limit_per_min)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_store(request: Request) -> ShareStore:
    return request.app.state.store


StoreDep = Annotated[ShareStore, Depends(get_store)]


def get_ocr(request: Request) -> OcrEngine:
    return request.app.state.ocr


@router.post("/scan", dependencies=[Depends(scan_limit)])
async def scan(
    request: Request,
    image: Annotated[UploadFile, File()],
    engine: Annotated[OcrEngine, Depends(get_ocr)],
    settings: SettingsDep,
) -> ScanResult:
    data = await image.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "Image too large.")
    if not data:
        raise HTTPException(400, "Empty upload.")
    try:
        return await run_scan(data, engine, request.app.state.scan_slots, settings)
    except ScanError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ScanBusy as exc:
        raise HTTPException(503, "Busy reading another bill. Try again in a moment.") from exc
    except ScanTimeout as exc:
        raise HTTPException(504, "Reading the bill took too long. Try a closer, flatter photo.") from exc


@router.post("/split")
async def split(bill: Bill) -> SplitResult:
    return compute_split(bill)


class ShareCreated(BaseModel):
    code: str
    ttl_days: int


class SharedSplit(BaseModel):
    bill: Bill
    split: SplitResult


@router.post("/share", dependencies=[Depends(share_limit)])
async def create_share(bill: Bill, store: StoreDep, settings: SettingsDep) -> ShareCreated:
    payload = bill.model_dump_json()
    if len(payload) > settings.max_share_bytes:
        raise HTTPException(413, "Bill too large to share.")
    return ShareCreated(code=await store.put(payload), ttl_days=settings.share_ttl_days)


@router.get("/share/{code}")
async def read_share(code: str, store: StoreDep) -> SharedSplit:
    payload = await store.get(code)
    if payload is None:
        raise HTTPException(404, "That split does not exist or has expired.")
    bill = Bill.model_validate_json(payload)
    return SharedSplit(bill=bill, split=compute_split(bill))


class QrRequest(BaseModel):
    vpa: str = Field(max_length=300)
    name: str = Field(max_length=60)
    amount: int = Field(gt=0, le=100_000_000)
    note: str = Field(default="", max_length=80)


class QrResponse(BaseModel):
    link: str
    svg: str


# POST, not GET: keeps the UPI ID out of URLs and access logs. Nothing is stored.
@router.post("/qr")
async def qr(req: QrRequest) -> QrResponse:
    if not is_valid_vpa(req.vpa):
        raise HTTPException(422, "That does not look like a UPI ID (name@bank).")
    link = upi_link(vpa=req.vpa, payee_name=req.name, amount_paise=req.amount, note=req.note)
    return QrResponse(link=link, svg=qr_svg(link))
