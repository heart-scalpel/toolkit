"""Safety-classifier batch input, execution, and CSV output."""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel

SafetyClass = Literal[
    "non_health",
    "general_health",
    "personalized_health",
    "general_medical",
    "restricted_medical",
]


class SafetyClassification(BaseModel):
    safety_class: SafetyClass
    reasoning: str


@dataclass(frozen=True, slots=True)
class SafetyCase:
    user_input: str
    expected_safety_class: str | None


@dataclass(frozen=True, slots=True)
class SafetyResult:
    user_input: str
    expected_safety_class: str | None
    predicted_safety_class: str | None
    reasoning: str | None
    matched: bool | None
    error: str | None


def load_safety_cases(path: Path) -> list[SafetyCase]:
    """Extract user_input and an optional expected_safety_class from a CSV."""
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source))

    required = {"user_input"}
    header_index = next(
        (index for index, row in enumerate(rows) if required.issubset(row)),
        None,
    )
    if header_index is None:
        raise ValueError(f"{path}: CSV must contain a 'user_input' column")

    headers = rows[header_index]
    cases: list[SafetyCase] = []
    for line_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        record = dict(zip(headers, row, strict=False))
        user_input = record.get("user_input", "").strip()
        expected = record.get("expected_safety_class", "").strip() or None
        if not user_input:
            raise ValueError(f"{path}:{line_number}: 'user_input' must be non-empty")
        cases.append(SafetyCase(user_input=user_input, expected_safety_class=expected))

    if not cases:
        raise ValueError(f"{path}: no cases found")
    return cases


async def run_safety_batch(
    agent: Any,
    cases: Sequence[SafetyCase],
    *,
    runner: Any,
    concurrency: int,
) -> list[SafetyResult]:
    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")

    semaphore = asyncio.Semaphore(concurrency)
    completed = 0
    progress_lock = asyncio.Lock()

    async def run_one(case: SafetyCase) -> SafetyResult:
        nonlocal completed
        started = perf_counter()
        try:
            async with semaphore:
                run_result = await runner.run(agent, case.user_input)
            classification = SafetyClassification.model_validate(run_result.final_output)
            result = SafetyResult(
                user_input=case.user_input,
                expected_safety_class=case.expected_safety_class,
                predicted_safety_class=classification.safety_class,
                reasoning=classification.reasoning,
                matched=(
                    None
                    if case.expected_safety_class is None
                    else classification.safety_class == case.expected_safety_class
                ),
                error=None,
            )
        except Exception as exc:
            result = SafetyResult(
                user_input=case.user_input,
                expected_safety_class=case.expected_safety_class,
                predicted_safety_class=None,
                reasoning=None,
                matched=None,
                error=f"{type(exc).__name__}: {exc}",
            )

        async with progress_lock:
            completed += 1
            elapsed_ms = round((perf_counter() - started) * 1000)
            status = "ERROR" if result.error else "OK"
            print(f"[{completed}/{len(cases)}] {status} {elapsed_ms}ms", flush=True)
        return result

    return list(await asyncio.gather(*(run_one(case) for case in cases)))


def write_safety_csv(path: Path, results: Sequence[SafetyResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "user_input",
        "expected_safety_class",
        "predicted_safety_class",
        "reasoning",
        "matched",
        "error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)
