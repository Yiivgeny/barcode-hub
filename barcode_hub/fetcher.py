from __future__ import annotations

import base64
import binascii
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit

import httpx

from barcode_hub.config import Settings
from barcode_hub.errors import (
    BadRequestError,
    ResourceTimeoutError,
    UnprocessableContentError,
    UnsupportedMediaTypeError,
)
from barcode_hub.media import clean_content_type, guess_content_type, is_allowed_image_content_type
from barcode_hub.metrics import Metrics
from barcode_hub.url_policy import is_url_allowed


@dataclass(frozen=True)
class FetchedResource:
    data: bytes
    content_type: str
    source: str


class ResourceFetcher:
    def __init__(self, settings: Settings, metrics: Metrics | None = None) -> None:
        self.settings = settings
        self.metrics = metrics

    async def fetch(self, url: str, interaction: str) -> FetchedResource:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https", "data", "file"}:
            raise BadRequestError("Unsupported URL scheme.", {"scheme": parsed.scheme})
        if not is_url_allowed(url, self.settings.fetch.allowed_url_prefixes):
            raise BadRequestError("URL is outside the configured allowlist.")
        if parsed.scheme in {"http", "https"}:
            return await self._fetch_http(url, interaction)
        if parsed.scheme == "data":
            return self._fetch_data_url(url)
        return self._fetch_file_url(url)

    async def _fetch_http(self, url: str, interaction: str) -> FetchedResource:
        start = time.perf_counter()
        status = "success"
        try:
            timeout = httpx.Timeout(self.settings.fetch.timeout_seconds)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    if not is_url_allowed(str(response.url), self.settings.fetch.allowed_url_prefixes):
                        raise BadRequestError("Redirect target is outside the configured allowlist.")
                    content_type = clean_content_type(response.headers.get("content-type"))
                    if not is_allowed_image_content_type(
                        content_type, self.settings.media.allowed_content_types
                    ):
                        raise UnsupportedMediaTypeError("Only configured image/* content types are accepted.")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > self.settings.limits.max_file_bytes:
                        raise UnprocessableContentError("Fetched resource exceeds configured file size limit.")
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.limits.max_file_bytes:
                            raise UnprocessableContentError(
                                "Fetched resource exceeds configured file size limit."
                            )
                        chunks.append(chunk)
                    return FetchedResource(b"".join(chunks), content_type, "url")
        except httpx.TimeoutException as exc:
            status = "timeout"
            raise ResourceTimeoutError("Resource download timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = "http_error"
            raise UnprocessableContentError(
                "Fetched resource returned an unsuccessful HTTP status.",
                {"status_code": exc.response.status_code},
            ) from exc
        finally:
            if self.metrics is not None:
                self.metrics.resource_fetch_duration.labels(interaction, status).observe(
                    time.perf_counter() - start
                )

    def _fetch_data_url(self, url: str) -> FetchedResource:
        header, separator, data_part = url.partition(",")
        if not separator:
            raise BadRequestError("Invalid data URL.")
        media_part = header[5:] if header.startswith("data:") else ""
        media_type = clean_content_type(media_part.split(";", 1)[0] or "text/plain")
        if not is_allowed_image_content_type(media_type, self.settings.media.allowed_content_types):
            raise UnsupportedMediaTypeError("Only configured image/* content types are accepted.")
        is_base64 = any(part.lower() == "base64" for part in media_part.split(";")[1:])
        try:
            data = base64.b64decode(data_part, validate=True) if is_base64 else unquote_to_bytes(data_part)
        except (binascii.Error, ValueError) as exc:
            raise BadRequestError("Invalid data URL payload.") from exc
        if len(data) > self.settings.limits.max_file_bytes:
            raise UnprocessableContentError("Data URL payload exceeds configured file size limit.")
        return FetchedResource(data, media_type, "data_url")

    def _fetch_file_url(self, url: str) -> FetchedResource:
        parsed = urlsplit(url)
        if parsed.netloc not in ("", "localhost"):
            raise BadRequestError("Only local file URLs are supported.")
        path = Path(unquote(parsed.path))
        if not path.is_file():
            raise UnprocessableContentError("File URL does not point to a readable file.")
        size = os.path.getsize(path)
        if size > self.settings.limits.max_file_bytes:
            raise UnprocessableContentError("File exceeds configured file size limit.")
        content_type = clean_content_type(guess_content_type(str(path)))
        if not is_allowed_image_content_type(content_type, self.settings.media.allowed_content_types):
            raise UnsupportedMediaTypeError("Only configured image/* content types are accepted.")
        return FetchedResource(path.read_bytes(), content_type, "file_url")

