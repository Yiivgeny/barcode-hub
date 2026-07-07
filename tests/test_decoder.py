from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from barcode_hub.config import DecodeConfig, McpConfig, Settings
from barcode_hub.decoder import DecodeService
from barcode_hub.models import BarcodeResult


def _image_bytes(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, "white")
    handle = io.BytesIO()
    image.save(handle, format="PNG")
    return handle.getvalue()


def _point(x: float, y: float) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y)


def _barcode(
    *,
    text: str = "4607084351323",
    valid: bool = True,
    points: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]
    | None = None,
) -> SimpleNamespace:
    if points is None:
        points = ((10, 5), (20, 5), (20, 15), (10, 15))
    return SimpleNamespace(
        text=text,
        bytes=text.encode("ascii"),
        format="EAN13",
        valid=valid,
        position=SimpleNamespace(
            top_left=_point(*points[0]),
            top_right=_point(*points[1]),
            bottom_right=_point(*points[2]),
            bottom_left=_point(*points[3]),
        ),
    )


class FakeZxing:
    BarcodeFormat = SimpleNamespace(EAN13="EAN13")

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def read_barcodes(self, image, **kwargs):
        self.calls.append({"size": image.size, "kwargs": kwargs})
        response = self.responses.pop(0)
        if callable(response):
            return response(image)
        return response


@pytest.mark.asyncio
async def test_max_side_resizes_before_decode_and_maps_coords(monkeypatch):
    fake = FakeZxing([[_barcode()]])
    monkeypatch.setitem(
        sys.modules,
        "zxingcpp",
        SimpleNamespace(BarcodeFormat=fake.BarcodeFormat, read_barcodes=fake.read_barcodes),
    )
    settings = Settings(
        decode=DecodeConfig(max_side=100, opencv={"barcode_detector": False}),
        mcp=McpConfig(enabled=False),
    )

    result = await DecodeService(settings).decode_bytes(
        _image_bytes((200, 100)), ["EAN13"], "test", "upload"
    )

    assert fake.calls[0]["size"] == (100, 50)
    barcode = result.barcodes[0]
    assert barcode.coords.top_left.x == 20
    assert barcode.coords.top_left.y == 10
    assert barcode.coords.bottom_right.x == 40
    assert barcode.coords.bottom_right.y == 30


@pytest.mark.asyncio
async def test_opencv_barcode_detector_fallback_runs_after_empty_zxing(monkeypatch):
    fake = FakeZxing([[]])
    monkeypatch.setitem(
        sys.modules,
        "zxingcpp",
        SimpleNamespace(BarcodeFormat=fake.BarcodeFormat, read_barcodes=fake.read_barcodes),
    )
    barcode = BarcodeResult(
        text="4607084351323",
        data="NDYwNzA4NDM1MTMyMw==",
        type="EAN13",
        valid="yes",
        coords={
            "top_left": {"x": 1, "y": 2},
            "top_right": {"x": 3, "y": 2},
            "bottom_right": {"x": 3, "y": 4},
            "bottom_left": {"x": 1, "y": 4},
        },
    )
    monkeypatch.setattr(
        DecodeService,
        "_decode_opencv_barcode_detector",
        lambda *_: [barcode],
    )
    settings = Settings(
        decode=DecodeConfig(opencv={"barcode_detector": True}),
        mcp=McpConfig(enabled=False),
    )

    result = await DecodeService(settings).decode_bytes(
        _image_bytes((100, 80)), ["EAN13"], "test", "upload"
    )

    assert len(fake.calls) == 1
    assert result.barcodes == [barcode]


@pytest.mark.asyncio
async def test_opencv_barcode_detector_fallback_can_be_disabled(monkeypatch):
    fake = FakeZxing([[]])
    monkeypatch.setitem(
        sys.modules,
        "zxingcpp",
        SimpleNamespace(BarcodeFormat=fake.BarcodeFormat, read_barcodes=fake.read_barcodes),
    )

    def unexpected_fallback(*_):
        raise AssertionError("OpenCV fallback should not run")

    monkeypatch.setattr(DecodeService, "_decode_opencv_barcode_detector", unexpected_fallback)
    settings = Settings(
        decode=DecodeConfig(opencv={"barcode_detector": False}),
        mcp=McpConfig(enabled=False),
    )

    result = await DecodeService(settings).decode_bytes(
        _image_bytes((100, 80)), ["EAN13"], "test", "upload"
    )

    assert len(fake.calls) == 1
    assert result.barcodes == []
