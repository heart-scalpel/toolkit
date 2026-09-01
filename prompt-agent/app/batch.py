"""Case loading and concurrent batch execution."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    input: str
    expected_contains: str | None = None


@dataclass(frozen=True, slots=True)
class CaseResult:
    id: str
    input: str
    output: str | None
    error: str | None
    expected_contains: str | None
    passed: bool | None
    latency_ms: int


def load_cases(path: Path) -> list[Case]:
    """Load JSONL cases, or CSV cases with user_input and case_id columns."""
    if path.suffix.lower() == ".csv":
        return _load_csv_cases(path)

    cases: list[Case] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc

        if isinstance(payload, str):
            cases.append(Case(id=str(line_number), input=payload))
            continue
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_number}: each case must be a string or object")

        case_input = payload.get("input")
        if not isinstance(case_input, str) or not case_input.strip():
            raise ValueError(f"{path}:{line_number}: 'input' must be a non-empty string")

        case_id = payload.get("id", line_number)
        expected = payload.get("expected_contains")
        if expected is not None and not isinstance(expected, str):
            raise ValueError(f"{path}:{line_number}: 'expected_contains' must be a string")
        cases.append(Case(id=str(case_id), input=case_input, expected_contains=expected))

    if not cases:
        raise ValueError(f"{path}: no cases found")
    return cases


def _load_csv_cases(path: Path) -> list[Case]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))

    header_index = next(
        (index for index, row in enumerate(rows) if "user_input" in row),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path}: CSV must contain a 'user_input' column")

    headers = rows[header_index]
    cases: list[Case] = []
    for line_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        record = dict(zip(headers, row, strict=False))
        case_input = record.get("user_input", "").strip()
        if not case_input:
            raise ValueError(f"{path}:{line_number}: 'user_input' must be non-empty")
        case_id = record.get("case_id", "").strip() or str(line_number)
        expected = record.get("expected_contains", "").strip() or None
        cases.append(Case(id=case_id, input=case_input, expected_contains=expected))

    if not cases:
        raise ValueError(f"{path}: no cases found")
    return cases


async def run_batch(
    agent: Any,
    cases: Sequence[Case],
    *,
    runner: Any,
    concurrency: int,
) -> list[CaseResult]:
    """Run independent cases concurrently while preserving input order."""
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    semaphore = asyncio.Semaphore(concurrency)

    async def run_one(case: Case) -> CaseResult:
        started = perf_counter()
        try:
            async with semaphore:
                result = await runner.run(agent, case.input)
            output = str(result.final_output)
            passed = None if case.expected_contains is None else case.expected_contains in output
            return CaseResult(
                id=case.id,
                input=case.input,
                output=output,
                error=None,
                expected_contains=case.expected_contains,
                passed=passed,
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return CaseResult(
                id=case.id,
                input=case.input,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
                expected_contains=case.expected_contains,
                passed=False if case.expected_contains is not None else None,
                latency_ms=round((perf_counter() - started) * 1000),
            )

    return list(await asyncio.gather(*(run_one(case) for case in cases)))


def write_results(path: Path, results: Sequence[CaseResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(asdict(result), ensure_ascii=False) for result in results)
    path.write_text(f"{content}\n", encoding="utf-8")
