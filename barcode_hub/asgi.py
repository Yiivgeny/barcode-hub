from __future__ import annotations

import asyncio
import copy
import contextlib
import logging
import time
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from barcode_hub.config import Settings, load_settings
from barcode_hub.decoder import DecodeService
from barcode_hub.errors import (
    AppError,
    BadRequestError,
    InternalServiceError,
    PayloadTooLargeError,
    ResourceTimeoutError,
    UnsupportedMediaTypeError,
    ensure_decode_method_enabled,
)
from barcode_hub.fetcher import ResourceFetcher
from barcode_hub.formats import UnknownBarcodeType, parse_types_query
from barcode_hub.health import health_payload
from barcode_hub.media import is_allowed_image_content_type
from barcode_hub.metrics import CONTENT_TYPE_LATEST, Metrics
from barcode_hub.models import DecodeResult

LOGGER = logging.getLogger(__name__)
SPEC_DIR = Path(__file__).resolve().parents[1] / "spec"
DECODE_METHODS = ("get", "post", "put")


def create_app(
    settings: Settings | None = None,
    metrics: Metrics | None = None,
    decode_service: DecodeService | None = None,
    fetcher: ResourceFetcher | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    metrics = metrics or Metrics(settings)
    decode_service = decode_service or DecodeService(settings, metrics)
    fetcher = fetcher or ResourceFetcher(settings, metrics)
    mcp_server = (
        _build_mcp_server(settings, metrics, decode_service, fetcher)
        if settings.mcp.enabled
        else None
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if mcp_server is None:
            yield
            return
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(
        title="Barcode Hub API",
        version=settings.build.version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.metrics = metrics
    app.state.decode_service = decode_service
    app.state.fetcher = fetcher

    _install_common_handlers(app, settings)
    _install_api_routes(app, settings, metrics, decode_service, fetcher)
    _install_service_routes(app, metrics)
    _install_openapi(app, settings)

    if mcp_server is not None:
        app.mount("/mcp", mcp_server.streamable_http_app())

    return app


def _install_service_routes(app: FastAPI, metrics: Metrics) -> None:
    @app.get("/health")
    async def health() -> JSONResponse:
        status_code, payload = health_payload()
        return JSONResponse(payload, status_code=status_code)

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        return Response(metrics.render(), media_type=CONTENT_TYPE_LATEST)


def _install_common_handlers(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def response_header_and_body_limit(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if (
            request.url.path == "/decode"
            and request.method in {"POST", "PUT"}
            and content_length
            and int(content_length) > settings.limits.max_request_body_bytes
        ):
            response = JSONResponse(
                PayloadTooLargeError("Request body exceeds configured limit.").response_body(),
                status_code=413,
            )
        else:
            response = await call_next(request)
        response.headers["Server"] = settings.build.server_header_value
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(exc.response_body(), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            BadRequestError("Request validation failed.", {"errors": exc.errors()}).response_body(),
            status_code=400,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("unexpected_error", exc_info=exc)
        error = InternalServiceError("Unexpected server error.")
        return JSONResponse(error.response_body(), status_code=500)


def _install_api_routes(
    app: FastAPI,
    settings: Settings,
    metrics: Metrics,
    decode_service: DecodeService,
    fetcher: ResourceFetcher,
) -> None:
    @app.get("/decode", response_model=DecodeResult)
    async def decode_get(url: str = Query(...), types: str | None = Query(None)) -> DecodeResult:
        ensure_decode_method_enabled("GET", settings.decode.enabled_methods)
        requested_types = _parse_requested_types(settings, types)

        async def work() -> DecodeResult:
            resource = await fetcher.fetch(url, "get_url")
            return await decode_service.decode_bytes(
                resource.data,
                requested_types,
                interaction="get_url",
                source=resource.source,
                limit_status=422,
            )

        return await _run_decode_interaction(settings, metrics, "get_url", work)

    @app.post("/decode", response_model=DecodeResult)
    async def decode_post(request: Request, types: str | None = Query(None)) -> DecodeResult:
        ensure_decode_method_enabled("POST", settings.decode.enabled_methods)
        requested_types = _parse_requested_types(settings, types)
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
            raise UnsupportedMediaTypeError("POST /decode expects multipart/form-data.")
        form = await request.form()
        uploads = [
            value for _, value in form.multi_items() if isinstance(value, StarletteUploadFile)
        ]
        if len(uploads) != 1:
            raise BadRequestError("POST /decode accepts exactly one uploaded file.")
        upload = uploads[0]
        if not is_allowed_image_content_type(
            upload.content_type, settings.media.allowed_content_types
        ):
            raise UnsupportedMediaTypeError("Only configured image/* content types are accepted.")
        data = await upload.read()
        if len(data) > settings.limits.max_request_body_bytes:
            raise PayloadTooLargeError("Request body exceeds configured limit.")

        async def work() -> DecodeResult:
            return await decode_service.decode_bytes(
                data,
                requested_types,
                interaction="post_multipart",
                source="upload",
                limit_status=413,
            )

        return await _run_decode_interaction(settings, metrics, "post_multipart", work)

    @app.put("/decode", response_model=DecodeResult)
    async def decode_put(request: Request, types: str | None = Query(None)) -> DecodeResult:
        ensure_decode_method_enabled("PUT", settings.decode.enabled_methods)
        requested_types = _parse_requested_types(settings, types)
        if not is_allowed_image_content_type(
            request.headers.get("content-type"), settings.media.allowed_content_types
        ):
            raise UnsupportedMediaTypeError("Only configured image/* content types are accepted.")
        data = await request.body()
        if len(data) > settings.limits.max_request_body_bytes:
            raise PayloadTooLargeError("Request body exceeds configured limit.")

        async def work() -> DecodeResult:
            return await decode_service.decode_bytes(
                data, requested_types, interaction="put_binary", source="raw_body", limit_status=413
            )

        return await _run_decode_interaction(settings, metrics, "put_binary", work)


async def _run_decode_interaction(
    settings: Settings, metrics: Metrics, interaction: str, work
) -> DecodeResult:
    start = time.perf_counter()
    status = "success"
    try:
        result = await asyncio.wait_for(work(), timeout=settings.decode.request_timeout_seconds)
        return result
    except ResourceTimeoutError:
        status = "resource_timeout"
        raise
    except AppError as exc:
        status = exc.code
        raise
    except asyncio.TimeoutError as exc:
        status = "request_timeout"
        raise ResourceTimeoutError("Request processing timed out.") from exc
    finally:
        metrics.decode_requests.labels(interaction, status).inc()
        metrics.request_duration.labels(interaction, status).observe(time.perf_counter() - start)


def _parse_requested_types(settings: Settings, types: str | None) -> list[str]:
    try:
        requested = parse_types_query(types)
    except UnknownBarcodeType as exc:
        raise BadRequestError("Unknown barcode type.", {"type": str(exc)}) from exc
    return settings.ensure_requested_types_allowed(requested)


def _install_openapi(app: FastAPI, settings: Settings) -> None:
    openapi_path = next(
        path
        for path in (SPEC_DIR / "openapi.yaml", Path.cwd() / "spec" / "openapi.yaml")
        if path.exists()
    )

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        base_schema = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))
        app.openapi_schema = _runtime_openapi_schema(base_schema, settings)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def _runtime_openapi_schema(base_schema: dict[str, Any], settings: Settings) -> dict[str, Any]:
    schema = copy.deepcopy(base_schema)
    _apply_openapi_info(schema, settings)
    _apply_openapi_decode_methods(schema, settings)
    _apply_openapi_barcode_formats(schema, settings)
    _apply_openapi_media_types(schema, settings)
    return schema


def _apply_openapi_info(schema: dict[str, Any], settings: Settings) -> None:
    info = schema.get("info")
    if isinstance(info, dict):
        info["version"] = settings.build.version


def _apply_openapi_decode_methods(schema: dict[str, Any], settings: Settings) -> None:
    decode_path = schema.get("paths", {}).get("/decode")
    if not isinstance(decode_path, dict):
        return

    enabled_methods = {method.lower() for method in settings.decode.enabled_methods}
    for method in DECODE_METHODS:
        if method not in enabled_methods:
            decode_path.pop(method, None)

    if not any(method in decode_path for method in DECODE_METHODS):
        schema["paths"].pop("/decode", None)


def _apply_openapi_barcode_formats(schema: dict[str, Any], settings: Settings) -> None:
    barcode_type = schema.get("components", {}).get("schemas", {}).get("BarcodeType")
    if isinstance(barcode_type, dict):
        barcode_type["enum"] = list(settings.decode.allowed_formats)


def _apply_openapi_media_types(schema: dict[str, Any], settings: Settings) -> None:
    allowed_content_types = list(settings.media.allowed_content_types)
    url_parameter = schema.get("components", {}).get("parameters", {}).get("Url")
    if isinstance(url_parameter, dict):
        description = url_parameter.get("description", "")
        url_parameter["description"] = (
            f"{description}\n\nFetched resource Content-Type must be one of: "
            f"{', '.join(allowed_content_types)}."
        )

    decode_path = schema.get("paths", {}).get("/decode")
    if not isinstance(decode_path, dict):
        return

    post = decode_path.get("post")
    if isinstance(post, dict):
        multipart = post.get("requestBody", {}).get("content", {}).get("multipart/form-data")
        if isinstance(multipart, dict):
            multipart.setdefault("encoding", {}).setdefault("file", {})["contentType"] = ", ".join(
                allowed_content_types
            )

    put = decode_path.get("put")
    if isinstance(put, dict):
        content = put.get("requestBody", {}).get("content")
        if isinstance(content, dict):
            binary_schema = content.get("image/*", {}).get(
                "schema",
                {"type": "string", "format": "binary", "description": "Raw image bytes to decode."},
            )
            content.clear()
            for content_type in allowed_content_types:
                content[content_type] = {"schema": copy.deepcopy(binary_schema)}


def _build_mcp_server(
    settings: Settings, metrics: Metrics, decode_service: DecodeService, fetcher: ResourceFetcher
):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "Barcode Hub",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    async def decode_url(url: str, types: list[str] | None = None) -> DecodeResult:
        """Decode barcodes from a URL, including data:base64 URLs."""
        try:
            requested_types = settings.ensure_requested_types_allowed(types)
            resource = await fetcher.fetch(url, "mcp_url")

            async def work() -> DecodeResult:
                return await decode_service.decode_bytes(
                    resource.data,
                    requested_types,
                    interaction="mcp_url",
                    source=resource.source,
                    limit_status=422,
                )

            return await _run_decode_interaction(settings, metrics, "mcp_url", work)
        except AppError as exc:
            raise ValueError(f"{exc.code}: {exc.message}") from exc
        except UnknownBarcodeType as exc:
            raise ValueError(f"disallowed_type: Unknown barcode type {exc}") from exc

    return mcp
