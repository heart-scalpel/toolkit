from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.cli import _balanced_random_sample, build_parser, run
from app.platforms.argilla import (
    batch_usernames,
    build_records,
    build_settings,
    dataset_user_progress,
    delete_dataset,
    offline_client,
    resolve_deletable_annotators,
    resolve_workspace,
    submitted_response_rows,
)
from app.profiles.cozie_safety import load_rows


def _write_csv(path: Path, count: int = 1) -> None:
    columns = [
        "case_id",
        "priority",
        "difficulty",
        "turn_type",
        "sub_capability",
        "user_profile",
        "conversation_history",
        "user_input",
        "expected_safety_class",
        "predicted_safety_class",
        "model_reasoning",
        "classifier_error",
        "conflict_pair",
        "boundary_precheck",
        "review_route",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index in range(1, count + 1):
            writer.writerow(
                {
                    "case_id": f"H{index:03d}",
                    "priority": "P1",
                    "difficulty": "基础",
                    "turn_type": "单轮",
                    "sub_capability": "一般健康",
                    "user_profile": '{"stage":"产后"}',
                    "conversation_history": "[]",
                    "user_input": f"你好 {index}",
                    "expected_safety_class": "non_health",
                    "predicted_safety_class": "general_health",
                    "model_reasoning": "用户询问的是不依赖个人情况的通用健康知识。",
                    "classifier_error": "",
                    "conflict_pair": "non_health → general_health",
                    "boundary_precheck": "边界不明确",
                    "review_route": "医学复核",
                }
            )


def test_review_dataset_shows_model_assessment_and_uses_multiselect(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    _write_csv(path)
    rows = load_rows(path)
    settings = build_settings("review", min_submitted=2, client=offline_client())
    records = build_records(rows, "review")

    assert [question.name for question in settings.questions] == [
        "medical_review_label",
        "boundary_status",
        "reason_codes",
        "medical_rationale",
        "needs_expert_adjudication",
    ]
    assert type(settings.questions[0]).__name__ == "MultiLabelQuestion"
    assert type(settings.questions[1]).__name__ == "LabelQuestion"
    assert settings.distribution.min_submitted == 2
    assert set(records[0].fields) == {
        "user_input",
        "review_context",
        "model_assessment",
    }
    assert "通用健康知识" in records[0].fields["model_assessment"]
    assert "用户询问的是不依赖个人情况的通用健康知识" in records[0].fields[
        "model_assessment"
    ]
    assert records[0].metadata["expected_safety_class"] == "non_health"


def test_comparison_dataset_shows_both_candidate_labels(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    _write_csv(path)
    rows = load_rows(path)
    records = build_records(rows, "comparison")

    comparison = records[0].fields["candidate_labels"]
    assert "non_health" in comparison
    assert "general_health" in comparison


def test_workspace_falls_back_when_server_has_only_one() -> None:
    client = SimpleNamespace(workspaces=[SimpleNamespace(name="default")])

    assert resolve_workspace(client, "argilla") == "default"


def test_delete_dataset_requires_an_exact_name() -> None:
    target = SimpleNamespace(name="target_dataset", delete=Mock())
    other = SimpleNamespace(name="other_dataset", delete=Mock())
    workspace = SimpleNamespace(datasets=[target, other])
    client = SimpleNamespace(workspaces=lambda name: workspace)

    delete_dataset(client, "default", "target_dataset")

    target.delete.assert_called_once_with()
    other.delete.assert_not_called()

    with pytest.raises(ValueError, match="not found"):
        delete_dataset(client, "default", "target")


def test_limit_rejects_zero() -> None:
    args = build_parser().parse_args(["--dry-run", "--limit", "0"])
    args.platform = "argilla"

    with pytest.raises(ValueError, match="--limit must be at least 1"):
        run(args)


def test_offset_rejects_negative_values() -> None:
    args = build_parser().parse_args(["--dry-run", "--offset", "-1"])
    args.platform = "argilla"

    with pytest.raises(ValueError, match="--offset must be at least 0"):
        run(args)


def test_offset_and_limit_select_a_csv_window(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "review.csv"
    _write_csv(path, count=5)
    selected_case_ids: list[str] = []

    def capture_records(rows: list[dict[str, str]], mode: str) -> list[object]:
        selected_case_ids.extend(row["case_id"] for row in rows)
        return build_records(rows, mode)

    monkeypatch.setattr("app.cli.argilla.build_records", capture_records)
    args = build_parser().parse_args(
        [
            "--dry-run",
            "--input",
            str(path),
            "--offset",
            "2",
            "--limit",
            "2",
        ]
    )
    args.platform = "argilla"

    assert run(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["source_records"] == 5
    assert summary["offset"] == 2
    assert summary["records"] == 2
    assert selected_case_ids == ["H003", "H004"]


def test_offset_rejects_an_empty_window(tmp_path: Path) -> None:
    path = tmp_path / "review.csv"
    _write_csv(path, count=2)
    args = build_parser().parse_args(["--dry-run", "--input", str(path), "--offset", "2"])
    args.platform = "argilla"

    with pytest.raises(ValueError, match="outside the input containing 2 CSV records"):
        run(args)


def test_random_requires_limit() -> None:
    args = build_parser().parse_args(["--dry-run", "--random"])
    args.platform = "argilla"

    with pytest.raises(ValueError, match="--random requires --limit"):
        run(args)


def test_balanced_random_sample_keeps_both_fields_unique_within_each_round() -> None:
    rows = [
        {
            "case_id": f"{sub_capability}-{safety_class}-{index}",
            "sub_capability": sub_capability,
            "predicted_safety_class": safety_class,
        }
        for sub_capability, safety_class in [
            ("feeding", "general_health"),
            ("feeding", "personalized_health"),
            ("storage", "general_health"),
            ("storage", "personalized_health"),
        ]
        for index in range(2)
    ]

    selected = _balanced_random_sample(rows, limit=5)

    assert len(selected) == 5
    for sample_round in (selected[:2], selected[2:4]):
        assert len({row["sub_capability"] for row in sample_round}) == 2
        assert len({row["predicted_safety_class"] for row in sample_round}) == 2
    assert len({row["case_id"] for row in selected}) == 5


def test_balanced_random_sample_starts_new_round_when_only_one_pair_remains() -> None:
    rows = [
        {
            "case_id": f"feeding-{index}",
            "sub_capability": "feeding",
            "predicted_safety_class": "personalized_health",
        }
        for index in range(4)
    ]
    rows.append(
        {
            "case_id": "storage-0",
            "sub_capability": "storage",
            "predicted_safety_class": "general_health",
        }
    )

    selected = _balanced_random_sample(rows, limit=5)

    assert len(selected) == 5
    assert "storage-0" in {row["case_id"] for row in selected}
    assert len({row["case_id"] for row in selected}) == 5


def test_balanced_random_sample_excludes_empty_sampling_fields() -> None:
    rows = [
        {
            "case_id": "valid-1",
            "sub_capability": "feeding",
            "predicted_safety_class": "personalized_health",
        },
        {
            "case_id": "empty-class",
            "sub_capability": "storage",
            "predicted_safety_class": "",
        },
        {
            "case_id": "empty-sub-capability",
            "sub_capability": "",
            "predicted_safety_class": "general_health",
        },
        {
            "case_id": "valid-2",
            "sub_capability": "storage",
            "predicted_safety_class": "general_health",
        },
    ]

    selected = _balanced_random_sample(rows, limit=4)

    assert {row["case_id"] for row in selected} == {"valid-1", "valid-2"}


def test_balanced_random_sample_spreads_dominant_values_across_all_rounds() -> None:
    rows = [
        {
            "case_id": f"dominant-{index}",
            "sub_capability": "dominant",
            "predicted_safety_class": "general_health",
        }
        for index in range(6)
    ]
    rows.extend(
        {
            "case_id": f"minor-{index}",
            "sub_capability": "minor-a" if index < 3 else "minor-b",
            "predicted_safety_class": "personalized_health",
        }
        for index in range(6)
    )

    selected = _balanced_random_sample(rows, limit=12)

    assert len(selected) == 12
    for previous, current in zip(selected, selected[1:], strict=False):
        assert previous["sub_capability"] != current["sub_capability"]
        assert previous["predicted_safety_class"] != current["predicted_safety_class"]


def test_random_sampling_starts_after_offset(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "review.csv"
    _write_csv(path, count=5)
    selected_case_ids: list[str] = []

    def capture_records(rows: list[dict[str, str]], mode: str) -> list[object]:
        selected_case_ids.extend(row["case_id"] for row in rows)
        return build_records(rows, mode)

    monkeypatch.setattr("app.cli.argilla.build_records", capture_records)
    args = build_parser().parse_args(
        [
            "--dry-run",
            "--input",
            str(path),
            "--offset",
            "2",
            "--limit",
            "2",
            "--random",
        ]
    )
    args.platform = "argilla"

    assert run(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["sampling"] == "balanced_random"
    assert summary["records"] == 2
    assert set(selected_case_ids) <= {"H003", "H004", "H005"}


def test_batch_usernames_are_stable_and_validated() -> None:
    assert batch_usernames("medical_reviewer", 3) == [
        "medical_reviewer_01",
        "medical_reviewer_02",
        "medical_reviewer_03",
    ]
    with pytest.raises(ValueError, match="--user-prefix"):
        batch_usernames("Medical Reviewer", 3)


def test_dataset_user_progress_combines_completed_and_pending_counts() -> None:
    dataset = SimpleNamespace(
        name="review",
        progress=Mock(
            return_value={
                "total": 5,
                "completed": 1,
                "pending": 4,
                "users": {
                    "doctor": {
                        "completed": {"submitted": 1, "draft": 0, "discarded": 0},
                        "pending": {"submitted": 4, "draft": 1, "discarded": 0},
                    }
                },
            }
        ),
    )
    workspace = SimpleNamespace(datasets=[dataset])
    client = SimpleNamespace(workspaces=lambda name: workspace)

    progress = dataset_user_progress(client, "default", "review")

    assert progress["users"] == [{"username": "doctor", "submitted": 5, "draft": 1, "discarded": 0}]


def test_user_deletion_only_resolves_exact_annotators() -> None:
    annotator = SimpleNamespace(username="doctor", role=SimpleNamespace(value="annotator"))
    owner = SimpleNamespace(username="argilla", role=SimpleNamespace(value="owner"))
    client = SimpleNamespace(users=[annotator, owner], me=owner)

    assert resolve_deletable_annotators(client, ["doctor"]) == [annotator]
    with pytest.raises(ValueError, match="non-annotator"):
        resolve_deletable_annotators(client, ["argilla"])
    with pytest.raises(ValueError, match="not found"):
        resolve_deletable_annotators(client, ["missing"])


def test_submitted_response_export_is_one_row_per_annotator() -> None:
    class Responses:
        def __init__(self) -> None:
            submitted = SimpleNamespace(
                value=["GENERAL_INFO"],
                user_id="user-1",
                status=SimpleNamespace(value="submitted"),
            )
            draft = SimpleNamespace(
                value=["TAXONOMY_GAP"],
                user_id="user-2",
                status=SimpleNamespace(value="draft"),
            )
            self.values = {"reason_codes": [submitted, draft]}

        def to_dict(self) -> dict[str, list[object]]:
            return self.values

        def __getitem__(self, name: str) -> list[object]:
            return self.values[name]

    record = SimpleNamespace(
        id="record-1",
        fields={"user_input": "你好"},
        metadata={"case_id": "H001"},
        responses=Responses(),
    )
    dataset = SimpleNamespace(name="review", records=[record])
    workspace = SimpleNamespace(datasets=[dataset])
    client = SimpleNamespace(
        workspaces=lambda name: workspace,
        users=[SimpleNamespace(id="user-1", username="doctor")],
    )

    columns, rows = submitted_response_rows(client, "default", "review")

    assert "annotator_username" in columns
    assert rows == [
        {
            "record_id": "record-1",
            "case_id": "H001",
            "user_input": "你好",
            "annotator_username": "doctor",
            "annotator_user_id": "user-1",
            "response_status": "submitted",
            "reason_codes": '["GENERAL_INFO"]',
        }
    ]
