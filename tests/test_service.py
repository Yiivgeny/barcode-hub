from __future__ import annotations

import base64
from unittest.mock import patch

from fastapi.testclient import TestClient

from barcode_hub.asgi import create_app
from barcode_hub.config import BuildConfig, DecodeConfig, McpConfig, MediaConfig, Settings
from barcode_hub.metrics import Metrics
from barcode_hub.models import BarcodeResult, DecodeResult
from barcode_hub.url_policy import match_url_prefix


class FakeDecodeService:
    async def decode_bytes(
        self,
        data: bytes,
        requested_types: list[str],
        interaction: str,
        source: str,
        limit_status: int = 413,
    ) -> DecodeResult:
        return DecodeResult(
            barcodes=[
                BarcodeResult(
                    text="4607084351323",
                    data=base64.b64encode(b"4607084351323").decode("ascii"),
                    type=requested_types[0],
                    valid="yes",
                )
            ]
        )


def test_put_decode_requires_allowed_image_content_type():
    settings = Settings(mcp=McpConfig(enabled=False))
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.put("/decode", content=b"not image", headers={"content-type": "text/plain"})

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert response.headers["server"] == "Barcode-Hub 0.1.0 (dev 000000)"


def test_put_decode_returns_minimal_contract_and_server_header():
    settings = Settings(mcp=McpConfig(enabled=False))
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.put(
        "/decode?types=EAN13", content=b"fake", headers={"content-type": "image/png"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "barcodes": [
            {
                "text": "4607084351323",
                "data": "NDYwNzA4NDM1MTMyMw==",
                "type": "EAN13",
                "valid": "yes",
            }
        ]
    }
    assert response.headers["server"] == "Barcode-Hub 0.1.0 (dev 000000)"


def test_post_decode_rejects_multiple_uploaded_files():
    settings = Settings(mcp=McpConfig(enabled=False))
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.post(
        "/decode",
        files=[
            ("file1", ("a.png", b"a", "image/png")),
            ("file2", ("b.png", b"b", "image/png")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_disabled_method_returns_405():
    settings = Settings(
        decode=DecodeConfig(enabled_methods=["GET"]),
        mcp=McpConfig(enabled=False),
    )
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.put("/decode", content=b"fake", headers={"content-type": "image/png"})

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_disabled"


def test_openapi_json_reflects_runtime_decode_settings():
    settings = Settings(
        build=BuildConfig(version="9.8.7", build="test", commit="abcdef123"),
        decode=DecodeConfig(
            enabled_methods=["GET", "POST", "PUT"],
            default_formats=["EAN13"],
            allowed_formats=["EAN13", "QRCode"],
        ),
        media=MediaConfig(allowed_content_types=["image/png", "image/webp"]),
        mcp=McpConfig(enabled=False),
    )
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.headers["server"] == "Barcode-Hub 9.8.7 (test abcdef)"
    schema = response.json()
    decode_path = schema["paths"]["/decode"]
    assert schema["info"]["version"] == "9.8.7"
    assert "get" in decode_path
    assert "post" in decode_path
    assert "put" in decode_path
    assert schema["components"]["schemas"]["BarcodeType"]["enum"] == ["EAN13", "QRCode"]
    assert (
        schema["components"]["parameters"]["Types"]["schema"]["items"]["$ref"]
        == "#/components/schemas/BarcodeType"
    )
    assert (
        schema["components"]["schemas"]["Barcode"]["properties"]["type"]["$ref"]
        == "#/components/schemas/BarcodeType"
    )
    assert "image/png, image/webp" in schema["components"]["parameters"]["Url"]["description"]
    assert (
        decode_path["post"]["requestBody"]["content"]["multipart/form-data"]["encoding"]["file"][
            "contentType"
        ]
        == "image/png, image/webp"
    )
    assert set(decode_path["put"]["requestBody"]["content"]) == {"image/png", "image/webp"}


def test_openapi_json_hides_disabled_decode_methods():
    settings = Settings(
        decode=DecodeConfig(enabled_methods=["GET", "POST"]),
        mcp=McpConfig(enabled=False),
    )
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    decode_path = response.json()["paths"]["/decode"]
    assert "get" in decode_path
    assert "post" in decode_path
    assert "put" not in decode_path


def test_get_decode_accepts_data_url_base64():
    settings = Settings(mcp=McpConfig(enabled=False))
    client = TestClient(create_app(settings, Metrics(settings), FakeDecodeService()))
    payload = base64.b64encode(b"fake").decode("ascii")

    response = client.get(f"/decode?url=data:image/png;base64,{payload}&types=EAN13")

    assert response.status_code == 200
    assert response.json()["barcodes"][0]["type"] == "EAN13"


def test_health_and_metrics_are_served_by_main_app_with_server_header():
    settings = Settings(mcp=McpConfig(enabled=False))
    metrics = Metrics(settings)
    client = TestClient(create_app(settings, metrics, FakeDecodeService()))

    with patch(
        "barcode_hub.health.check_zxing_cpp",
        return_value={"ok": True, "module": "zxingcpp", "version": None},
    ):
        health = client.get("/health")
    metric_response = client.get("/metrics")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.headers["server"] == "Barcode-Hub 0.1.0 (dev 000000)"
    assert metric_response.status_code == 200
    assert "barcode_hub_build_info" in metric_response.text
    assert metric_response.headers["server"] == "Barcode-Hub 0.1.0 (dev 000000)"


def test_url_prefix_matching_is_url_parser_based():
    assert match_url_prefix("https://*.example.com/", "https://cdn.example.com/image.jpg")
    assert not match_url_prefix("https://*.example.com/", "https://test.tld/example.com/image.jpg")
    assert match_url_prefix(
        "https://example.com/assets/{tenant}/", "https://example.com/assets/acme/a.png"
    )
    assert not match_url_prefix(
        "https://example.com/assets/{tenant}/", "https://example.com/other/acme/a.png"
    )
