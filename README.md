# Barcode Hub

Barcode Hub is a Python service for barcode recognition over HTTP and MCP. The
recognition backend is `zxing-cpp`.

The API response body is intentionally minimal:

```json
{
  "barcodes": [
    {
      "text": "4607084351323",
      "data": "NDYwNzA4NDM1MTMyMw==",
      "type": "EAN13",
      "valid": "yes",
      "coords": {
        "top_left": {"x": 12, "y": 34},
        "top_right": {"x": 212, "y": 34},
        "bottom_right": {"x": 212, "y": 88},
        "bottom_left": {"x": 12, "y": 88}
      }
    }
  ]
}
```

Build identity is emitted at runtime as an HTTP `Server` header on every
response, but it is not part of the OpenAPI or MCP contracts.

## Endpoints

Single service port, default `8080`:

- `GET /` shows a small HTML server index with build info and resource links
- `GET /decode?url=...&types=EAN13,UPCA`
- `POST /decode` with exactly one `multipart/form-data` image file
- `PUT /decode` with raw image bytes and an `image/*` Content-Type
- `GET /health` checks that `zxingcpp` is importable and exposes the required API
- `GET /metrics` exposes Prometheus metrics
- `/mcp` when MCP is enabled
- `/docs`, `/redoc`, `/openapi.json`

## Run Locally

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
barcode-hub
```

Decode from a URL:

```bash
curl 'http://localhost:8080/decode?url=https://example.com/image.jpg&types=EAN13,UPCA'
```

Decode an uploaded file:

```bash
curl -F 'file=@image.jpg;type=image/jpeg' 'http://localhost:8080/decode?types=EAN13'
```

Decode raw bytes:

```bash
curl -X PUT --data-binary @image.jpg -H 'Content-Type: image/jpeg' \
  'http://localhost:8080/decode?types=EAN13'
```

## Docker

Use the prebuilt image from GitHub Container Registry:

```bash
docker pull ghcr.io/yiivgeny/barcode-hub:latest
docker run --rm -p 8080:8080 ghcr.io/yiivgeny/barcode-hub:latest
```

Or build locally:

```bash
docker build -t barcode-hub:local .
docker run --rm -p 8080:8080 barcode-hub:local
```

Docker Compose builds the local image by default:

```bash
docker compose up --build
```

## Configuration

Configuration is loaded from `/etc/barcode-hub/config.yaml` when it exists.
Environment variables override file values. Nested variables use `__` and the
`BARCODE_HUB_` prefix.

Example YAML:

```yaml
app:
  port: 8080
limits:
  max_request_body_bytes: 16777216
  max_file_bytes: 8388608
  max_image_side_pixels: 4096
decode:
  enabled_methods: ["GET", "POST", "PUT"]
  default_formats: ["EAN13", "EAN8", "UPCA", "UPCE"]
  allowed_formats: ["EAN13", "EAN8", "UPCA", "UPCE", "QRCode", "DataMatrix"]
  request_timeout_seconds: 10
fetch:
  timeout_seconds: 5
  allowed_url_prefixes: ["https://*.example.com/", "data:*"]
media:
  allowed_content_types: ["image/png", "image/jpeg", "image/webp"]
mcp:
  enabled: true
logging:
  format: human
  level: INFO
```

Common environment variables:

- `BARCODE_HUB_LIMITS__MAX_REQUEST_BODY_BYTES`
- `BARCODE_HUB_LIMITS__MAX_FILE_BYTES`
- `BARCODE_HUB_LIMITS__MAX_IMAGE_SIDE_PIXELS`
- `BARCODE_HUB_DECODE__ENABLED_METHODS`
- `BARCODE_HUB_DECODE__REQUEST_TIMEOUT_SECONDS`
- `BARCODE_HUB_DECODE__RETURN_ERRORS`
- `BARCODE_HUB_FETCH__TIMEOUT_SECONDS`
- `BARCODE_HUB_FETCH__ALLOWED_URL_PREFIXES`
- `BARCODE_HUB_MEDIA__ALLOWED_CONTENT_TYPES`
- `BARCODE_HUB_MCP__ENABLED`
- `BARCODE_HUB_LOGGING__FORMAT`

`allowed_url_prefixes` are matched by parsing URLs. For example,
`https://*.example.com/` matches `https://cdn.example.com/image.jpg`, but does
not match `https://test.tld/example.com/image.jpg`.

## Metrics

`/metrics` includes process/platform/gc metrics and service metrics:

- `barcode_hub_decode_requests_total{interaction,status}`
- `barcode_hub_decoded_barcodes_total{interaction,type,valid}`
- `barcode_hub_decode_request_duration_seconds{interaction,status}`
- `barcode_hub_recognition_duration_seconds{interaction,status}`
- `barcode_hub_resource_fetch_duration_seconds{interaction,status}`
- `barcode_hub_decode_input_bytes{interaction,source}`
- `barcode_hub_decode_image_max_side_pixels{interaction}`
- `barcode_hub_build_info`

Interaction labels are `get_url`, `post_multipart`, `put_binary`, and `mcp_url`.

## MCP

When enabled, `/mcp` exposes the `decode_url` tool:

```text
decode_url(url: string, types?: list[BarcodeType]) -> DecodeResult
```

`data:image/...;base64,...` URLs are supported. MCP tool errors use MCP error
semantics and stable domain codes in the message, such as `invalid_url`,
`disallowed_type`, `resource_timeout`, and `request_too_large`.

## Development

```bash
pip install -e '.[dev]'
python scripts/generate_contract.py --check
pytest
ruff check .
```

The shared response schema is `spec/decode-result.schema.json`. The OpenAPI
contract is `spec/openapi.yaml`. The MCP contract is `spec/mcp.md`.

Runtime `/openapi.json` is loaded from `spec/openapi.yaml` and then narrowed by
the active configuration: disabled `/decode` methods are removed, `BarcodeType`
is limited to `decode.allowed_formats`, and request media types reflect
`media.allowed_content_types`. The `types` query parameter default reflects
`decode.default_formats`. Swagger UI and ReDoc use that runtime schema.

`DecodeResult`, `Barcode`, `BarcodeType`, and `BarcodeValidity` are generated
from the Python models and format enum:

```bash
python scripts/generate_contract.py
```

The generator updates `spec/decode-result.schema.json` and only the marked
`components.schemas` block in `spec/openapi.yaml`. Paths, request/response
semantics, examples, and MCP documentation remain hand-authored.

## License

Barcode Hub is MIT licensed. `zxing-cpp` is Apache-2.0 licensed; keep upstream
notices when redistributing images or derived distributions.
