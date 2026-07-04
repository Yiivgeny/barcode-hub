from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from prometheus_client.gc_collector import GCCollector

from barcode_hub.build_info import BuildInfo, load_build_info
from barcode_hub.config import Settings


REQUEST_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
DECODE_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
FETCH_DURATION_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
INPUT_BYTES_BUCKETS = (
    1024,
    4 * 1024,
    16 * 1024,
    64 * 1024,
    256 * 1024,
    1024 * 1024,
    4 * 1024 * 1024,
    16 * 1024 * 1024,
    64 * 1024 * 1024,
)
IMAGE_SIDE_BUCKETS = (128, 256, 512, 1024, 1600, 2048, 4096, 8192, 16384)


class Metrics:
    def __init__(self, settings: Settings, build_info: BuildInfo | None = None) -> None:
        build_info = build_info or load_build_info()
        self.registry = CollectorRegistry(auto_describe=True)
        ProcessCollector(namespace="barcode_hub", registry=self.registry)
        PlatformCollector(registry=self.registry)
        GCCollector(registry=self.registry)

        self.build_info = Info("barcode_hub_build", "Barcode Hub build info", registry=self.registry)
        self.build_info.info(
            {
                "version": build_info.version,
                "build": build_info.build,
                "commit": build_info.commit6,
            }
        )

        self.config_limit_bytes = Gauge(
            "barcode_hub_config_limit_bytes",
            "Configured byte limits.",
            ["limit"],
            registry=self.registry,
        )
        self.config_limit_bytes.labels("max_request_body").set(settings.limits.max_request_body_bytes)
        self.config_limit_bytes.labels("max_file").set(settings.limits.max_file_bytes)

        self.config_max_image_side = Gauge(
            "barcode_hub_config_max_image_side_pixels",
            "Configured maximum image side in pixels.",
            registry=self.registry,
        )
        self.config_max_image_side.set(settings.limits.max_image_side_pixels)

        self.decode_requests = Counter(
            "barcode_hub_decode_requests_total",
            "Decode requests by interaction and final status.",
            ["interaction", "status"],
            registry=self.registry,
        )
        self.decoded_barcodes = Counter(
            "barcode_hub_decoded_barcodes_total",
            "Decoded barcode count by interaction, type, and validity.",
            ["interaction", "type", "valid"],
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "barcode_hub_decode_request_duration_seconds",
            "End-to-end decode request duration.",
            ["interaction", "status"],
            buckets=REQUEST_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.recognition_duration = Histogram(
            "barcode_hub_recognition_duration_seconds",
            "ZXing-C++ recognition duration.",
            ["interaction", "status"],
            buckets=DECODE_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.resource_fetch_duration = Histogram(
            "barcode_hub_resource_fetch_duration_seconds",
            "External resource fetch duration for URL-based interactions.",
            ["interaction", "status"],
            buckets=FETCH_DURATION_BUCKETS,
            registry=self.registry,
        )
        self.input_bytes = Histogram(
            "barcode_hub_decode_input_bytes",
            "Input image byte size.",
            ["interaction", "source"],
            buckets=INPUT_BYTES_BUCKETS,
            registry=self.registry,
        )
        self.image_side = Histogram(
            "barcode_hub_decode_image_max_side_pixels",
            "Input image maximum side in pixels.",
            ["interaction"],
            buckets=IMAGE_SIDE_BUCKETS,
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


__all__ = ["CONTENT_TYPE_LATEST", "Metrics"]
