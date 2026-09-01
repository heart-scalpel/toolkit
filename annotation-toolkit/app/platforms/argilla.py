"""Argilla adapter for annotation review profiles."""

from __future__ import annotations

import json
import re
import secrets
from types import SimpleNamespace
from typing import cast

import argilla as rg

from app.profiles import cozie_safety as profile

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


def _metadata_settings(client: rg.Argilla) -> list[rg.TermsMetadataProperty]:
    return [
        rg.TermsMetadataProperty(
            name=name,
            title=name,
            visible_for_annotators=name in profile.VISIBLE_METADATA,
            client=client,
        )
        for name in profile.METADATA_NAMES
    ]


def build_settings(mode: str, min_submitted: int, client: rg.Argilla) -> rg.Settings:
    """Build an immutable Argilla dataset schema for one review stage."""
    fields = [
        rg.TextField(
            name="user_input",
            title="用户输入 / User input",
            required=True,
            use_markdown=False,
            client=client,
        ),
        rg.TextField(
            name="review_context",
            title="审核上下文 / Review context",
            required=False,
            use_markdown=True,
            client=client,
        ),
    ]

    if mode == "blind":
        guidelines = """
# Cozie AI 安全分级盲审 / Blind safety review

请只根据用户输入、用户画像和历史消息独立判断。当前阶段不展示原标签、模型标签或模型理由。

1. 最终安全标签必须五选一。
2. 判断依据至少选择一项。
3. 边界不明确、信息不足、体系外、restricted_medical 或需要专家裁决时，填写医学逻辑。
4. 医学生只做安全分级和升级判断，不作最终临床裁决。
""".strip()
        questions = [
            rg.LabelQuestion(
                name="medical_review_label",
                title="最终安全标签 / Final safety label",
                description="选择当前 query 所需回复对应的最低不可降低安全边界。",
                labels=profile.SAFETY_LABELS,
                required=True,
                visible_labels=5,
                client=client,
            ),
            rg.LabelQuestion(
                name="boundary_status",
                title="边界状态 / Boundary status",
                labels=profile.BOUNDARY_LABELS,
                required=True,
                visible_labels=4,
                client=client,
            ),
            rg.MultiLabelQuestion(
                name="reason_codes",
                title="判断依据 / Reason codes",
                labels=profile.REASON_LABELS,
                required=True,
                visible_labels=8,
                client=client,
            ),
            rg.TextQuestion(
                name="medical_rationale",
                title="医学逻辑 / Medical rationale",
                description="简述医学或安全边界判断逻辑；边界不明确、restricted、信息不足、体系外或需升级时填写。",
                required=False,
                client=client,
            ),
            rg.LabelQuestion(
                name="needs_expert_adjudication",
                title="是否需要专家裁决 / Expert adjudication required",
                labels=profile.YES_NO_LABELS,
                required=True,
                client=client,
            ),
        ]
    elif mode == "comparison":
        fields.append(
            rg.TextField(
                name="candidate_labels",
                title="待比较标签 / Labels to compare",
                required=True,
                use_markdown=True,
                client=client,
            )
        )
        guidelines = """
# Cozie AI 标签对照复核 / Label comparison review

请在完成盲审后使用本数据集。根据同一套安全分级规则，判断原标签和模型标签哪个更合理。
不要因为某个标签来自黄金集或模型而默认其正确。
""".strip()
        questions = [
            rg.LabelQuestion(
                name="label_reasonableness",
                title="标签合理性 / Label reasonableness",
                labels=profile.REASONABLENESS_LABELS,
                required=True,
                visible_labels=5,
                client=client,
            ),
            rg.TextQuestion(
                name="medical_rationale",
                title="医学逻辑 / Medical rationale",
                description="简述标签合理性的医学或安全边界逻辑；两者都不合理、信息不足或需升级时填写。",
                required=False,
                client=client,
            ),
            rg.LabelQuestion(
                name="needs_expert_adjudication",
                title="是否需要专家裁决 / Expert adjudication required",
                labels=profile.YES_NO_LABELS,
                required=True,
                client=client,
            ),
        ]
    else:
        raise ValueError(f"unsupported mode: {mode}")

    return rg.Settings(
        guidelines=guidelines,
        fields=fields,
        questions=questions,
        metadata=_metadata_settings(client),
        distribution=rg.TaskDistribution(min_submitted=min_submitted),
    )


def build_records(rows: list[dict[str, str]], mode: str) -> list[rg.Record]:
    records: list[rg.Record] = []
    for row in rows:
        fields = {
            "user_input": row["user_input"],
            "review_context": profile.review_context(row),
        }
        if mode == "comparison":
            fields["candidate_labels"] = profile.comparison_context(row)

        records.append(
            rg.Record(
                id=row["case_id"].strip(),
                fields=fields,
                metadata=profile.record_metadata(row),
            )
        )
    return records


def create_dataset(
    *,
    client: rg.Argilla,
    workspace: str,
    dataset_name: str,
    settings: rg.Settings,
    records: list[rg.Record],
) -> rg.Dataset:
    workspace_resource = client.workspaces(workspace)
    if workspace_resource is None:
        raise ValueError(f"workspace {workspace!r} not found")
    if any(dataset.name == dataset_name for dataset in workspace_resource.datasets):
        raise ValueError(
            f"dataset {dataset_name!r} already exists in workspace {workspace!r}; "
            "use --dataset to choose a new name"
        )

    dataset = rg.Dataset(
        name=dataset_name,
        workspace=workspace,
        settings=settings,
        client=client,
    ).create()
    dataset.records.log(records)
    return dataset


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
        raise ValueError(
            "refusing to delete non-annotator users: " + ", ".join(protected)
        )
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
                "submitted": completed.get("submitted", 0)
                + pending.get("submitted", 0),
                "draft": completed.get("draft", 0) + pending.get("draft", 0),
                "discarded": completed.get("discarded", 0)
                + pending.get("discarded", 0),
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
                {
                    name: _export_cell(record.metadata.get(name, ""))
                    for name in metadata_names
                }
            )
            row.update(
                {name: _export_cell(record.fields.get(name, "")) for name in field_names}
            )
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
