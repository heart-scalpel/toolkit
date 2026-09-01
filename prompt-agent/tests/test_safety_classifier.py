import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.safety_classifier import (
    SafetyCase,
    SafetyClassification,
    SafetyResult,
    load_safety_cases,
    run_safety_batch,
    write_safety_csv,
)


def test_load_safety_cases_extracts_only_requested_columns(tmp_path: Path) -> None:
    source = tmp_path / "golden.csv"
    source.write_text(
        "\ufeffGolden Set\n"
        "case_id,user_input,expected_safety_class,notes\n"
        "H001,hello,non_health,ignored\n"
        "H002,what is mastitis,general_medical,ignored\n",
        encoding="utf-8",
    )

    assert load_safety_cases(source) == [
        SafetyCase(user_input="hello", expected_safety_class="non_health"),
        SafetyCase(
            user_input="what is mastitis",
            expected_safety_class="general_medical",
        ),
    ]


def test_load_safety_cases_allows_missing_expected_class(tmp_path: Path) -> None:
    source = tmp_path / "unlabeled.csv"
    source.write_text(
        "case_id,user_input,expected_safety_class\n"
        "BF001,first unlabeled question,\n",
        encoding="utf-8",
    )

    assert load_safety_cases(source) == [
        SafetyCase(user_input="first unlabeled question", expected_safety_class=None)
    ]


@pytest.mark.asyncio
async def test_run_safety_batch_returns_structured_comparison() -> None:
    class FakeRunner:
        @staticmethod
        async def run(_agent: object, _case_input: str) -> SimpleNamespace:
            return SimpleNamespace(
                final_output=SafetyClassification(
                    safety_class="non_health",
                    reasoning="Not a health request.",
                )
            )

    results = await run_safety_batch(
        object(),
        [SafetyCase(user_input="hello", expected_safety_class="non_health")],
        runner=FakeRunner,
        concurrency=1,
    )

    assert results[0].predicted_safety_class == "non_health"
    assert results[0].matched is True


@pytest.mark.asyncio
async def test_run_safety_batch_leaves_match_blank_without_expected_class() -> None:
    class FakeRunner:
        @staticmethod
        async def run(_agent: object, _case_input: str) -> SimpleNamespace:
            return SimpleNamespace(
                final_output=SafetyClassification(
                    safety_class="general_health",
                    reasoning="General health information.",
                )
            )

    results = await run_safety_batch(
        object(),
        [SafetyCase(user_input="question", expected_safety_class=None)],
        runner=FakeRunner,
        concurrency=1,
    )

    assert results[0].predicted_safety_class == "general_health"
    assert results[0].matched is None


def test_write_safety_csv_uses_expected_columns(tmp_path: Path) -> None:
    output = tmp_path / "results.csv"
    write_safety_csv(
        output,
        [
            SafetyResult(
                user_input="hello",
                expected_safety_class="non_health",
                predicted_safety_class="non_health",
                reasoning="Not a health request.",
                matched=True,
                error=None,
            )
        ],
    )

    with output.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    assert list(rows[0]) == [
        "user_input",
        "expected_safety_class",
        "predicted_safety_class",
        "reasoning",
        "matched",
        "error",
    ]
