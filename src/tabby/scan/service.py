"""Run a scan: decode, OCR and parse in a worker thread, one at a time, with a time limit."""

import asyncio

from tabby.config import Settings
from tabby.scan.image import prepare_image
from tabby.scan.normalize import ScanResult, normalize
from tabby.scan.ocr import OcrEngine
from tabby.scan.parse import parse_bill
from tabby.scan.schema import ScannedBill


class ScanBusy(Exception):
    pass


class ScanTimeout(Exception):
    pass


def _pipeline(data: bytes, engine: OcrEngine) -> ScannedBill:
    return parse_bill(engine.read(prepare_image(data)))


async def run_scan(data: bytes, engine: OcrEngine, slots: asyncio.Semaphore, settings: Settings) -> ScanResult:
    try:
        await asyncio.wait_for(slots.acquire(), settings.ocr_queue_wait_s)
    except TimeoutError as exc:
        raise ScanBusy from exc
    # A timed-out thread keeps running; release the slot only when it really finishes,
    # so slow scans can't pile up on the CPU.
    task = asyncio.ensure_future(asyncio.to_thread(_pipeline, data, engine))
    task.add_done_callback(lambda _: slots.release())
    try:
        scanned = await asyncio.wait_for(asyncio.shield(task), settings.ocr_timeout_s)
    except TimeoutError as exc:
        raise ScanTimeout from exc
    return normalize(scanned)
