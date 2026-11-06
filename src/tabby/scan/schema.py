"""What the scanner extracts from a bill photo, before conversion to paise."""

from pydantic import BaseModel, Field


class ScanError(Exception):
    """A scan failed in a way the user should be told about."""


class ScannedItem(BaseModel):
    name: str
    quantity: float = 1
    amount: float
    is_alcohol: bool = False
    confidence: float = 1.0
    note: str | None = None


class ScannedCharge(BaseModel):
    name: str
    amount: float
    confidence: float = 1.0
    note: str | None = None


class ScannedBill(BaseModel):
    restaurant: str | None = None
    items: list[ScannedItem]
    charges: list[ScannedCharge]
    printed_total: float | None = None
    warnings: list[str] = Field(default_factory=list)
