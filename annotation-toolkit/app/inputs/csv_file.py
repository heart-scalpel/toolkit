"""Generic CSV loading without business-specific column assumptions."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CsvTable:
    columns: tuple[str, ...]
    rows: list[dict[str, str]]


def read_csv(path: Path) -> CsvTable:
    """Read a UTF-8 CSV while preserving row and column order."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        if not columns:
            raise ValueError(f"{path}: CSV must contain a non-empty header")
        if len(columns) != len(set(columns)):
            raise ValueError(f"{path}: CSV contains duplicate column names")
        rows = [
            {name: value or "" for name, value in row.items() if name is not None} for row in reader
        ]

    if not rows:
        raise ValueError(f"{path}: no records found")
    return CsvTable(columns=columns, rows=rows)
