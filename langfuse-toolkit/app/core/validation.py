"""Shared input validation, independent of credentials and CLI."""

import json
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError("Prompt name must be a nonempty exact name without surrounding whitespace")
    if any(character in name for character in "*?\r\n\x00"):
        raise ValueError("Prompt name cannot contain wildcards or control characters")
    return name


def string_list(value, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be an array of nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} contains duplicate values")
    if field == "labels" and "latest" in value:
        raise ValueError("The latest label is managed by Langfuse; use another label")
    return value


def positive_version(version: int) -> int:
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Version must be a positive integer")
    return version
