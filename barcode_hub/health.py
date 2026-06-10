from __future__ import annotations

import importlib.util
from typing import Any


def check_zxing_cpp() -> dict[str, Any]:
    spec = importlib.util.find_spec("zxingcpp")
    if spec is None:
        return {"ok": False, "error": "zxingcpp module is not importable"}
    try:
        import zxingcpp
    except Exception as exc:  # pragma: no cover - defensive health path
        return {"ok": False, "error": repr(exc)}
    missing = [
        name for name in ("read_barcodes", "BarcodeFormat", "barcode_format_from_str") if not hasattr(zxingcpp, name)
    ]
    if missing:
        return {"ok": False, "error": f"zxingcpp is missing: {', '.join(missing)}"}
    return {
        "ok": True,
        "module": str(spec.origin),
        "version": getattr(zxingcpp, "__version__", None),
    }


def health_payload() -> tuple[int, dict[str, Any]]:
    checks = {"zxing_cpp": check_zxing_cpp()}
    ok = all(item["ok"] for item in checks.values())
    return 200 if ok else 503, {"status": "ok" if ok else "fail", "checks": checks}

