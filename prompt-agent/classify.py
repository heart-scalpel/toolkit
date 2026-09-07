"""Run the Cozie AI safety-classifier batch and write one CSV."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from app.safety_classifier import (
    SafetyClassification,
    load_safety_cases,
    run_safety_batch,
    write_safety_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT = PROJECT_ROOT / "prompt.md"
DEFAULT_CASES = PROJECT_ROOT / "workbench" / "004_02_黄金集.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "workbench" / "output" / "safety_classifier_results.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch-run the Cozie AI safety classifier.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--model", default=None)
    parser.add_argument("--concurrency", type=int, default=5)
    return parser


async def _run(args: argparse.Namespace) -> int:
    load_dotenv(args.env)
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError(f"OPENAI_API_KEY is missing from environment or {args.env}")

    from agents import Agent, Runner, set_tracing_disabled

    set_tracing_disabled(True)
    if args.output.resolve() == args.cases.resolve():
        raise ValueError("output must differ from the source CSV")
    if args.output.exists():
        raise ValueError(f"refusing to overwrite existing results: {args.output}")

    prompt = args.prompt.read_text(encoding="utf-8")
    if not prompt.strip():
        raise ValueError(f"{args.prompt}: prompt is empty")

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-5.6")
    agent = Agent(
        name="Cozie AI Safety Classifier",
        instructions=prompt,
        model=model,
        output_type=SafetyClassification,
    )
    cases = load_safety_cases(args.cases)
    results = await run_safety_batch(
        agent,
        cases,
        runner=Runner,
        concurrency=args.concurrency,
    )
    write_safety_csv(args.output, results)

    completed = [result for result in results if result.error is None]
    matched = sum(result.matched is True for result in completed)
    errors = len(results) - len(completed)
    labeled = sum(result.matched is not None for result in completed)
    accuracy = f"{matched / labeled:.2%}" if labeled else "n/a (no human reference labels)"
    manifest = {
        "completed_at": datetime.now(UTC).isoformat(),
        "source_csv": str(args.cases.resolve()),
        "source_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "prompt": str(args.prompt.resolve()),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "model": model,
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "concurrency": args.concurrency,
        "input_fields": ["query", "user_profile (when supplied)", "short_memory (when supplied)"],
        "total": len(results),
        "completed": len(completed),
        "errors": errors,
        "human_labeled": labeled,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    args.output.with_suffix(".run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"done: total={len(results)} completed={len(completed)} errors={errors} "
        f"matched={matched} accuracy={accuracy} output={args.output}"
    )
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
