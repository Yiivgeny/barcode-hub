from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from barcode_hub.formats import BARCODE_TYPES, canonicalize_barcode_type, canonicalize_barcode_types


DEFAULT_CONFIG_PATH = "/etc/barcode-hub/config.yaml"


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class LimitsConfig(BaseModel):
    max_request_body_bytes: int = 16 * 1024 * 1024
    max_file_bytes: int = 8 * 1024 * 1024
    max_image_side_pixels: int = 4096


class OpenCvDecodeConfig(BaseModel):
    barcode_detector: bool = True


class DecodeConfig(BaseModel):
    enabled_methods: list[str] = Field(default_factory=lambda: ["GET", "POST", "PUT"])
    default_formats: list[str] = Field(default_factory=lambda: ["EAN13", "EAN8", "UPCA", "UPCE"])
    allowed_formats: list[str] = Field(default_factory=lambda: list(BARCODE_TYPES))
    request_timeout_seconds: float = 10.0
    max_side: int | None = None
    try_rotate: bool = True
    try_downscale: bool = True
    try_invert: bool = False
    opencv: OpenCvDecodeConfig = Field(default_factory=OpenCvDecodeConfig)
    return_errors: bool = True

    @field_validator("enabled_methods", mode="before")
    @classmethod
    def normalize_methods(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        methods = [str(method).upper() for method in value]
        invalid = sorted(set(methods) - {"GET", "POST", "PUT"})
        if invalid:
            raise ValueError(f"unsupported methods: {', '.join(invalid)}")
        return methods

    @field_validator("default_formats", "allowed_formats", mode="before")
    @classmethod
    def normalize_formats(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        return canonicalize_barcode_types(list(value))

    @field_validator("max_side")
    @classmethod
    def max_side_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("max_side must be positive")
        return value

    @model_validator(mode="after")
    def default_formats_must_be_allowed(self) -> "DecodeConfig":
        disallowed = sorted(set(self.default_formats) - set(self.allowed_formats))
        if disallowed:
            raise ValueError(f"default formats outside allowlist: {', '.join(disallowed)}")
        return self


class FetchConfig(BaseModel):
    timeout_seconds: float = 5.0
    allowed_url_prefixes: list[str] = Field(
        default_factory=lambda: ["http://*", "https://*", "data:*", "file://*"]
    )

    @field_validator("allowed_url_prefixes", mode="before")
    @classmethod
    def normalize_prefixes(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return list(value)


class MediaConfig(BaseModel):
    allowed_content_types: list[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "image/bmp",
            "image/tiff",
        ]
    )

    @field_validator("allowed_content_types", mode="before")
    @classmethod
    def normalize_content_types(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        return [str(item).split(";", 1)[0].strip().lower() for item in value]


class McpConfig(BaseModel):
    enabled: bool = True


class LoggingConfig(BaseModel):
    format: Literal["human", "json"] = "human"
    level: str = "INFO"


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        config_path = os.environ.get("BARCODE_HUB_CONFIG", DEFAULT_CONFIG_PATH)
        path = Path(config_path)
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"configuration file must contain a mapping: {path}")
        return data


class Settings(BaseSettings):
    app: AppConfig = Field(default_factory=AppConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    decode: DecodeConfig = Field(default_factory=DecodeConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    media: MediaConfig = Field(default_factory=MediaConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = SettingsConfigDict(
        env_prefix="BARCODE_HUB_",
        env_nested_delimiter="__",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    def ensure_requested_types_allowed(self, requested_types: list[str] | None) -> list[str]:
        types = requested_types or self.decode.default_formats
        canonical_types = [canonicalize_barcode_type(item) for item in types]
        disallowed = sorted(set(canonical_types) - set(self.decode.allowed_formats))
        if disallowed:
            from barcode_hub.errors import BadRequestError

            raise BadRequestError(
                "Requested barcode type is outside the configured allowlist.",
                {"types": disallowed},
            )
        return canonical_types


def load_settings() -> Settings:
    return Settings()
