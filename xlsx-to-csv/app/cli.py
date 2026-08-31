"""Command-line interface for the XLSX-to-CSV backend."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from app.xlsx_to_csv import XlsxToCsvError, convert_xlsx


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Convert an XLSX workbook to CSV.",
    )
    parser.add_argument("source", help="Source .xlsx file.")
    parser.add_argument("-o", "--output", help="Output CSV file or directory.")

    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--sheet", help="Worksheet name.")
    selection.add_argument("--sheet-index", type=int, help="One-based worksheet index.")
    selection.add_argument(
        "--all-sheets",
        action="store_true",
        help="Convert all worksheets, including hidden worksheets.",
    )

    parser.add_argument(
        "--formulas",
        action="store_true",
        help="Export formula expressions instead of cached values.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding (default: utf-8-sig).",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="One-character CSV delimiter (default: comma).",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Replace existing output files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the converter CLI."""

    args = build_parser().parse_args(argv)
    sheet = args.sheet_index if args.sheet_index is not None else args.sheet

    try:
        results = convert_xlsx(
            args.source,
            args.output,
            sheet=sheet,
            all_sheets=args.all_sheets,
            encoding=args.encoding,
            delimiter=args.delimiter,
            data_only=not args.formulas,
            overwrite=args.force,
        )
    except XlsxToCsvError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for result in results:
        print(
            f'Converted "{result.sheet_name}" to "{result.output_path}" '
            f"({result.row_count} rows, {result.column_count} columns)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
