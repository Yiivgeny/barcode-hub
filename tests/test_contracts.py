import json
import re
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "decode-result.schema.json"
OPENAPI_PATH = ROOT / "spec" / "openapi.yaml"
MCP_PATH = ROOT / "spec" / "mcp.md"


class SchemaValidationError(AssertionError):
    pass


def load_decode_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def resolve_ref(root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise SchemaValidationError(f"unsupported external ref: {ref}")
    value = root
    for part in ref[2:].split("/"):
        value = value[part]
    return value


def validate(instance, schema, root=None, path="$"):
    root = root or schema
    if "$ref" in schema:
        return validate(instance, resolve_ref(root, schema["$ref"]), root, path)

    if "enum" in schema and instance not in schema["enum"]:
        raise SchemaValidationError(f"{path}: {instance!r} is not in enum")

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(instance, dict):
            raise SchemaValidationError(f"{path}: expected object")
        missing = set(schema.get("required", [])) - set(instance)
        if missing:
            raise SchemaValidationError(f"{path}: missing {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise SchemaValidationError(f"{path}: extra {sorted(extra)}")
        for key, value in instance.items():
            if key in properties:
                validate(value, properties[key], root, f"{path}.{key}")
    elif expected_type == "array":
        if not isinstance(instance, list):
            raise SchemaValidationError(f"{path}: expected array")
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(instance):
                validate(item, item_schema, root, f"{path}[{index}]")
    elif expected_type == "string":
        if not isinstance(instance, str):
            raise SchemaValidationError(f"{path}: expected string")
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(pattern, instance):
            raise SchemaValidationError(f"{path}: string does not match pattern")


def assert_valid_decode_result(testcase: unittest.TestCase, instance: dict) -> None:
    schema = load_decode_schema()
    try:
        import jsonschema
    except ModuleNotFoundError:
        validate(instance, schema)
    else:
        jsonschema.Draft202012Validator(schema).validate(instance)
    testcase.assertIsInstance(instance["barcodes"], list)


class DecodeResultSchemaTests(unittest.TestCase):
    def test_generated_contract_files_are_current(self):
        result = subprocess.run(
            [sys.executable, "scripts/generate_contract.py", "--check"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_success_result_is_valid(self):
        assert_valid_decode_result(self, {"barcodes": []})

    def test_one_ean13_result_is_valid(self):
        assert_valid_decode_result(
            self,
            {
                "barcodes": [
                    {
                        "text": "4607084351323",
                        "data": "NDYwNzA4NDM1MTMyMw==",
                        "type": "EAN13",
                        "valid": "yes",
                    }
                ]
            },
        )

    def test_unknown_validity_is_rejected(self):
        with self.assertRaises(Exception):
            assert_valid_decode_result(
                self,
                {
                    "barcodes": [
                        {
                            "text": "4607084351323",
                            "data": "NDYwNzA4NDM1MTMyMw==",
                            "type": "EAN13",
                            "valid": "maybe",
                        }
                    ]
                },
            )

    def test_unknown_barcode_type_is_rejected(self):
        with self.assertRaises(Exception):
            assert_valid_decode_result(
                self,
                {
                    "barcodes": [
                        {
                            "text": "4607084351323",
                            "data": "NDYwNzA4NDM1MTMyMw==",
                            "type": "EAN_13",
                            "valid": "yes",
                        }
                    ]
                },
            )

    def test_missing_barcodes_is_rejected(self):
        with self.assertRaises(Exception):
            assert_valid_decode_result(self, {})

    def test_pseudo_selector_types_are_not_public_response_types(self):
        enum = set(load_decode_schema()["$defs"]["BarcodeType"]["enum"])
        self.assertFalse({"None", "All", "AllReadable", "AllLinear", "EANUPC"} & enum)
        self.assertIn("EAN13", enum)
        self.assertIn("QRCode", enum)
        self.assertIn("DataMatrix", enum)


class OpenApiContractTests(unittest.TestCase):
    def test_openapi_documents_decode_methods_and_required_statuses(self):
        spec = OPENAPI_PATH.read_text(encoding="utf-8")
        for method in ("get", "post", "put"):
            self.assertIn(f"    {method}:", spec)
        for status in ("200", "400", "405", "413", "415", "422", "504", "500"):
            self.assertIn(f'"{status}":', spec)

    def test_openapi_documents_comma_separated_types_parameter(self):
        spec = OPENAPI_PATH.read_text(encoding="utf-8")
        self.assertIn("name: types", spec)
        self.assertIn("style: form", spec)
        self.assertIn("explode: false", spec)
        self.assertIn("`types=EAN13,UPCA`", spec)

    def test_openapi_does_not_document_server_header(self):
        spec = OPENAPI_PATH.read_text(encoding="utf-8")
        self.assertNotIn("Barcode-Hub", spec)
        self.assertNotIn("components:\n  headers:", spec)
        self.assertNotIn("$ref: \"#/components/headers/Server\"", spec)

    def test_openapi_component_enum_matches_json_schema_enum(self):
        schema_enum = set(load_decode_schema()["$defs"]["BarcodeType"]["enum"])
        spec = OPENAPI_PATH.read_text(encoding="utf-8")
        enum_block = spec.split("    BarcodeType:", 1)[1].split("    BarcodeValidity:", 1)[0]
        openapi_enum = {line.strip()[2:] for line in enum_block.splitlines() if line.strip().startswith("- ")}
        self.assertEqual(openapi_enum, schema_enum)

    def test_openapi_barcode_validity_enum_is_string_typed(self):
        try:
            import yaml
        except ModuleNotFoundError:
            self.skipTest("PyYAML is not installed")
        spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
        enum = spec["components"]["schemas"]["BarcodeValidity"]["enum"]
        self.assertEqual(enum, ["yes", "no", "unknown"])


class McpContractTests(unittest.TestCase):
    def test_mcp_structured_content_example_validates_against_decode_schema(self):
        doc = MCP_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"<!-- structured-content-example:start -->\n```json\n(?P<json>.*?)\n```\n<!-- structured-content-example:end -->",
            doc,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert_valid_decode_result(self, json.loads(match.group("json")))

    def test_mcp_documents_decode_url_tool_and_error_codes(self):
        doc = MCP_PATH.read_text(encoding="utf-8")
        self.assertIn("decode_url(url: string, types?: list[BarcodeType]) -> DecodeResult", doc)
        self.assertIn("structuredContent", doc)
        self.assertNotIn("Barcode-Hub", doc)
        self.assertNotIn("Server:", doc)
        for code in ("invalid_url", "disallowed_type", "resource_timeout", "request_too_large"):
            self.assertIn(code, doc)


if __name__ == "__main__":
    unittest.main()
