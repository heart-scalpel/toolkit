import csv
import json
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

    cases = load_safety_cases(source)
    assert [(case.user_input, case.expected_safety_class) for case in cases] == [
        ("hello", "non_health"),
        ("what is mastitis", "general_medical"),
    ]
    assert cases[0].model_input() == "hello"
    assert cases[0].source["case_id"] == "H001"


def test_load_safety_cases_allows_missing_expected_class(tmp_path: Path) -> None:
    source = tmp_path / "unlabeled.csv"
    source.write_text(
        "case_id,user_input,expected_safety_class\nBF001,first unlabeled question,\n",
        encoding="utf-8",
    )

    case = load_safety_cases(source)[0]
    assert case.expected_safety_class is None
    assert case.user_input == "first unlabeled question"


@pytest.mark.asyncio
async def test_profile_context_is_sent_without_leaking_draft_labels(tmp_path: Path) -> None:
    sources = [
        {
            "case_id": str(index),
            "user_input": "same question",
            "expected_safety_class": "",
            "user_profile": json.dumps({"goal": goal}),
            "candidate_safety_class": "restricted_medical",
            "initial_assessment": "draft is not input",
            "confirmed_assessment": "",
        }
        for index, goal in enumerate(("maintain", "reduce"))
    ]
    seen = []

    class FakeRunner:
        @staticmethod
        async def run(_agent: object, case_input: str) -> SimpleNamespace:
            seen.append(json.loads(case_input))
            return SimpleNamespace(
                final_output=SafetyClassification(
                    safety_class="personalized_health", reasoning="Uses the supplied goal."
                )
            )

    results = await run_safety_batch(
        object(),
        [SafetyCase(row["user_input"], None, source=row) for row in sources],
        runner=FakeRunner,
        concurrency=2,
    )
    assert seen == [
        {"query": "same question", "user_profile": {"goal": goal}}
        for goal in ("maintain", "reduce")
    ]
    output = tmp_path / "result.csv"
    write_safety_csv(output, results)
    with output.open(encoding="utf-8-sig", newline="") as handle:
        exported = list(csv.DictReader(handle))
    for original, result in zip(sources, exported, strict=True):
        assert {key: result[key] for key in original} == original
        assert result["matched"] == ""


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
