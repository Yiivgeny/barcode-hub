from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BUILD_INFO_PATH = Path(__file__).with_name("build_info.json")


@dataclass(frozen=True)
class BuildInfo:
    version: str = "0.1.0"
    build: str = "dev"
    commit: str = "000000"
    created: str = "unknown"

    @property
    def commit6(self) -> str:
        return (self.commit or "000000")[:6].lower().ljust(6, "0")

    @property
    def server_header_value(self) -> str:
        return f"Barcode-Hub {self.version} ({self.build} {self.commit6})"


def _coerce_string(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    if value is None:
        return default
    return str(value)


def load_build_info(path: Path = BUILD_INFO_PATH) -> BuildInfo:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return BuildInfo()
    if not isinstance(data, dict):
        return BuildInfo()
    return BuildInfo(
        version=_coerce_string(data, "version", "0.1.0"),
        build=_coerce_string(data, "build", "dev"),
        commit=_coerce_string(data, "commit", "000000"),
        created=_coerce_string(data, "created", "unknown"),
    )
