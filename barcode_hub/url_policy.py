from __future__ import annotations

import fnmatch
import re
from urllib.parse import urlsplit


def is_url_allowed(url: str, prefixes: list[str]) -> bool:
    return any(match_url_prefix(prefix, url) for prefix in prefixes)


def match_url_prefix(prefix: str, url: str) -> bool:
    parsed_prefix = urlsplit(prefix)
    parsed_url = urlsplit(url)
    if not parsed_prefix.scheme or parsed_prefix.scheme.lower() != parsed_url.scheme.lower():
        return False

    if parsed_url.scheme.lower() == "data":
        return _match_data_prefix(prefix, url)

    if not _match_host(parsed_prefix.hostname, parsed_url.hostname):
        return False
    if parsed_prefix.port is not None and parsed_prefix.port != parsed_url.port:
        return False
    return _match_path_prefix(parsed_prefix.path, parsed_url.path)


def _match_data_prefix(prefix: str, url: str) -> bool:
    if prefix == "data:*":
        return url.startswith("data:")
    if "*" in prefix:
        literal_prefix = prefix.split("*", 1)[0]
        return url.startswith(literal_prefix)
    return url.startswith(prefix)


def _match_host(prefix_host: str | None, url_host: str | None) -> bool:
    if prefix_host in (None, "", "*"):
        return True
    if url_host is None:
        return False
    prefix = prefix_host.lower()
    host = url_host.lower()
    if "{" in prefix:
        pattern = re.escape(prefix)
        pattern = re.sub(r"\\{[a-zA-Z_][a-zA-Z0-9_]*\\}", r"[^.]+", pattern)
        pattern = pattern.replace(r"\*", r".*")
        return re.fullmatch(pattern, host) is not None
    return fnmatch.fnmatchcase(host, prefix)


def _match_path_prefix(prefix_path: str, url_path: str) -> bool:
    if prefix_path in ("", "/"):
        return True
    prefix_segments = [part for part in prefix_path.split("/") if part]
    url_segments = [part for part in url_path.split("/") if part]
    if len(prefix_segments) > len(url_segments):
        return False
    for prefix_segment, url_segment in zip(prefix_segments, url_segments, strict=False):
        if prefix_segment == "*" or _is_placeholder(prefix_segment):
            continue
        if "*" in prefix_segment:
            if not fnmatch.fnmatchcase(url_segment, prefix_segment):
                return False
            continue
        if prefix_segment != url_segment:
            return False
    if prefix_path.endswith("/"):
        return True
    return len(prefix_segments) == len(url_segments) or url_segments[: len(prefix_segments)] == prefix_segments


def _is_placeholder(segment: str) -> bool:
    return re.fullmatch(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", segment) is not None
