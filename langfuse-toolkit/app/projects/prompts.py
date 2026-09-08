"""Prompt maintenance in a verified project."""

from urllib.parse import quote

from app.core.errors import ApiError
from app.core.validation import positive_version, string_list, validate_name
from app.projects.prompt_definitions import version_payload


class PromptService:
    def __init__(self, client):
        self.client = client

    def list_prompts(self, *, name=None, label=None, tag=None) -> list[dict]:
        self.client.check()
        filters = {
            key: value
            for key, value in {"name": name, "label": label, "tag": tag}.items()
            if value is not None
        }
        page, collected, seen = 1, [], set()
        while True:
            result = self.client.request(
                "GET", "/api/public/v2/prompts", params={**filters, "page": page, "limit": 100}
            )
            batch = result["data"]
            for prompt in batch:
                if prompt["name"] in seen:
                    raise RuntimeError("Pagination repeated a prompt; retry with a stable project")
                seen.add(prompt["name"])
                collected.append(prompt)
            meta = result.get("meta", {})
            total_pages = meta.get("totalPages")
            if (total_pages is not None and page >= total_pages) or (
                total_pages is None and len(batch) < 100
            ):
                if meta.get("totalItems") is not None and len(collected) != meta["totalItems"]:
                    raise RuntimeError("Prompt count changed during pagination; retry listing")
                return collected
            if not batch:
                raise RuntimeError("Empty page before the end of the prompt list")
            page += 1

    def get_prompt(self, name: str, *, version=None, label=None, resolve=False) -> dict:
        validate_name(name)
        if version is not None and label is not None:
            raise ValueError("Choose a version or a label, not both")
        self.client.check()
        params = {"resolve": "true" if resolve else "false"}
        if version is not None:
            params["version"] = positive_version(version)
        else:
            params["label"] = label or "latest"
        result = self.client.request(
            "GET", f"/api/public/v2/prompts/{quote(name, safe='')}", params=params
        )
        if result.get("name") != name or (version is not None and result.get("version") != version):
            raise RuntimeError("Server returned a different prompt name or version")
        return result

    def prepare_save(self, definition: dict) -> tuple[dict, dict | None]:
        self.client.check()
        try:
            current = self.get_prompt(definition["name"])
        except ApiError as error:
            if error.status != 404:
                raise
            # A broken/missing endpoint must not be mistaken for a new prompt.
            if any(
                item["name"] == definition["name"]
                for item in self.list_prompts(name=definition["name"])
            ):
                raise RuntimeError(
                    "Prompt exists but latest could not be read; save stopped"
                ) from error
            current = None
        return version_payload(definition, current), current

    def create_version(self, payload: dict) -> dict:
        self.client.check()
        result = self.client.request("POST", "/api/public/v2/prompts", body=payload)
        if result.get("name") != payload["name"]:
            raise RuntimeError("Write returned an unexpected prompt; inspect before retrying")
        try:
            saved = self.get_prompt(payload["name"], version=result["version"])
        except (ApiError, RuntimeError, KeyError) as error:
            raise RuntimeError(
                "Version may have been created; read-back failed. Inspect before retrying"
            ) from error
        if (
            any(saved.get(field) != payload.get(field) for field in ("type", "prompt", "config"))
            or set(saved.get("tags", [])) != set(payload.get("tags", []))
            or not set(payload.get("labels", [])).issubset(saved.get("labels", []))
        ):
            raise RuntimeError("Version was created but read-back differs; inspect before retrying")
        return saved

    def assign_labels(self, name: str, version: int, labels: list[str]) -> dict:
        validate_name(name)
        positive_version(version)
        string_list(labels, "labels")
        if not labels:
            raise ValueError("Provide at least one label to assign")
        self.get_prompt(name, version=version)
        self.client.request(
            "PATCH",
            f"/api/public/v2/prompts/{quote(name, safe='')}/versions/{version}",
            body={"newLabels": labels},
        )
        for label in labels:
            saved = self.get_prompt(name, label=label)
            if saved["version"] != version:
                raise RuntimeError("Label update read-back differs; inspect before retrying")
        return self.get_prompt(name, version=version)

    def delete_version(self, name: str, version: int) -> None:
        validate_name(name)
        positive_version(version)
        self.get_prompt(name, version=version)
        self.client.request(
            "DELETE", f"/api/public/v2/prompts/{quote(name, safe='')}", params={"version": version}
        )
        try:
            self.get_prompt(name, version=version)
        except ApiError as error:
            if error.status == 404:
                return
            raise
        raise RuntimeError("Delete read-back still found the version; inspect the server")
