"""Local Prompt definitions and version payloads."""

from copy import deepcopy
from pathlib import Path

from app.core.validation import read_json, string_list, validate_name


def load_definition(path: Path) -> dict:
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Prompt definition must be a JSON object")
    unknown = set(data) - {
        "name",
        "type",
        "prompt",
        "promptFile",
        "config",
        "configFile",
        "labels",
        "tags",
        "commitMessage",
    }
    if unknown:
        raise ValueError(f"Unknown definition fields: {', '.join(sorted(unknown))}")
    validate_name(data.get("name"))
    if data.get("type") not in ("text", "chat"):
        raise ValueError("Prompt type must be text or chat")
    if ("prompt" in data) == ("promptFile" in data):
        raise ValueError("Provide exactly one of prompt or promptFile")
    if "promptFile" in data:
        if data["type"] != "text":
            raise ValueError("promptFile is only for text prompts; use chat contentFile instead")
        data["prompt"] = (path.parent / data.pop("promptFile")).read_text(encoding="utf-8")
    if data["type"] == "text":
        if not isinstance(data["prompt"], str) or not data["prompt"].strip():
            raise ValueError("Text prompt must be a nonempty string")
    else:
        if not isinstance(data["prompt"], list) or not data["prompt"]:
            raise ValueError("Chat prompt must be a nonempty array of messages")
        for message in data["prompt"]:
            if not isinstance(message, dict):
                raise ValueError("Each chat message must be an object")
            if message.get("type") == "placeholder":
                if set(message) != {"type", "name"} or not isinstance(message["name"], str):
                    raise ValueError("A placeholder requires only type and name")
                if not message["name"].strip():
                    raise ValueError("A placeholder name must not be empty")
                continue
            if set(message) - {"type", "role", "content", "contentFile"}:
                raise ValueError("Unsupported chat message field")
            if message.get("type", "chatmessage") != "chatmessage":
                raise ValueError("Message type must be chatmessage or placeholder")
            if not isinstance(message.get("role"), str) or not message["role"].strip():
                raise ValueError("Each chat message requires a role")
            if ("content" in message) == ("contentFile" in message):
                raise ValueError("Provide exactly one of content or contentFile per chat message")
            if "contentFile" in message:
                message["content"] = (path.parent / message.pop("contentFile")).read_text(
                    encoding="utf-8"
                )
            if not isinstance(message["content"], str):
                raise ValueError("Chat message content must be a string")
    if "configFile" in data:
        if "config" in data:
            raise ValueError("Use either config or configFile, not both")
        data["config"] = read_json(path.parent / data.pop("configFile"))
    if "config" in data and not isinstance(data["config"], dict):
        raise ValueError("config must be a JSON object")
    for field in ("labels", "tags"):
        if field in data:
            string_list(data[field], field)
    if "commitMessage" in data and not isinstance(data["commitMessage"], str):
        raise ValueError("commitMessage must be a string")
    return data


def version_payload(definition: dict, current: dict | None) -> dict:
    """Preserve omitted config/tags while creating a new, explicitly labeled version."""
    if current and definition["type"] != current["type"]:
        raise ValueError("Existing prompt has a different type; use a new prompt name")
    result = deepcopy(definition)
    for field in ("config", "tags"):
        result.setdefault(
            field, deepcopy((current or {}).get(field, {} if field == "config" else []))
        )
    result.setdefault("labels", [])
    return result
