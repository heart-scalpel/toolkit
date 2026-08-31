"""Default workbench runner for XLSX files."""

from __future__ import annotations

import sys
from pathlib import Path

from app.xlsx_to_csv import ConversionResult, XlsxToCsvError, convert_xlsx

DEFAULT_WORKBENCH_DIR = Path(__file__).resolve().parents[1] / "workbench"


def find_workbooks(workbench_dir: Path = DEFAULT_WORKBENCH_DIR) -> list[Path]:
    """Return XLSX files placed directly in the workbench directory."""

    if not workbench_dir.is_dir():
        return []
    return sorted(
        (
            path
            for path in workbench_dir.iterdir()
            if path.is_file()
            and path.suffix.casefold() == ".xlsx"
            and not path.name.startswith("~$")
        ),
        key=lambda path: path.name.casefold(),
    )


def convert_workbench(
    workbench_dir: Path = DEFAULT_WORKBENCH_DIR,
) -> list[ConversionResult]:
    """Convert every worksheet from every XLSX file in the workbench."""

    output_dir = workbench_dir / "output"
    results = []
    for workbook_path in find_workbooks(workbench_dir):
        results.extend(
            convert_xlsx(
                workbook_path,
                output_dir / workbook_path.stem,
                all_sheets=True,
                overwrite=True,
            )
        )
    return results


def main() -> int:
    """Run the default workbench conversion."""

    workbooks = find_workbooks()
    if not workbooks:
        print(f'No XLSX files found in "{DEFAULT_WORKBENCH_DIR}".')
        print("Add XLSX files to the workbench and run this command again.")
        return 0

    try:
        results = convert_workbench()
    except XlsxToCsvError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    for result in results:
        print(f'Created "{result.output_path}" from worksheet "{result.sheet_name}".')
    print(f"Converted {len(results)} worksheet(s) from {len(workbooks)} workbook(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
