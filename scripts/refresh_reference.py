"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Writes ``src/xippios/usda/nass/reference/<param>.json`` for every packaged parameter
list through the layer-1 wrapper (never the task, which would answer from the package),
and ``columns.csv`` from the column table in ``docs/upstream/param_define.md``. Run from
the repository root with the API key in the environment::

    uv run python scripts/refresh_reference.py
"""

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from xippios.core import sync

from xippios.usda.nass import api
from xippios.usda.nass.params import PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "src/xippios/usda/nass/reference"
PARAM_DEFINE = ROOT / "docs/upstream/param_define.md"

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


def main() -> None:
    """Fetch every packaged list and rebuild columns.csv."""
    today = datetime.now(UTC).date().isoformat()
    fetch = sync(api.get_param_values)
    for param in PACKAGED_PARAMS:
        values = fetch(param)
        path = REFERENCE / f"{param}.json"
        path.write_text(
            json.dumps({"param": param, "fetched": today, "values": values}, indent=2) + "\n"
        )
        print(f"{path.name}: {len(values)} values")  # noqa: T201
    with (REFERENCE / "columns.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["column", "dimension", "max_length", "definition"]
        )
        writer.writeheader()
        writer.writerows(columns_from_snapshot())
    print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


if __name__ == "__main__":
    main()
