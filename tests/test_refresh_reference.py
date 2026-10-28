"""``scripts/refresh_reference.py``'s column table parser, offline.

``columns.csv`` is rebuilt from the HTML column table the snapshot keeps in
``docs/upstream/param_define.md`` (conventions §3); these tests read the committed
snapshot and the committed file and send no request.
"""

import csv
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
COLUMNS = ROOT / "src" / "xippios" / "usda" / "nass" / "reference" / "columns.csv"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_reference", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def test_columns_from_snapshot_equals_the_committed_columns_csv() -> None:
    rows = script.columns_from_snapshot()
    with COLUMNS.open(newline="", encoding="utf-8") as handle:
        assert rows == list(csv.DictReader(handle))
    assert script.columns_csv(rows).encode("utf-8") == COLUMNS.read_bytes()


def test_refresh_stops_before_any_write_when_the_table_does_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "param_define.md"
    snapshot.write_text(
        "| Column or Header Name | Max Length | Definition |\n| --- | --- | --- |\n",
        encoding="utf-8",
    )

    def refused(*args: object) -> None:
        raise AssertionError("refresh wrote or fetched before the column table parsed")

    monkeypatch.setattr(script, "PARAM_DEFINE", snapshot)
    monkeypatch.setattr(script, "sync", refused)
    monkeypatch.setattr(script, "write", refused)
    monkeypatch.setattr(script, "render", refused)
    monkeypatch.setattr(script, "COLUMNS", tmp_path / "columns.csv")
    with pytest.raises(SystemExit, match="no HTML column table"):
        script.refresh()
    assert not (tmp_path / "columns.csv").exists()
