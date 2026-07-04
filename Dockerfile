FROM python:3.12-slim AS runtime

ARG VERSION=0.1.0
ARG BUILD=dev
ARG VCS_REF=000000
ARG CREATED=unknown

LABEL org.opencontainers.image.title="Barcode Hub" \
      org.opencontainers.image.description="Python barcode recognition service backed by ZXing-C++." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/openai/barcode-hub"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 barcode

COPY pyproject.toml README.md LICENSE ./
COPY barcode_hub ./barcode_hub
COPY spec ./spec

RUN VERSION="$VERSION" BUILD="$BUILD" VCS_REF="$VCS_REF" CREATED="$CREATED" python - <<'PY'
import json
import os
from pathlib import Path

Path("barcode_hub/build_info.json").write_text(
    json.dumps(
        {
            "version": os.environ["VERSION"],
            "build": os.environ["BUILD"],
            "commit": os.environ["VCS_REF"],
            "created": os.environ["CREATED"],
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

RUN pip install --no-cache-dir . \
    && chown -R barcode:barcode /app

USER barcode

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json, urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3); raise SystemExit(0 if json.load(r).get('status') == 'ok' else 1)"

CMD ["barcode-hub"]
