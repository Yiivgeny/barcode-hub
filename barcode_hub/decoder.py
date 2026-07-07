from __future__ import annotations

import base64
import io
import time
from collections.abc import Callable, Iterable

import anyio
from PIL import Image, UnidentifiedImageError

from barcode_hub.config import Settings
from barcode_hub.errors import UnprocessableContentError
from barcode_hub.formats import canonicalize_barcode_type
from barcode_hub.metrics import Metrics
from barcode_hub.models import BarcodeCoords, BarcodePoint, BarcodeResult, DecodeResult

PointTransform = Callable[[float, float], tuple[int, int]]


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


def _point(point: object, transform: PointTransform) -> BarcodePoint:
    x, y = transform(float(getattr(point, "x")), float(getattr(point, "y")))
    return BarcodePoint(x=x, y=y)


def _coords(barcode: object, transform: PointTransform) -> BarcodeCoords:
    position = getattr(barcode, "position")
    return BarcodeCoords(
        top_left=_point(getattr(position, "top_left"), transform),
        top_right=_point(getattr(position, "top_right"), transform),
        bottom_right=_point(getattr(position, "bottom_right"), transform),
        bottom_left=_point(getattr(position, "bottom_left"), transform),
    )


def _clamp(value: int, upper_bound: int) -> int:
    return max(0, min(value, upper_bound - 1))


def _image_transform(processed_size: tuple[int, int], original_size: tuple[int, int]) -> PointTransform:
    processed_width, processed_height = processed_size
    original_width, original_height = original_size
    scale_x = processed_width / original_width
    scale_y = processed_height / original_height

    def transform(x: float, y: float) -> tuple[int, int]:
        return (
            _clamp(round(x / scale_x), original_width),
            _clamp(round(y / scale_y), original_height),
        )

    return transform


def _coords_from_points(points: Iterable[tuple[float, float]], transform: PointTransform) -> BarcodeCoords:
    mapped = [BarcodePoint(x=x, y=y) for x, y in (transform(x, y) for x, y in points)]
    top_left = min(mapped, key=lambda point: point.x + point.y)
    bottom_right = max(mapped, key=lambda point: point.x + point.y)
    top_right = max(mapped, key=lambda point: point.x - point.y)
    bottom_left = min(mapped, key=lambda point: point.x - point.y)
    return BarcodeCoords(
        top_left=top_left,
        top_right=top_right,
        bottom_right=bottom_right,
        bottom_left=bottom_left,
    )


def _has_valid_barcode(results: Iterable[BarcodeResult]) -> bool:
    return any(result.valid == "yes" for result in results)


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

        original_image = self._load_image(data)
        input_max_side = max(original_image.size)
        image, transform = self._prepare_image(original_image)
        effective_max_side = max(image.size)
        if effective_max_side > self.settings.limits.max_image_side_pixels:
            raise UnprocessableContentError("Image side exceeds configured limit.")

        if self.metrics is not None:
            self.metrics.input_bytes.labels(interaction, source).observe(len(data))
            self.metrics.image_side.labels(interaction).observe(input_max_side)

        start = time.perf_counter()
        status = "success"
        effective_return_errors = (
            self.settings.decode.return_errors if return_errors is None else return_errors
        )
        try:
            results = await anyio.to_thread.run_sync(
                self._decode_image,
                image,
                original_image,
                tuple(requested_types),
                effective_return_errors,
                transform,
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

    def _prepare_image(self, image: Image.Image) -> tuple[Image.Image, PointTransform]:
        original_size = image.size
        max_side = self.settings.decode.max_side
        if max_side is None or max(original_size) <= max_side:
            return image, _image_transform(original_size, original_size)

        scale = max_side / max(original_size)
        target_size = (
            max(1, round(original_size[0] * scale)),
            max(1, round(original_size[1] * scale)),
        )
        resized = image.resize(target_size, Image.Resampling.LANCZOS)
        return resized, _image_transform(target_size, original_size)

    def _decode_image(
        self,
        image: Image.Image,
        original_image: Image.Image,
        requested_types: tuple[str, ...],
        return_errors: bool,
        transform: PointTransform,
    ) -> list[BarcodeResult]:
        results = self._decode_image_once(image, requested_types, return_errors, transform)
        if _has_valid_barcode(results) or not self.settings.decode.opencv.barcode_detector:
            return results

        opencv_results = self._decode_opencv_barcode_detector(image, requested_types, transform)
        if _has_valid_barcode(opencv_results) or not results:
            return opencv_results
        return results

    def _decode_image_once(
        self,
        image: Image.Image,
        requested_types: tuple[str, ...],
        return_errors: bool,
        transform: PointTransform,
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
        return self._map_barcodes(barcodes, requested_types, transform)

    def _decode_opencv_barcode_detector(
        self,
        image: Image.Image,
        requested_types: tuple[str, ...],
        transform: PointTransform,
    ) -> list[BarcodeResult]:
        try:
            import cv2
            import numpy as np
        except ImportError:
            return []

        detector_class = getattr(getattr(cv2, "barcode", None), "BarcodeDetector", None)
        if detector_class is None:
            detector_class = getattr(cv2, "barcode_BarcodeDetector", None)
        if detector_class is None:
            return []

        bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        try:
            ok, decoded_values, decoded_types, points = detector_class().detectAndDecodeWithType(
                bgr
            )
        except cv2.error:
            return []
        if not ok or points is None:
            return []

        requested = set(requested_types)
        results: list[BarcodeResult] = []
        for index, text in enumerate(decoded_values):
            if not text:
                continue
            try:
                barcode_type = canonicalize_barcode_type(str(decoded_types[index]))
            except ValueError:
                continue
            if barcode_type not in requested:
                continue
            raw = str(text).encode("utf-8")
            result_points = [(float(x), float(y)) for x, y in points[index]]
            results.append(
                BarcodeResult(
                    text=str(text),
                    data=base64.b64encode(raw).decode("ascii"),
                    type=barcode_type,
                    valid="yes",
                    coords=_coords_from_points(result_points, transform),
                )
            )
        return results

    def _map_barcodes(
        self,
        barcodes: Iterable[object],
        requested_types: tuple[str, ...],
        transform: PointTransform,
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
                    coords=_coords(barcode, transform),
                )
            )
        return results
