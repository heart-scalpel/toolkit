from pathlib import Path
from types import SimpleNamespace

import pytest

from app.batch import Case, load_cases, run_batch


def test_load_cases_accepts_strings_and_objects(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text(
        '"hello"\n{"id":"math","input":"2+2","expected_contains":"4"}\n',
        encoding="utf-8",
    )

    assert load_cases(path) == [
        Case(id="1", input="hello"),
        Case(id="math", input="2+2", expected_contains="4"),
    ]


def test_load_cases_reports_line_number(tmp_path: Path) -> None:
    path = tmp_path / "cases.jsonl"
    path.write_text('{"id":"broken"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"cases\.jsonl:1"):
        load_cases(path)


def test_load_cases_accepts_golden_set_csv_with_title_row(tmp_path: Path) -> None:
    path = tmp_path / "golden.csv"
    path.write_text(
        "\ufeffGolden Test Set\n"
        "case_id,capability,user_input\n"
        "H001,health,first question\n"
        "H002,health,second question\n",
        encoding="utf-8",
    )

    assert load_cases(path) == [
        Case(id="H001", input="first question"),
        Case(id="H002", input="second question"),
    ]


@pytest.mark.asyncio
async def test_run_batch_preserves_order_and_checks_expected_text() -> None:
    class FakeRunner:
        @staticmethod
        async def run(_agent: object, case_input: str) -> SimpleNamespace:
            return SimpleNamespace(final_output=f"answer: {case_input}")

    results = await run_batch(
        object(),
        [
            Case(id="a", input="first"),
            Case(id="b", input="second", expected_contains="second"),
        ],
        runner=FakeRunner,
        concurrency=2,
    )

    assert [result.id for result in results] == ["a", "b"]
    assert results[0].passed is None
    assert results[1].passed is True


@pytest.mark.asyncio
async def test_run_batch_keeps_going_after_one_error() -> None:
    class FakeRunner:
        @staticmethod
        async def run(_agent: object, case_input: str) -> SimpleNamespace:
            if case_input == "bad":
                raise RuntimeError("boom")
            return SimpleNamespace(final_output="ok")

    results = await run_batch(
        object(),
        [Case(id="bad", input="bad"), Case(id="good", input="good")],
        runner=FakeRunner,
        concurrency=2,
    )

    assert results[0].error == "RuntimeError: boom"
    assert results[1].output == "ok"
