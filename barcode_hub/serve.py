from __future__ import annotations

import asyncio
import logging

import uvicorn

from barcode_hub.asgi import create_app
from barcode_hub.build_info import load_build_info
from barcode_hub.config import load_settings
from barcode_hub.logging import configure_logging
from barcode_hub.metrics import Metrics


async def _serve() -> None:
    settings = load_settings()
    build_info = load_build_info()
    configure_logging(settings)
    metrics = Metrics(settings, build_info)
    api_app = create_app(settings, metrics, build_info=build_info)

    api_server = uvicorn.Server(
        uvicorn.Config(
            api_app,
            host=settings.app.host,
            port=settings.app.port,
            log_config=None,
            server_header=False,
        )
    )

    logging.getLogger(__name__).info(
        "starting barcode-hub api=%s:%s",
        settings.app.host,
        settings.app.port,
    )
    await api_server.serve()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
