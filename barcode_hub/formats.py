from __future__ import annotations

from enum import Enum
import re


BARCODE_TYPES: tuple[str, ...] = (
    "Codabar",
    "Code39",
    "Code39Std",
    "Code39Ext",
    "Code32",
    "PZN",
    "Code93",
    "Code128",
    "ITF",
    "ITF14",
    "DataBar",
    "DataBarOmni",
    "DataBarStk",
    "DataBarStkOmni",
    "DataBarLtd",
    "DataBarExp",
    "DataBarExpStk",
    "EAN13",
    "EAN8",
    "EAN5",
    "EAN2",
    "ISBN",
    "UPCA",
    "UPCE",
    "Telepen",
    "TelepenAlpha",
    "TelepenNumeric",
    "OtherBarcode",
    "DXFilmEdge",
    "PDF417",
    "CompactPDF417",
    "MicroPDF417",
    "Aztec",
    "AztecCode",
    "AztecRune",
    "QRCode",
    "QRCodeModel1",
    "QRCodeModel2",
    "MicroQRCode",
    "RMQRCode",
    "DataMatrix",
    "MaxiCode",
)

PSEUDO_TYPES = {
    "None",
    "All",
    "AllReadable",
    "AllCreatable",
    "AllLinear",
    "AllMatrix",
    "AllGS1",
    "AllRetail",
    "AllIndustrial",
    "EANUPC",
    "LinearCodes",
    "MatrixCodes",
    "Any",
}

BarcodeType = Enum("BarcodeType", {barcode_type: barcode_type for barcode_type in BARCODE_TYPES}, type=str)


def _key(value: str) -> str:
    return re.sub(r"[-_/\\s]+", "", value).casefold()


_ALIASES: dict[str, str] = {}

for barcode_type in BARCODE_TYPES:
    _ALIASES[_key(barcode_type)] = barcode_type

_ALIASES.update(
    {
        _key("Code 39"): "Code39",
        _key("Code 39 Standard"): "Code39Std",
        _key("Code 39 Extended"): "Code39Ext",
        _key("Code 128"): "Code128",
        _key("ITF-14"): "ITF14",
        _key("DataBar Omni"): "DataBarOmni",
        _key("DataBar Stacked"): "DataBarStk",
        _key("DataBar Stacked Omni"): "DataBarStkOmni",
        _key("DataBar Limited"): "DataBarLtd",
        _key("DataBar Expanded"): "DataBarExp",
        _key("DataBar Expanded Stacked"): "DataBarExpStk",
        _key("EAN-13"): "EAN13",
        _key("EAN-8"): "EAN8",
        _key("EAN-5"): "EAN5",
        _key("EAN-2"): "EAN2",
        _key("UPC-A"): "UPCA",
        _key("UPC-E"): "UPCE",
        _key("DX Film Edge"): "DXFilmEdge",
        _key("Compact PDF417"): "CompactPDF417",
        _key("Micro PDF417"): "MicroPDF417",
        _key("Aztec Code"): "AztecCode",
        _key("Aztec Rune"): "AztecRune",
        _key("QR Code"): "QRCode",
        _key("QR Code Model 1"): "QRCodeModel1",
        _key("QR Code Model 2"): "QRCodeModel2",
        _key("Micro QR Code"): "MicroQRCode",
        _key("rMQR Code"): "RMQRCode",
        _key("Data Matrix"): "DataMatrix",
        _key("MaxiCode"): "MaxiCode",
    }
)


class UnknownBarcodeType(ValueError):
    pass


def canonicalize_barcode_type(value: str) -> str:
    try:
        return _ALIASES[_key(value)]
    except KeyError as exc:
        raise UnknownBarcodeType(value) from exc


def canonicalize_barcode_types(values: list[str] | tuple[str, ...]) -> list[str]:
    return [canonicalize_barcode_type(value) for value in values]


def parse_types_query(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None
    return canonicalize_barcode_types([part.strip() for part in value.split(",") if part.strip()])
