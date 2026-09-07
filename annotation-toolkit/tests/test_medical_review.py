from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.platforms.argilla import build_records, build_settings, offline_client
from app.profiles import get_profile


def write_source(path: Path, **changes: str) -> None:
    row = {
        "case_id": "S05-Q005",
        "user_input": "same question",
        "user_profile": '{"background":["reduce pumping"]}',
        "candidate_safety_class": "personalized_health",
        "initial_assessment": "Draft assessment",
        "possible_consultation_response": "Draft direction",
        "follow_ups": "[]",
        "predicted_safety_class": "restricted_medical",
        "reasoning": "Engine reason",
        "error": "",
        "expected_safety_class": "",
        "confirmed_assessment": "",
        "review_status": "",
        "pair_key": "S05-pair1",
        "changed_factor": "feeding goal",
        **changes,
    }
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def test_medical_review_preserves_drafts_and_separates_human_answers(tmp_path: Path) -> None:
    path = tmp_path / "cases.csv"
    write_source(path)
    profile = get_profile("cozie-medical-review")
    loaded = profile.load_input(path)
    settings = build_settings(profile.task_spec("review"), 2, offline_client())
    records = build_records([profile.record_spec(loaded.rows[0], "review")])
    assert settings.distribution.min_submitted == 2
    questions = {question.name: question for question in settings.questions}
    assert type(questions["expected_safety_class"]).__name__ == "LabelQuestion"
    assert "confirmed_assessment" not in questions
    assert set(questions) >= {
        "confirmed_consultation_response",
        "confirmed_follow_ups",
        "material_review",
    }
    assert "Draft assessment" in records[0].fields["candidate_materials"]
    assert "Engine reason" in records[0].fields["model_assessment"]
    assert "reduce pumping" in records[0].fields["user_profile"]
    assert "conversation_history" not in records[0].fields
    assert loaded.rows[0]["expected_safety_class"] == ""
    assert loaded.rows[0]["confirmed_assessment"] == ""
    assert loaded.rows[0]["review_status"] == ""
    assert not records[0].responses.to_dict()


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"follow_ups": '[{"question":"what"}]'}, "follow_ups"),
        ({"user_profile": "[]"}, "user_profile"),
        ({"predicted_safety_class": ""}, "engine prediction"),
        ({"error": "timeout"}, "engine run failed"),
    ],
)
def test_medical_review_rejects_incomplete_inputs(
    tmp_path: Path, changes: dict, message: str
) -> None:
    path = tmp_path / "cases.csv"
    write_source(path, **changes)
    with pytest.raises(ValueError, match=message):
        get_profile("cozie-medical-review").load_input(path)


def test_explicit_engine_failure_stays_reviewable_without_fabricated_prediction(
    tmp_path: Path,
) -> None:
    path = tmp_path / "failed.csv"
    write_source(path, predicted_safety_class="", reasoning="", error="cyber_policy")
    profile = get_profile("cozie-medical-review")
    loaded = profile.load_input(path)
    row = loaded.rows[0]
    record = profile.record_spec(row, "review")
    assert row["engine_status"] == "FAILED"
    assert row["predicted_safety_class"] == ""
    assert row["expected_safety_class"] == ""
    assert record.metadata["engine_status"] == "FAILED"
    assert "predicted_safety_class" not in record.metadata
    assert "未生成有效结果" in record.fields["model_assessment"]
    assert "本条模型调用失败" in record.fields["model_assessment"]
    assert "Draft assessment" in record.fields["candidate_materials"]
