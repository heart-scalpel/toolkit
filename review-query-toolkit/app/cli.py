"""Command-line interface for querying review CSV exports."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.dataset import (
    QUESTION_FIELDS,
    ReviewDataset,
    case_views,
    disagreement_views,
    filter_rows,
    group_counts,
    parse_assignment,
    rows_to_csv,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "workbench"
    / "input"
    / "product-safety-review-v2-2p-full340_completed50_100rows_20260902.csv"
)
DEFAULT_DISPLAY_COLUMNS = (
    "case_id",
    "annotator_username",
    "sub_capability",
    "predicted_safety_class",
    "medical_review_label",
    "boundary_status",
    "reason_codes",
    "needs_expert_adjudication",
    "user_input",
)


def _add_common_options(
    parser: argparse.ArgumentParser, *, suppress_defaults: bool = False
) -> None:
    def default(value: Any) -> Any:
        return argparse.SUPPRESS if suppress_defaults else value

    parser.add_argument("--input", type=Path, default=default(DEFAULT_INPUT), help="输入 CSV 文件")
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default=default("table"),
        help="输出格式，默认 table",
    )
    parser.add_argument(
        "--output", type=Path, default=default(None), help="将结果写入文件；不传则输出到终端"
    )
    parser.add_argument(
        "--case-id",
        dest="case_ids",
        action="append",
        default=default(None),
        help="按 case_id 筛选，可重复",
    )
    parser.add_argument(
        "--annotator", action="append", default=default(None), help="按标注者筛选，可重复"
    )
    parser.add_argument(
        "--where",
        action="append",
        default=default([]),
        metavar="FIELD=VALUE",
        help="字段精确匹配，可重复",
    )
    parser.add_argument(
        "--contains",
        action="append",
        default=default([]),
        metavar="FIELD=TEXT",
        help="字段包含文本匹配，可重复",
    )
    parser.add_argument(
        "--has-label",
        action="append",
        default=default([]),
        metavar="FIELD=LABEL",
        help="JSON 多选字段包含某标签，可重复",
    )
    parser.add_argument(
        "--missing", action="append", default=default([]), metavar="FIELD", help="筛选空值字段"
    )
    parser.add_argument(
        "--search", default=default(None), help="在 case_id、用户输入、上下文和审核说明中搜索"
    )
    parser.add_argument(
        "--completed-only",
        action="store_true",
        default=default(False),
        help="只保留有至少两位标注者提交的 case",
    )
    parser.add_argument(
        "--disagreement",
        choices=("any", *QUESTION_FIELDS),
        default=default(None),
        help="只保留指定字段存在双人分歧的 case",
    )
    parser.add_argument(
        "--select", default=default(None), help="输出列，逗号分隔；默认使用适合阅读的列"
    )
    parser.add_argument("--sort-by", default=default(None), help="按字段排序")
    parser.add_argument(
        "--descending", action="store_true", default=default(False), help="倒序排列"
    )
    parser.add_argument("--limit", type=int, default=default(None), help="限制输出数量")
    parser.add_argument("--offset", type=int, default=default(0), help="跳过前 N 条，默认 0")


def build_parser() -> argparse.ArgumentParser:
    subcommand_common = argparse.ArgumentParser(add_help=False)
    _add_common_options(subcommand_common, suppress_defaults=True)
    parser = argparse.ArgumentParser(
        description="查询和比较人工审核 CSV，支持筛选、分歧、统计和导出。",
    )
    _add_common_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", parents=[subcommand_common], help="显示数据集和字段概览")
    subparsers.add_parser("agreement", parents=[subcommand_common], help="分析双人标注一致性")
    reference = subparsers.add_parser(
        "reference-agreement", parents=[subcommand_common], help="对照参考引擎与人工标注"
    )
    reference.add_argument(
        "--reference-field",
        default="predicted_safety_class",
        help="参考引擎字段，默认 predicted_safety_class",
    )
    reference.add_argument(
        "--review-field",
        default="medical_review_label",
        help="人工审核字段，默认 medical_review_label",
    )
    subparsers.add_parser("query", parents=[subcommand_common], help="逐行查询和显示响应")
    subparsers.add_parser("cases", parents=[subcommand_common], help="按 case_id 折叠为一行查看")

    disagreements = subparsers.add_parser(
        "disagreements", parents=[subcommand_common], help="列出双人分歧的 case"
    )
    disagreements.add_argument(
        "--field",
        choices=("any", *QUESTION_FIELDS),
        default="any",
        help="只查看某个问题字段的分歧，默认 any",
    )

    group = subparsers.add_parser("group-by", parents=[subcommand_common], help="按字段分组计数")
    group.add_argument("field", help="分组字段名")
    group.add_argument("--unit", choices=("rows", "cases"), default="rows")
    group.add_argument("--explode", action="store_true", help="拆开 JSON 多选值分别计数")

    fields = subparsers.add_parser("fields", parents=[subcommand_common], help="列出字段及空值情况")
    fields.set_defaults(ignore_filters=True)

    export = subparsers.add_parser("export", parents=[subcommand_common], help="导出筛选后的原始行")
    export.set_defaults(force_csv=True)
    return parser


def _assignments(raw_values: Iterable[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in raw_values:
        field, value = parse_assignment(raw)
        values[field] = value
    return values


def _validate_window(args: argparse.Namespace) -> None:
    if args.offset < 0:
        raise ValueError("--offset must be at least 0")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be at least 1")


def _filtered_rows(dataset: ReviewDataset, args: argparse.Namespace) -> list[dict[str, str]]:
    return filter_rows(
        dataset,
        case_ids=args.case_ids or (),
        annotators=args.annotator or (),
        equals=_assignments(args.where),
        contains=_assignments(args.contains),
        labels=_assignments(args.has_label),
        search=args.search or "",
        missing=args.missing,
        completed_only=args.completed_only,
        disagreement=args.disagreement,
    )


def _window(values: Sequence[Any], args: argparse.Namespace) -> list[Any]:
    start = args.offset
    stop = None if args.limit is None else start + args.limit
    return list(values[start:stop])


def _sorted(values: Sequence[Mapping[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    result = [dict(value) for value in values]
    if args.sort_by:
        if result and args.sort_by not in result[0]:
            raise ValueError(f"unknown result field for --sort-by: {args.sort_by}")
        result.sort(
            key=lambda row: str(row.get(args.sort_by, "")).casefold(), reverse=args.descending
        )
    return result


def _selected_columns(args: argparse.Namespace, available: Sequence[str]) -> list[str]:
    if args.select:
        columns = [column.strip() for column in args.select.split(",") if column.strip()]
        missing = [column for column in columns if column not in available]
        if missing:
            raise ValueError("unknown output columns: " + ", ".join(missing))
        return columns
    preferred = [column for column in DEFAULT_DISPLAY_COLUMNS if column in available]
    return preferred or list(available)


def _display_value(value: object, max_length: int = 72) -> str:
    if isinstance(value, (list, dict, tuple)):
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value if value is not None else "")
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 1] + "…"
    return text


def _table_text(rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> str:
    if not rows:
        return "(没有匹配结果)\n"
    normalized = [
        {column: _display_value(row.get(column, "")) for column in columns} for row in rows
    ]
    widths = {
        column: min(48, max(len(column), *(len(row[column]) for row in normalized)))
        for column in columns
    }
    header = " | ".join(column.ljust(widths[column]) for column in columns)
    divider = "-+-".join("-" * widths[column] for column in columns)
    lines = [header, divider]
    for row in normalized:
        lines.append(" | ".join(row[column].ljust(widths[column]) for column in columns))
    return "\n".join(lines) + "\n"


def _csv_rows(
    rows: Sequence[Mapping[str, object]], columns: Sequence[str]
) -> list[dict[str, object]]:
    result = []
    for row in rows:
        result.append(
            {
                column: json.dumps(row.get(column), ensure_ascii=False, separators=(",", ":"))
                if isinstance(row.get(column), (list, dict, tuple))
                else row.get(column, "")
                for column in columns
            }
        )
    return result


def _dict_rows(value: Mapping[str, object]) -> list[dict[str, object]]:
    return [{"metric": key, "value": item} for key, item in value.items()]


def _write_or_print(
    data: object,
    args: argparse.Namespace,
    *,
    columns: Sequence[str] | None = None,
) -> None:
    if isinstance(data, Mapping):
        rows: list[Mapping[str, object]] = _dict_rows(data)
        output_columns = ("metric", "value")
    elif isinstance(data, list):
        rows = [row for row in data if isinstance(row, Mapping)]
        output_columns = list(columns or (list(rows[0]) if rows else []))
    else:
        rows = [{"value": data}]
        output_columns = ["value"]

    if args.format == "json":
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    elif args.format == "csv":
        text = rows_to_csv(output_columns, _csv_rows(rows, output_columns))
    else:
        table_columns = list(columns or output_columns)
        text = _table_text(rows, table_columns)

    if args.output:
        if args.output.exists():
            raise ValueError(f"refusing to overwrite output file: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"已写入: {args.output}")
    else:
        print(text, end="")


def _fields_report(dataset: ReviewDataset) -> list[dict[str, object]]:
    report = []
    for field in dataset.columns:
        values = [row[field] for row in dataset.rows]
        report.append(
            {
                "field": field,
                "nonempty": sum(bool(value.strip()) for value in values),
                "missing": sum(not value.strip() for value in values),
                "unique": len(set(values)),
            }
        )
    return report


def _subset(dataset: ReviewDataset, rows: Sequence[Mapping[str, str]]) -> ReviewDataset:
    return ReviewDataset(dataset.source, dataset.columns, tuple(dict(row) for row in rows))


def run(args: argparse.Namespace) -> int:
    _validate_window(args)
    dataset = ReviewDataset.from_csv(args.input)

    if args.command == "fields":
        _write_or_print(
            _fields_report(dataset), args, columns=("field", "nonempty", "missing", "unique")
        )
        return 0

    selected = _filtered_rows(dataset, args)
    if args.command == "summary":
        report = _subset(dataset, selected).summary()
        _write_or_print(report, args)
        return 0

    if args.command == "agreement":
        report = _subset(dataset, selected).agreement_report()
        _write_or_print(report, args)
        return 0

    if args.command == "reference-agreement":
        report = _subset(dataset, selected).reference_agreement_report(
            reference_field=args.reference_field,
            review_field=args.review_field,
        )
        _write_or_print(report, args)
        return 0

    if args.command in {"query", "export"}:
        if args.sort_by:
            if args.sort_by not in dataset.columns:
                raise ValueError(f"unknown CSV column for --sort-by: {args.sort_by}")
            selected.sort(
                key=lambda row: row.get(args.sort_by, "").casefold(), reverse=args.descending
            )
        selected = _window(selected, args)
        if args.command == "export" and args.format == "table":
            args.format = "csv"
        columns = _selected_columns(args, dataset.columns) if args.select else list(dataset.columns)
        if args.command == "query" and args.format == "table":
            columns = _selected_columns(args, dataset.columns)
        _write_or_print(selected, args, columns=columns)
        return 0

    if args.command == "cases":
        views = case_views(dataset, selected)
        views = _sorted(views, args)
        views = _window(views, args)
        columns = _selected_columns(args, list(views[0]) if views else ("case_id",))
        _write_or_print(views, args, columns=columns)
        return 0

    if args.command == "disagreements":
        selected_ids = {row["case_id"].strip() for row in selected}
        views = [
            view
            for view in disagreement_views(dataset, args.field)
            if view["case_id"] in selected_ids
        ]
        views = _sorted(views, args)
        views = _window(views, args)
        columns = _selected_columns(args, list(views[0]) if views else ("case_id",))
        _write_or_print(views, args, columns=columns)
        return 0

    if args.command == "group-by":
        values = group_counts(
            dataset, args.field, rows=selected, unit=args.unit, explode=args.explode
        )
        _write_or_print(values, args, columns=("value", "count", "rate"))
        return 0

    raise ValueError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
