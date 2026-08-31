from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from app.cli import main


def _create_workbook(path: Path) -> None:
    workbook = Workbook()
    workbook.active.title = "数据"
    workbook.active.append(["name", "value"])
    workbook.active.append(["中文", 42])
    workbook.save(path)
    workbook.close()


def test_cli_converts_workbook(tmp_path: Path, capsys: object) -> None:
    source = tmp_path / "input.xlsx"
    output = tmp_path / "output.csv"
    _create_workbook(source)

    exit_code = main([str(source), "--output", str(output)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.exists()
    assert 'Converted "数据"' in captured.out
    assert captured.err == ""


def test_cli_returns_one_for_conversion_error(tmp_path: Path, capsys: object) -> None:
    source = tmp_path / "missing.xlsx"

    exit_code = main([str(source)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "error:" in captured.err
