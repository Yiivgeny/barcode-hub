# Barcode Hub MCP Contract

Barcode Hub exposes MCP Streamable HTTP at `/mcp` when MCP support is enabled.
The transport is Streamable HTTP and should be configured as a stateless JSON
response server by implementation code.

## Tool: decode_url

```text
decode_url(url: string, types?: list[BarcodeType]) -> DecodeResult
```

`decode_url` decodes barcodes from an image URL. The `url` argument may be an
HTTP(S) URL, a `file:` URL if enabled by deployment policy, or a `data:` URL.
For `data:` URLs, base64 payloads are explicitly supported, for example:

```text
data:image/png;base64,iVBORw0KGgo=
```

`types` is an optional list of canonical Barcode Hub type IDs such as `EAN13`,
`UPCA`, and `QRCode`. Requested values must stay inside the runtime allowlist.

## Structured Output

The tool returns the same `DecodeResult` shape as the OpenAPI decode response.
The authoritative JSON Schema is `spec/decode-result.schema.json`.

The visible MCP text content SHOULD be a concise summary, for example:

```text
Decoded 1 barcode.
```

The MCP `structuredContent` MUST validate as `DecodeResult`.

<!-- structured-content-example:start -->
```json
{
  "barcodes": []
}
```
<!-- structured-content-example:end -->

For a non-empty result:

```json
{
  "barcodes": [
    {
      "text": "4607084351323",
      "data": "NDYwNzA4NDM1MTMyMw==",
      "type": "EAN13",
      "valid": "yes"
    }
  ]
}
```

## Errors

MCP failures are standard MCP tool errors, not the OpenAPI HTTP error schema.
The implementation should either raise the SDK-equivalent tool error or return
an MCP tool result with `isError=true`.

Domain error codes are stable and must be exposed in the error text or metadata:

- `invalid_url`
- `disallowed_type`
- `resource_timeout`
- `request_too_large`

Do not wrap MCP errors in the OpenAPI body shape:

```json
{
  "error": {
    "code": "resource_timeout",
    "message": "Resource download timed out.",
    "details": {}
  }
}
```
