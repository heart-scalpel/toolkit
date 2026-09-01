"""Command-line interface for single and batch prompt runs."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from app.batch import CaseResult, load_cases, run_batch, write_results

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = PROJECT_ROOT / "prompt.md"
DEFAULT_CASES = PROJECT_ROOT / "workbench" / "cases.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "workbench" / "output" / "results.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one prompt or a JSONL/CSV batch with the OpenAI Agents SDK."
    )
    parser.add_argument("input", nargs="?", help="Run one input and print its output")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT, help="System prompt file")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="Batch JSONL or CSV file")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Batch result JSONL")
    parser.add_argument("--model", help="Model ID; defaults to OPENAI_MODEL or gpt-5.6")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Parallel batch requests; defaults to PROMPT_AGENT_CONCURRENCY or 5",
    )
    return parser


def _read_prompt(path: Path) -> str:
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"{path}: prompt is empty")
    return prompt


def _print_summary(results: list[CaseResult], output: Path) -> int:
    failures = 0
    for result in results:
        failed = result.error is not None or result.passed is False
        failures += int(failed)
        status = "FAIL" if failed else "OK"
        detail = result.error or result.output or ""
        print(f"[{status}] {result.id}: {detail}")

    print(f"\n{len(results) - failures}/{len(results)} passed; results: {output}")
    return 1 if failures else 0


async def _run(args: argparse.Namespace) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is missing; copy .env.example to .env and fill it in")

    from agents import Agent, Runner

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-5.6")
    agent = Agent(name="Prompt Agent", instructions=_read_prompt(args.prompt), model=model)

    if args.input is not None:
        result = await Runner.run(agent, args.input)
        print(result.final_output)
        return 0

    concurrency = args.concurrency
    if concurrency is None:
        concurrency = int(os.getenv("PROMPT_AGENT_CONCURRENCY", "5"))
    cases = load_cases(args.cases)
    results = await run_batch(agent, cases, runner=Runner, concurrency=concurrency)
    write_results(args.output, results)
    return _print_summary(results, args.output)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
