from __future__ import annotations

import os

from barcode_hub.config import Settings


def _clear_barcode_hub_env(monkeypatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("BARCODE_HUB_"):
            monkeypatch.delenv(name, raising=False)


def test_allowed_url_prefixes_env_accepts_comma_separated_string(monkeypatch, tmp_path):
    _clear_barcode_hub_env(monkeypatch)
    monkeypatch.setenv("BARCODE_HUB_CONFIG", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv(
        "BARCODE_HUB_FETCH__ALLOWED_URL_PREFIXES",
        " http://* , , https://*,, data:* , file://* ",
    )

    settings = Settings()

    assert settings.fetch.allowed_url_prefixes == ["http://*", "https://*", "data:*", "file://*"]
