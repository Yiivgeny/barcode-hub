from __future__ import annotations

import base64
import io
import time
from typing import Iterable

import anyio
from PIL import Image, UnidentifiedImageError

from barcode_hub.config import Settings
from barcode_hub.errors import UnprocessableContentError
from barcode_hub.formats import canonicalize_barcode_type
from barcode_hub.metrics import Metrics
from barcode_hub.models import BarcodeCoords, BarcodePoint, BarcodeResult, DecodeResult


def _validity(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "unknown"


def _raw_bytes(barcode: object) -> bytes:
    raw = getattr(barcode, "bytes", None)
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return str(getattr(barcode, "text", "")).encode("utf-8")


def _point(point: object, offset: tuple[int, int]) -> BarcodePoint:
    return BarcodePoint(
        x=int(getattr(point, "x")) + offset[0],
        y=int(getattr(point, "y")) + offset[1],
    )


def _coords(barcode: object, offset: tuple[int, int]) -> BarcodeCoords:
    position = getattr(barcode, "position")
    return BarcodeCoords(
        top_left=_point(getattr(position, "top_left"), offset),
        top_right=_point(getattr(position, "top_right"), offset),
        bottom_right=_point(getattr(position, "bottom_right"), offset),
        bottom_left=_point(getattr(position, "bottom_left"), offset),
    )


class DecodeService:
    def __init__(self, settings: Settings, metrics: Metrics | None = None) -> None:
        self.settings = settings
        self.metrics = metrics

    async def decode_bytes(
        self,
        data: bytes,
        requested_types: list[str],
        interaction: str,
        source: str,
        limit_status: int = 413,
        return_errors: bool | None = None,
    ) -> DecodeResult:
        if len(data) > self.settings.limits.max_file_bytes:
            message = "Input file exceeds configured file size limit."
            if limit_status == 422:
                raise UnprocessableContentError(message)
            from barcode_hub.errors import PayloadTooLargeError

            raise PayloadTooLargeError(message)

        image = self._load_image(data)
        max_side = max(image.size)
        if max_side > self.settings.limits.max_image_side_pixels:
            raise UnprocessableContentError("Image side exceeds configured limit.")

        if self.metrics is not None:
            self.metrics.input_bytes.labels(interaction, source).observe(len(data))
            self.metrics.image_side.labels(interaction).observe(max_side)

        start = time.perf_counter()
        status = "success"
        effective_return_errors = (
            self.settings.decode.return_errors if return_errors is None else return_errors
        )
        try:
            results = await anyio.to_thread.run_sync(
                self._decode_image, image, tuple(requested_types), effective_return_errors
            )
        except Exception:
            status = "error"
            raise
        finally:
            if self.metrics is not None:
                self.metrics.recognition_duration.labels(interaction, status).observe(
                    time.perf_counter() - start
                )

        response = DecodeResult(barcodes=results)
        if self.metrics is not None:
            for barcode in response.barcodes:
                self.metrics.decoded_barcodes.labels(interaction, barcode.type, barcode.valid).inc()
        return response

    def _load_image(self, data: bytes) -> Image.Image:
        try:
            image = Image.open(io.BytesIO(data))
            image.load()
            return image.convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise UnprocessableContentError("Input is not a readable image.") from exc

    def _decode_image(
        self, image: Image.Image, requested_types: tuple[str, ...], return_errors: bool
    ) -> list[BarcodeResult]:
        import zxingcpp

        formats = tuple(getattr(zxingcpp.BarcodeFormat, item) for item in requested_types)
        zxing_formats = formats[0] if len(formats) == 1 else formats
        barcodes = zxingcpp.read_barcodes(
            image,
            formats=zxing_formats,
            try_rotate=self.settings.decode.try_rotate,
            try_downscale=self.settings.decode.try_downscale,
            try_invert=self.settings.decode.try_invert,
            return_errors=return_errors,
        )
        return self._map_barcodes(barcodes, requested_types, offset=(0, 0))

    def _map_barcodes(
        self,
        barcodes: Iterable[object],
        requested_types: tuple[str, ...],
        offset: tuple[int, int],
    ) -> list[BarcodeResult]:
        requested = set(requested_types)
        results: list[BarcodeResult] = []
        for barcode in barcodes:
            barcode_type = canonicalize_barcode_type(str(getattr(barcode, "format", "")))
            if barcode_type not in requested:
                continue
            raw = _raw_bytes(barcode)
            results.append(
                BarcodeResult(
                    text=str(getattr(barcode, "text", "")),
                    data=base64.b64encode(raw).decode("ascii"),
                    type=barcode_type,
                    valid=_validity(getattr(barcode, "valid", None)),
                    coords=_coords(barcode, offset),
                )
            )
        return results

