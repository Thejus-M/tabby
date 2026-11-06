"""Local OCR engine (RapidOCR: PP-OCR models on ONNX Runtime, CPU). Nothing leaves the server."""

from typing import Protocol

from PIL import Image

from tabby.scan.layout import Fragment


class OcrEngine(Protocol):
    def read(self, img: Image.Image) -> list[Fragment]: ...


class RapidOcrEngine:
    """Not safe for concurrent calls; the scan service serialises access."""

    def __init__(self, threads: int = 0) -> None:
        from rapidocr import RapidOCR  # heavy import, keep it off the module import path

        params = {"Global.log_level": "error", "Global.max_side_len": 3000}
        if threads > 0:
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = threads
        self._engine = RapidOCR(params=params)

    def read(self, img: Image.Image) -> list[Fragment]:
        result = self._engine(img)
        if result.boxes is None or not result.txts:
            return []
        return [
            Fragment.from_box(box.tolist(), text, float(score))
            for box, text, score in zip(result.boxes, result.txts, result.scores, strict=True)
        ]

    def warm_up(self) -> None:
        """Models load lazily on first call; do it at startup instead of on the first user's scan."""
        self.read(Image.new("RGB", (320, 64), "white"))


def load_engine(threads: int = 0) -> RapidOcrEngine:
    engine = RapidOcrEngine(threads)
    engine.warm_up()
    return engine
