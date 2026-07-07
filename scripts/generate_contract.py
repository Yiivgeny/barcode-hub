#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DECODE_SCHEMA_PATH = ROOT / "spec" / "decode-result.schema.json"
OPENAPI_PATH = ROOT / "spec" / "openapi.yaml"
GENERATED_START = "    # BEGIN GENERATED DECODE SCHEMAS\n"
GENERATED_END = "    # END GENERATED DECODE SCHEMAS\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated contracts differ")
    args = parser.parse_args()

    decode_schema = generate_decode_result_schema()
    openapi_text = generate_openapi_text(openapi_schemas_from_decode_schema(decode_schema))

    expected_decode_schema = json.dumps(decode_schema, ensure_ascii=False, indent=2) + "\n"
    current_decode_schema = DECODE_SCHEMA_PATH.read_text(encoding="utf-8")
    current_openapi = OPENAPI_PATH.read_text(encoding="utf-8")

    changed = {
        str(DECODE_SCHEMA_PATH): current_decode_schema != expected_decode_schema,
        str(OPENAPI_PATH): current_openapi != openapi_text,
    }

    if args.check:
        dirty = [path for path, is_changed in changed.items() if is_changed]
        if dirty:
            print("Generated contract files are out of date:", file=sys.stderr)
            for path in dirty:
                print(f"  {path}", file=sys.stderr)
            print("Run: python scripts/generate_contract.py", file=sys.stderr)
            return 1
        return 0

    if changed[str(DECODE_SCHEMA_PATH)]:
        DECODE_SCHEMA_PATH.write_text(expected_decode_schema, encoding="utf-8")
    if changed[str(OPENAPI_PATH)]:
        OPENAPI_PATH.write_text(openapi_text, encoding="utf-8")
    return 0


def generate_decode_result_schema() -> dict[str, Any]:
    from barcode_hub.models import DecodeResult

    pydantic_schema = DecodeResult.model_json_schema(ref_template="#/$defs/{model}")
    pydantic_schema = strip_titles(pydantic_schema)
    pydantic_schema["title"] = "Barcode Hub Decode Result"
    defs = pydantic_schema.setdefault("$defs", {})
    defs["BarcodeType"]["description"] = "Canonical ZXing-C++ barcode format ID emitted by Barcode Hub."
    defs["BarcodeValidity"][
        "description"
    ] = "Decoder validity mapped from ZXing-C++: true=yes, false=no, absent=unknown."

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://barcode-hub.local/schemas/decode-result.schema.json",
        **pydantic_schema,
    }


def openapi_schemas_from_decode_schema(decode_schema: dict[str, Any]) -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    decode_result = {
        key: value for key, value in decode_schema.items() if key not in {"$schema", "$id", "$defs"}
    }
    decode_result["title"] = "DecodeResult"
    schemas["DecodeResult"] = convert_refs(decode_result)
    for key, value in decode_schema["$defs"].items():
        schemas[key] = convert_refs(value)
    return schemas


def generate_openapi_text(generated_schemas: dict[str, Any]) -> str:
    current = OPENAPI_PATH.read_text(encoding="utf-8")
    if GENERATED_START not in current or GENERATED_END not in current:
        raise RuntimeError("OpenAPI generated schema markers are missing")
    before, rest = current.split(GENERATED_START, 1)
    _, after = rest.split(GENERATED_END, 1)
    block = yaml.safe_dump(generated_schemas, sort_keys=False, allow_unicode=True, width=1000)
    indented_block = "".join(f"    {line}" if line.strip() else line for line in block.splitlines(True))
    return before + GENERATED_START + indented_block + GENERATED_END + after


def strip_titles(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: strip_titles(item) for key, item in value.items() if key != "title"}
    if isinstance(value, list):
        return [strip_titles(item) for item in value]
    return value


def convert_refs(value: Any) -> Any:
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                converted[key] = item.replace("#/$defs/", "#/components/schemas/")
            else:
                converted[key] = convert_refs(item)
        return converted
    if isinstance(value, list):
        return [convert_refs(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
