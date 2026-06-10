from __future__ import annotations

from pydantic import BaseModel, Field


class BarcodeResult(BaseModel):
    text: str
    data: str
    type: str
    valid: str = Field(pattern="^(yes|no|unknown)$")


class DecodeResult(BaseModel):
    barcodes: list[BarcodeResult]

