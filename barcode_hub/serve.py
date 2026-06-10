from __future__ import annotations

import asyncio
import logging

import uvicorn

from barcode_hub.asgi import create_admin_app, create_app
from barcode_hub.config import load_settings
from barcode_hub.logging import configure_logging
from barcode_hub.metrics import Metrics


async def _serve() -> None:
    settings = load_settings()
    configure_logging(settings)
    metrics = Metrics(settings)
    api_app = create_app(settings, metrics)
    admin_app = create_admin_app(settings, metrics)

    api_server = uvicorn.Server(
        uvicorn.Config(
            api_app,
            host=settings.app.host,
            port=settings.app.port,
            log_config=None,
            server_header=False,
        )
    )
    admin_server = uvicorn.Server(
        uvicorn.Config(
            admin_app,
            host=settings.app.admin_host,
            port=settings.app.admin_port,
            log_config=None,
            server_header=False,
        )
    )

    logging.getLogger(__name__).info(
        "starting barcode-hub api=%s:%s admin=%s:%s",
        settings.app.host,
        settings.app.port,
        settings.app.admin_host,
        settings.app.admin_port,
    )
    await asyncio.gather(api_server.serve(), admin_server.serve())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
