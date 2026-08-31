"""XLSX-to-CSV conversion library."""

from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

PathLike = str | os.PathLike[str]
SheetSelector = str | int

_INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class XlsxToCsvError(Exception):
    """Raised when an XLSX workbook cannot be converted."""


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Summary for one converted worksheet."""

    sheet_name: str
    output_path: Path
    row_count: int
    column_count: int


def convert_xlsx(
    source: PathLike,
    output: PathLike | None = None,
    *,
    sheet: SheetSelector | None = None,
    all_sheets: bool = False,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
    data_only: bool = True,
    overwrite: bool = False,
) -> list[ConversionResult]:
    """Convert one or all worksheets from an XLSX workbook to CSV.

    Worksheet indices are one-based. By default, the first ordinary worksheet
    is converted. Hidden worksheets are included when all_sheets is enabled.
    """

    source_path = _validate_source(source)
    output_path = Path(output).expanduser().resolve() if output is not None else None
    _validate_options(sheet, all_sheets, encoding, delimiter)

    try:
        workbook = load_workbook(
            source_path,
            read_only=True,
            data_only=data_only,
            keep_links=False,
        )
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        raise XlsxToCsvError(f'Cannot read workbook "{source_path}": {error}') from error

    try:
        selected = _select_worksheets(workbook, sheet=sheet, all_sheets=all_sheets)
        targets = _build_targets(source_path, output_path, selected)
        _check_targets(targets, overwrite=overwrite)

        results = []
        for _, worksheet, target in targets:
            row_count, column_count = _write_csv(
                worksheet,
                target,
                encoding=encoding,
                delimiter=delimiter,
                overwrite=overwrite,
            )
            results.append(
                ConversionResult(
                    sheet_name=worksheet.title,
                    output_path=target,
                    row_count=row_count,
                    column_count=column_count,
                )
            )
        return results
    finally:
        workbook.close()


def _validate_source(source: PathLike) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise XlsxToCsvError(f'Source file "{source_path}" does not exist.')
    if source_path.suffix.casefold() != ".xlsx":
        raise XlsxToCsvError("Only .xlsx workbooks are supported.")
    return source_path


def _validate_options(
    sheet: SheetSelector | None,
    all_sheets: bool,
    encoding: str,
    delimiter: str,
) -> None:
    if all_sheets and sheet is not None:
        raise XlsxToCsvError("sheet and all_sheets cannot be used together.")
    if isinstance(sheet, bool):
        raise XlsxToCsvError("Worksheet index must be a one-based integer.")
    if len(delimiter) != 1 or delimiter in {'"', "\r", "\n", "\0"}:
        raise XlsxToCsvError("Delimiter must be one valid CSV character.")
    try:
        "".encode(encoding)
    except LookupError as error:
        raise XlsxToCsvError(f'Unknown encoding "{encoding}".') from error


def _select_worksheets(
    workbook: Any,
    *,
    sheet: SheetSelector | None,
    all_sheets: bool,
) -> list[tuple[int, Any]]:
    worksheets = list(workbook.worksheets)
    if not worksheets:
        raise XlsxToCsvError("Workbook does not contain any worksheets.")
    if all_sheets:
        return list(enumerate(worksheets, start=1))
    if sheet is None:
        return [(1, worksheets[0])]
    if isinstance(sheet, int):
        if not 1 <= sheet <= len(worksheets):
            raise XlsxToCsvError(f"Worksheet index {sheet} is out of range (1-{len(worksheets)}).")
        return [(sheet, worksheets[sheet - 1])]

    for index, worksheet in enumerate(worksheets, start=1):
        if worksheet.title == sheet:
            return [(index, worksheet)]
    available = ", ".join(worksheet.title for worksheet in worksheets)
    raise XlsxToCsvError(f'Worksheet "{sheet}" was not found. Available: {available}.')


def _build_targets(
    source: Path,
    output: Path | None,
    selected: list[tuple[int, Any]],
) -> list[tuple[int, Any, Path]]:
    if output is None and len(selected) == 1:
        index, worksheet = selected[0]
        return [(index, worksheet, source.with_suffix(".csv"))]

    if output is not None and output.suffix.casefold() == ".csv":
        if len(selected) != 1:
            raise XlsxToCsvError("A CSV output path can only be used for one worksheet.")
        index, worksheet = selected[0]
        return [(index, worksheet, output)]

    output_dir = output or source.parent / f"{source.stem}_csv"
    if output_dir.exists() and not output_dir.is_dir():
        raise XlsxToCsvError(f'Output path "{output_dir}" is not a directory.')

    return [
        (
            index,
            worksheet,
            output_dir / f"{index:03d}_{_safe_filename(worksheet.title, index)}.csv",
        )
        for index, worksheet in selected
    ]


def _safe_filename(title: str, index: int) -> str:
    name = _INVALID_FILENAME_CHARS.sub("_", title).strip().rstrip(". ")
    if not name or name in {".", ".."}:
        name = f"sheet-{index}"
    if name.partition(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name


def _check_targets(
    targets: list[tuple[int, Any, Path]],
    *,
    overwrite: bool,
) -> None:
    for _, _, target in targets:
        if target.exists() and target.is_dir():
            raise XlsxToCsvError(f'Output path "{target}" is a directory.')
        if target.exists() and not overwrite:
            raise XlsxToCsvError(
                f'Output file "{target}" already exists. Use overwrite to replace it.'
            )


def _write_csv(
    worksheet: Any,
    target: Path,
    *,
    encoding: str,
    delimiter: str,
    overwrite: bool,
) -> tuple[int, int]:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
    except OSError as error:
        raise XlsxToCsvError(f'Cannot prepare output file "{target}": {error}') from error

    temporary_path = Path(temporary_name)
    try:
        with open(
            file_descriptor,
            mode="w",
            encoding=encoding,
            newline="",
            closefd=True,
        ) as output_file:
            writer = csv.writer(
                output_file,
                delimiter=delimiter,
                lineterminator="\n",
                quoting=csv.QUOTE_MINIMAL,
            )
            row_count, column_count = _write_rows(worksheet, writer)

        if target.exists() and not overwrite:
            raise XlsxToCsvError(
                f'Output file "{target}" already exists. Use overwrite to replace it.'
            )
        os.replace(temporary_path, target)
        return row_count, column_count
    except XlsxToCsvError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise XlsxToCsvError(f'Cannot write output file "{target}": {error}') from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_rows(worksheet: Any, writer: Any) -> tuple[int, int]:
    reset_dimensions = getattr(worksheet, "reset_dimensions", None)
    if callable(reset_dimensions):
        reset_dimensions()

    pending_empty_rows = 0
    row_count = 0
    column_count = 0

    for raw_row in worksheet.iter_rows(values_only=True):
        values = list(raw_row)
        while values and values[-1] is None:
            values.pop()

        if not values:
            pending_empty_rows += 1
            continue

        for _ in range(pending_empty_rows):
            writer.writerow(())
            row_count += 1
        pending_empty_rows = 0

        writer.writerow(_serialize(value) for value in values)
        row_count += 1
        column_count = max(column_count, len(values))

    return row_count, column_count


def _serialize(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value
