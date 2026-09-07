"""Safety-classifier batch input, execution, and CSV output."""

from __future__ import annotations

import asyncio
import csv
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
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
    source: dict[str, str] = field(default_factory=dict)

    def model_input(self) -> str:
        """Send only the query and supplied context, never draft or reference labels."""
        context = {}
        for column, key in (
            ("user_profile", "user_profile"),
            ("conversation_history", "short_memory"),
        ):
            raw = self.source.get(column, "").strip()
            if raw:
                context[key] = json.loads(raw)
        if not context:
            return self.user_input
        return json.dumps({"query": self.user_input, **context}, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class SafetyResult:
    user_input: str
    expected_safety_class: str | None
    predicted_safety_class: str | None
    reasoning: str | None
    matched: bool | None
    error: str | None
    source: dict[str, str] = field(default_factory=dict)


def load_safety_cases(path: Path) -> list[SafetyCase]:
    """Preserve CSV fields while exposing only input context to the classifier."""
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
    if len(headers) != len(set(headers)):
        raise ValueError(f"{path}: duplicate CSV columns")
    cases: list[SafetyCase] = []
    for line_number, row in enumerate(rows[header_index + 1 :], header_index + 2):
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != len(headers):
            raise ValueError(f"{path}:{line_number}: CSV row width differs from header")
        record = dict(zip(headers, row, strict=True))
        user_input = record.get("user_input", "").strip()
        expected = record.get("expected_safety_class", "").strip() or None
        if not user_input:
            raise ValueError(f"{path}:{line_number}: 'user_input' must be non-empty")
        case = SafetyCase(user_input=user_input, expected_safety_class=expected, source=record)
        try:
            case.model_input()
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid context JSON: {exc.msg}") from exc
        cases.append(case)

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
                run_result = await runner.run(agent, case.model_input())
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
                source=case.source,
            )
        except Exception as exc:
            result = SafetyResult(
                user_input=case.user_input,
                expected_safety_class=case.expected_safety_class,
                predicted_safety_class=None,
                reasoning=None,
                matched=None,
                error=f"{type(exc).__name__}: {exc}",
                source=case.source,
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
    result_columns = [
        "user_input",
        "expected_safety_class",
        "predicted_safety_class",
        "reasoning",
        "matched",
        "error",
    ]
    fieldnames = list(dict.fromkeys(key for result in results for key in result.source))
    fieldnames.extend(key for key in result_columns if key not in fieldnames)
    with path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            values = asdict(result)
            source = values.pop("source")
            # Keep original inputs and human reference cells byte-for-byte in CSV values.
            writer.writerow(
                {
                    **source,
                    **{
                        key: source.get(key, value)
                        if key in ("user_input", "expected_safety_class")
                        else value
                        for key, value in values.items()
                    },
                }
            )
