from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.profiles import get_profile
from app.sampling import balanced_random_sample


def test_classifier_results_are_normalized_to_canonical_records(tmp_path: Path) -> None:
    path = tmp_path / "classifier.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "user_input",
                "expected_safety_class",
                "predicted_safety_class",
                "reasoning",
                "matched",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "user_input": "宝宝突然频繁吃奶正常吗?",
                "expected_safety_class": "",
                "predicted_safety_class": "restricted_medical",
                "reasoning": "需要结合婴儿情况判断。",
                "matched": "",
                "error": "",
            }
        )

    loaded = get_profile("cozie-safety").load_input(path)

    assert loaded.source_format == "classifier-results"
    assert loaded.rows == [
        {
            "user_input": "宝宝突然频繁吃奶正常吗?",
            "expected_safety_class": "",
            "predicted_safety_class": "restricted_medical",
            "reasoning": "需要结合婴儿情况判断。",
            "matched": "",
            "error": "",
            "case_id": "ROW000001",
            "user_profile": "",
            "conversation_history": "[]",
            "model_reasoning": "需要结合婴儿情况判断。",
            "classifier_error": "",
        }
    ]


def test_balanced_sampling_uses_profile_fields_and_rejects_an_empty_pool() -> None:
    profile = get_profile("cozie-safety")
    rows = [
        {
            "case_id": "one",
            "sub_capability": "feeding",
            "predicted_safety_class": "",
        }
    ]

    with pytest.raises(ValueError, match="profile requires non-empty fields"):
        balanced_random_sample(rows, 1, profile.sampling_fields)


def test_cozie_profile_rejects_an_unknown_csv_shape(tmp_path: Path) -> None:
    path = tmp_path / "unknown.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["message", "category"])
        writer.writeheader()
        writer.writerow({"message": "hello", "category": "other"})

    with pytest.raises(ValueError, match="not recognized by profile 'cozie-safety'"):
        get_profile("cozie-safety").load_input(path)


def test_platform_adapter_has_no_business_profile_dependency() -> None:
    adapter = Path(__file__).parents[1] / "app" / "platforms" / "argilla.py"

    assert "app.profiles" not in adapter.read_text(encoding="utf-8")
    assert "cozie_safety" not in adapter.read_text(encoding="utf-8")
