from __future__ import annotations

import mimetypes
import fnmatch


def clean_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def is_allowed_image_content_type(content_type: str | None, allowed: list[str]) -> bool:
    clean = clean_content_type(content_type)
    if not clean.startswith("image/"):
        return False
    return any(fnmatch.fnmatchcase(clean, item.lower()) for item in allowed)


def guess_content_type(path: str) -> str | None:
    return mimetypes.guess_type(path)[0]
