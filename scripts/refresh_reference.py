"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Writes ``src/xippios/usda/nass/reference/<param>.json`` for every packaged parameter
list through the layer-1 wrapper (never the task, which would answer from the package),
``columns.csv`` from the column table in ``docs/upstream/param_define.md``, and
``enums.py`` with one ``StrEnum`` per packaged and derived list (member names derived from
the values, values verbatim). The derived lists, progress stages and condition categories,
come from one national year of weekly ``api_GET`` rows. Run from the repository root with
the API key in the environment::

    uv run python scripts/refresh_reference.py
"""

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from xippios.core import sync
from xippios.core.reference import render_str_enums

from xippios.usda.nass import api
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/nass"
REFERENCE = PACKAGE_DIR / "reference"
PARAM_DEFINE = ROOT / "docs/upstream/param_define.md"
ENUMS = PACKAGE_DIR / "enums.py"

_ARTIFACTS = {
    "reference_period_  desc": "reference_period_desc",
    "CV %": "CV (%)",
    "value": "Value",
}


def columns_from_snapshot() -> list[dict[str, str]]:
    """Column name, max length and definition from the snapshot's table."""
    rows: list[dict[str, str]] = []
    dimension = ""
    for line in PARAM_DEFINE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| ---") or "**" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3 or not cells[0]:
            continue
        if not cells[1] and not cells[2]:
            dimension = cells[0]
            continue
        raw = re.sub(r"\s*\(.*\)$", "", cells[0]).strip()
        name = _ARTIFACTS.get(raw, raw)
        rows.append(
            {"column": name, "dimension": dimension, "max_length": cells[1], "definition": cells[2]}
        )
    if not 35 <= len(rows) <= 45:
        raise SystemExit(f"expected about 39 columns in {PARAM_DEFINE}, parsed {len(rows)}")
    return rows


_ENUM_NAMES = {"progress_stages": "ProgressStage", "condition_categories": "ConditionCategory"}


def derive(name: str, filters: dict[str, str | int], year: int, today: str) -> list[str]:
    """Distinct ``unit_desc`` values of one national year of weekly rows, written to a file."""
    query: dict[str, str | int] = {**filters, "freq_desc": "WEEKLY", "year": year}
    rows = sync(api.api_GET)(query).data
    values = sorted({row.unit_desc for row in rows})
    path = REFERENCE / f"{name}.json"
    payload = {"param": "unit_desc", "fetched": today, "values": values, "derived_from": query}
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"{path.name}: {len(values)} values from {len(rows)} rows")  # noqa: T201
    return values


def main() -> None:
    """Fetch the packaged lists, derive stages and categories, rebuild columns.csv and enums.py."""
    now = datetime.now(UTC)
    today = now.date().isoformat()
    fetch = sync(api.get_param_values)
    lists: dict[str, list[str]] = {}
    for param in PACKAGED_PARAMS:
        values = fetch(param)
        lists[param] = values
        path = REFERENCE / f"{param}.json"
        path.write_text(
            json.dumps({"param": param, "fetched": today, "values": values}, indent=2) + "\n"
        )
        print(f"{path.name}: {len(values)} values")  # noqa: T201
    for name, filters in DERIVED_LISTS.items():
        lists[name] = derive(name, filters, now.year - 1, today)
    ENUMS.write_text(
        render_str_enums(
            lists,
            class_names=_ENUM_NAMES,
            fetched=today,
            generator="scripts/refresh_reference.py",
        )
    )
    print(f"{ENUMS.name}: {len(lists)} enums")  # noqa: T201
    with (REFERENCE / "columns.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["column", "dimension", "max_length", "definition"]
        )
        writer.writeheader()
        writer.writerows(columns_from_snapshot())
    print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


if __name__ == "__main__":
    main()
