from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_path: Path = Path("tabby.db")
    share_ttl_days: int = 30
    scan_rate_limit_per_min: int = 3
    share_rate_limit_per_min: int = 10
    # Local OCR. One scan at a time by default: the engine is not thread-safe and already uses all cores.
    ocr_max_concurrency: int = 1
    ocr_timeout_s: float = 30
    ocr_queue_wait_s: float = 15
    ocr_threads: int = 0  # 0 = let ONNX Runtime decide
    max_upload_bytes: int = 10 * 1024 * 1024
    max_share_bytes: int = 64 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
