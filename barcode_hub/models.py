from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from barcode_hub.formats import BarcodeType


class BarcodeValidity(str, Enum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


class Barcode(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    text: str = Field(description="Decoded text returned by ZXing-C++.")
    data: str = Field(
        description="Standard base64 representation of raw decoded payload bytes, without a data: prefix.",
        pattern=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
        json_schema_extra={"contentEncoding": "base64"},
    )
    type: BarcodeType
    valid: BarcodeValidity


class DecodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcodes: list[Barcode]


BarcodeResult = Barcode
