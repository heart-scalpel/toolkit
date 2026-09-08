"""Argilla adapter for annotation review profiles."""

from __future__ import annotations

import json
import re
import secrets
from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import argilla as rg

from app.core import QuestionSpec, RecordSpec, TaskSpec

USERNAME_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


def offline_client() -> rg.Argilla:
    """Provide the SDK resource namespaces needed for schema-only validation."""
    api = SimpleNamespace(fields=None, questions=None, metadata=None)
    return cast(rg.Argilla, SimpleNamespace(api=api))


def resolve_workspace(client: rg.Argilla, requested: str) -> str:
    """Resolve a workspace name and safely fall back when the server has only one."""
    available = [workspace.name for workspace in client.workspaces]
    if requested in available:
        return requested
    if len(available) == 1:
        selected = available[0]
        print(f"Workspace {requested!r} not found; using the only workspace: {selected!r}")
        return selected
    choices = ", ".join(available) if available else "none"
    raise ValueError(f"workspace {requested!r} not found; available workspaces: {choices}")


def _metadata_settings(
    task: TaskSpec,
    client: rg.Argilla,
) -> list[rg.TermsMetadataProperty]:
    return [
        rg.TermsMetadataProperty(
            name=item.name,
            title=item.title,
            visible_for_annotators=item.visible_for_annotators,
            client=client,
        )
        for item in task.metadata
    ]


def _question(spec: QuestionSpec, client: rg.Argilla) -> rg.Question:
    common: dict[str, object] = {
        "name": spec.name,
        "title": spec.title,
        "required": spec.required,
        "client": client,
    }
    if spec.description is not None:
        common["description"] = spec.description
    if spec.kind == "text":
        return rg.TextQuestion(**common)

    common["labels"] = dict(spec.labels)
    if spec.visible_labels is not None:
        common["visible_labels"] = spec.visible_labels
    if spec.kind == "label":
        return rg.LabelQuestion(**common)
    if spec.kind == "multi_label":
        return rg.MultiLabelQuestion(**common)
    raise ValueError(f"unsupported question kind: {spec.kind}")


def build_settings(task: TaskSpec, min_submitted: int, client: rg.Argilla) -> rg.Settings:
    """Translate a platform-neutral task specification to Argilla settings."""
    fields = [
        rg.TextField(
            name=field.name,
            title=field.title,
            required=field.required,
            use_markdown=field.use_markdown,
            client=client,
        )
        for field in task.fields
    ]
    return rg.Settings(
        guidelines=task.guidelines,
        fields=fields,
        questions=[_question(question, client) for question in task.questions],
        metadata=_metadata_settings(task, client),
        distribution=rg.TaskDistribution(min_submitted=min_submitted),
    )


def build_records(specs: list[RecordSpec]) -> list[rg.Record]:
    """Translate platform-neutral records to Argilla records."""
    return [
        rg.Record(
            id=spec.id,
            fields=dict(spec.fields),
            metadata=dict(spec.metadata),
        )
        for spec in specs
    ]


def create_dataset(
    *,
    client: rg.Argilla,
    workspace: str,
    dataset_name: str,
    settings: rg.Settings,
    records: list[rg.Record],
) -> rg.Dataset:
    _ensure_dataset_does_not_exist(client, workspace, dataset_name)

    dataset = rg.Dataset(
        name=dataset_name,
        workspace=workspace,
        settings=settings,
        client=client,
    ).create()
    dataset.records.log(records)
    return dataset


def _ensure_dataset_does_not_exist(client: rg.Argilla, workspace: str, dataset_name: str) -> None:
    workspace_resource = client.workspaces(workspace)
    if workspace_resource is None:
        raise ValueError(f"workspace {workspace!r} not found")
    if any(dataset.name == dataset_name for dataset in workspace_resource.datasets):
        raise ValueError(
            f"dataset {dataset_name!r} already exists in workspace {workspace!r}; "
            "use --dataset to choose a new name"
        )


def get_dataset(client: rg.Argilla, workspace: str, dataset_name: str) -> rg.Dataset:
    """Return one exact-name dataset without accepting patterns or partial matches."""
    workspace_resource = client.workspaces(workspace)
    if workspace_resource is None:
        raise ValueError(f"workspace {workspace!r} not found")

    for dataset in workspace_resource.datasets:
        if dataset.name == dataset_name:
            return dataset

    available = ", ".join(sorted(dataset.name for dataset in workspace_resource.datasets))
    choices = available or "none"
    raise ValueError(
        f"dataset {dataset_name!r} not found in workspace {workspace!r}; "
        f"available datasets: {choices}"
    )


def _settings_content(settings: rg.Settings) -> dict:
    """Keep the complete saved schema without server-owned identities or timestamps."""
    content = deepcopy(settings.serialize())
    for collection in ("fields", "questions", "metadata", "vectors"):
        for item in content[collection]:
            for key in ("id", "dataset_id", "inserted_at", "updated_at"):
                item.pop(key, None)
    return content


def _record_content(record: rg.Record) -> dict:
    """Copy task inputs, excluding feedback, status and the server's record ID."""
    return deepcopy(
        {
            "id": record.id,
            "fields": record.fields.to_dict(),
            "metadata": record.metadata.to_dict(),
            "vectors": record.vectors.to_dict(),
        }
    )


def clone_dataset(
    *,
    client: rg.Argilla,
    workspace: str,
    source_name: str,
    dataset_name: str,
    min_submitted: int,
    dry_run: bool = False,
) -> dict[str, object]:
    """Clone the saved task without feedback; a dry run only reads the platform."""
    if not dataset_name.strip() or dataset_name == source_name:
        raise ValueError("clone destination must be a new, non-empty dataset name")
    if min_submitted < 1:
        raise ValueError("--min-submitted must be at least 1")
    _ensure_dataset_does_not_exist(client, workspace, dataset_name)
    source = get_dataset(client, workspace, source_name)
    source.settings.get()
    settings_content = _settings_content(source.settings)
    settings_content["distribution"] = rg.TaskDistribution(min_submitted=min_submitted).to_dict()
    # Argilla 2.8 uses this same constructor for Settings.from_json and Dataset's copy.
    settings = rg.Settings._from_dict(deepcopy(settings_content))
    contents = [
        _record_content(record)
        for record in source.records(
            with_responses=False, with_suggestions=False, with_vectors=True
        )
    ]
    if not contents:
        raise ValueError(f"source dataset {source_name!r} has no records to clone")
    record_ids = [content["id"] for content in contents]
    if any(not record_id for record_id in record_ids) or len(set(record_ids)) != len(record_ids):
        raise ValueError("source dataset contains empty or duplicate record IDs")
    records = [rg.Record(**content) for content in contents]
    summary = {
        "source_dataset": source_name,
        "dataset": dataset_name,
        "workspace": workspace,
        "records": len(records),
        "record_ids": record_ids,
        "questions": [question.name for question in settings.questions],
        "min_submitted": min_submitted,
        "responses_copied": False,
        "suggestions_copied": False,
        "dry_run": dry_run,
        "created": False,
        "verified": False,
    }
    if dry_run:
        return summary

    target = create_dataset(
        client=client,
        workspace=workspace,
        dataset_name=dataset_name,
        settings=settings,
        records=records,
    )
    target.settings.get()
    copied = list(target.records(with_responses=True, with_suggestions=True, with_vectors=True))
    expected_by_id = {content["id"]: content for content in contents}
    if (
        _settings_content(target.settings) != settings_content
        or len(copied) != len(contents)
        or {record.id: _record_content(record) for record in copied} != expected_by_id
        or any(
            record.responses.to_dict() or record.suggestions.to_dict() or record.status != "pending"
            for record in copied
        )
    ):
        raise ValueError(
            f"clone verification failed for {dataset_name!r}; "
            "the new dataset was created and needs inspection before annotation"
        )
    return summary | {"created": True, "verified": True}


def delete_dataset(client: rg.Argilla, workspace: str, dataset_name: str) -> None:
    """Delete one dataset selected by its exact name."""
    dataset = get_dataset(client, workspace, dataset_name)
    dataset.delete()


def batch_usernames(prefix: str, count: int) -> list[str]:
    """Build stable reviewer usernames for one account batch."""
    if not USERNAME_PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError(
            "--user-prefix must start with a lowercase letter and contain only "
            "lowercase letters, numbers, underscores, or hyphens"
        )
    if count < 1 or count > 100:
        raise ValueError("--create-users must be between 1 and 100")
    width = max(2, len(str(count)))
    return [f"{prefix}_{index:0{width}d}" for index in range(1, count + 1)]


def generate_password() -> str:
    """Generate an Argilla-compatible random initial password."""
    return secrets.token_urlsafe(18)


def create_annotator(
    client: rg.Argilla,
    workspace: str,
    username: str,
    password: str,
) -> rg.User:
    """Create one annotator and grant access to the requested workspace."""
    workspace_resource = client.workspaces(workspace)
    if workspace_resource is None:
        raise ValueError(f"workspace {workspace!r} not found")
    if username in {user.username for user in client.users}:
        raise ValueError(f"user {username!r} already exists")

    user = rg.User(
        username=username,
        password=password,
        role="annotator",
        client=client,
    ).create()
    user.add_to_workspace(workspace_resource)
    return user


def ensure_users_do_not_exist(client: rg.Argilla, usernames: list[str]) -> None:
    """Fail the whole batch before creation when any requested username exists."""
    server_usernames = {user.username for user in client.users}
    existing = [username for username in usernames if username in server_usernames]
    if existing:
        names = ", ".join(existing)
        raise ValueError(f"refusing to overwrite existing users: {names}")


def resolve_deletable_annotators(
    client: rg.Argilla,
    usernames: list[str],
) -> list[rg.User]:
    """Resolve exact users and protect owner/admin accounts from deletion."""
    server_users = {user.username: user for user in client.users}
    missing = [username for username in usernames if username not in server_users]
    if missing:
        raise ValueError(f"users not found: {', '.join(missing)}")

    users = [server_users[username] for username in usernames]
    protected = [
        user.username
        for user in users
        if getattr(user.role, "value", str(user.role)) != "annotator"
    ]
    if protected:
        raise ValueError("refusing to delete non-annotator users: " + ", ".join(protected))
    if client.me.username in usernames:
        raise ValueError("refusing to delete the currently connected user")
    return users


def delete_annotators(users: list[rg.User]) -> None:
    """Delete a previously resolved exact list of annotator users."""
    for user in users:
        user.delete()


def remove_annotator_from_workspace(
    client: rg.Argilla,
    workspace: str,
    username: str,
) -> None:
    """Revoke workspace access without deleting the Argilla account."""
    users = resolve_deletable_annotators(client, [username])
    workspace_resource = client.workspaces(workspace)
    if workspace_resource is None:
        raise ValueError(f"workspace {workspace!r} not found")
    workspace_usernames = {user.username for user in workspace_resource.users}
    if username not in workspace_usernames:
        raise ValueError(f"user {username!r} is not in workspace {workspace!r}")
    workspace_resource.remove_user(users[0])


def dataset_user_progress(
    client: rg.Argilla,
    workspace: str,
    dataset_name: str,
) -> dict[str, object]:
    """Return compact per-user response totals for one dataset."""
    dataset = get_dataset(client, workspace, dataset_name)
    raw = dataset.progress(with_users_distribution=True)
    users = []
    for username, states in sorted(raw.get("users", {}).items()):
        completed = states.get("completed", {})
        pending = states.get("pending", {})
        users.append(
            {
                "username": username,
                "submitted": completed.get("submitted", 0) + pending.get("submitted", 0),
                "draft": completed.get("draft", 0) + pending.get("draft", 0),
                "discarded": completed.get("discarded", 0) + pending.get("discarded", 0),
            }
        )
    return {
        "dataset": dataset_name,
        "workspace": workspace,
        "total": raw.get("total", 0),
        "completed": raw.get("completed", 0),
        "pending": raw.get("pending", 0),
        "users": users,
    }


def _export_cell(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return ""
    return value


def submitted_response_rows(
    client: rg.Argilla,
    workspace: str,
    dataset_name: str,
) -> tuple[list[str], list[dict[str, object]]]:
    """Flatten submitted Argilla responses to one row per record and annotator."""
    dataset = get_dataset(client, workspace, dataset_name)
    records = list(dataset.records)
    if not records:
        return ["record_id", "annotator_username", "annotator_user_id", "response_status"], []

    field_names: list[str] = []
    metadata_names: list[str] = []
    question_names: list[str] = []
    for record in records:
        for name in record.fields:
            if name not in field_names:
                field_names.append(name)
        for name in record.metadata:
            if name not in metadata_names:
                metadata_names.append(name)
        for name in record.responses.to_dict():
            if name not in question_names:
                question_names.append(name)

    users_by_id = {str(user.id): user.username for user in client.users}
    rows: list[dict[str, object]] = []
    for record in records:
        responses_by_user: dict[str, dict[str, object]] = {}
        for question_name in question_names:
            for response in record.responses[question_name]:
                status = getattr(response.status, "value", str(response.status))
                if status != "submitted":
                    continue
                user_id = str(response.user_id)
                responses_by_user.setdefault(user_id, {})[question_name] = _export_cell(
                    response.value
                )

        for user_id, answers in responses_by_user.items():
            row: dict[str, object] = {"record_id": str(record.id)}
            row.update(
                {name: _export_cell(record.metadata.get(name, "")) for name in metadata_names}
            )
            row.update({name: _export_cell(record.fields.get(name, "")) for name in field_names})
            row.update(
                {
                    "annotator_username": users_by_id.get(user_id, "unknown"),
                    "annotator_user_id": user_id,
                    "response_status": "submitted",
                }
            )
            row.update({name: answers.get(name, "") for name in question_names})
            rows.append(row)

    columns = [
        "record_id",
        *metadata_names,
        *field_names,
        "annotator_username",
        "annotator_user_id",
        "response_status",
        *question_names,
    ]
    return columns, rows
