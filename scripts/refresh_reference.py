"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Writes ``src/xippios/usda/nass/reference/<param>.json`` for every packaged parameter
list through the layer-1 wrapper (never the task, which would answer from the package),
``columns.csv`` from the column table in ``docs/upstream/param_define.md``, and
``enums.py`` with one ``StrEnum`` per packaged and derived list (member names derived from
the values, values verbatim) through ``xippios.core.reference.render_str_enums``,
ASCII-only and ruff-clean, with no formatting step after it (ADR-0008). The derived lists,
progress stages and condition categories, come from one national year of weekly
``api_GET`` rows. Quick Stats' lists are value lists, so there is no ``IntEnum`` path.
Run from the repository root with what the list endpoints need in the environment, the
API key, since every Quick Stats endpoint takes it::

    uv run python scripts/refresh_reference.py

``--render-only`` regenerates ``enums.py`` from the packaged ``reference/*.json`` alone,
the six parameter lists and the two derived ones, without a request and without a key:
after a core release changes the renderer (conventions §15, item 6), it changes
``enums.py`` and nothing else.
"""

import argparse
import csv
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xippios.core import sync
from xippios.core.reference import render_str_enums

from xippios.usda.nass import api
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGED_PARAMS, PackagedValues

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/nass"
REFERENCE = PACKAGE_DIR / "reference"
PARAM_DEFINE = ROOT / "docs/upstream/param_define.md"
ENUMS = PACKAGE_DIR / "enums.py"
GENERATOR = "scripts/refresh_reference.py"

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


def write(name: str, payload: Mapping[str, Any]) -> None:
    """Write ``reference/<name>.json``: the list's parameter, the fetch date and its values."""
    path = REFERENCE / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read(name: str) -> PackagedValues:
    """The packaged ``reference/<name>.json``, as ``write`` wrote it."""
    path = REFERENCE / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"{path.name} is not packaged yet: run the script without --render-only")
    return PackagedValues.model_validate(json.loads(path.read_text(encoding="utf-8")))


def render(lists: Mapping[str, Sequence[str]], fetched: str | None) -> str:
    """``enums.py`` as core renders it: one ``StrEnum`` per list, in the order of ``lists``."""
    return render_str_enums(lists, class_names=_ENUM_NAMES, fetched=fetched, generator=GENERATOR)


def derive(name: str, filters: dict[str, str | int], year: int, today: str) -> list[str]:
    """Distinct ``unit_desc`` values of one national year of weekly rows, written to a file."""
    query: dict[str, str | int] = {**filters, "freq_desc": "WEEKLY", "year": year}
    rows = sync(api.api_GET)(query).data
    values = sorted({row.unit_desc for row in rows})
    write(name, {"param": "unit_desc", "fetched": today, "values": values, "derived_from": query})
    print(f"{name}.json: {len(values)} values from {len(rows)} rows")  # noqa: T201
    return values


def refresh() -> None:
    """Fetch the packaged lists, derive stages and categories, rebuild columns.csv and enums.py."""
    now = datetime.now(UTC)
    today = now.date().isoformat()
    fetch = sync(api.get_param_values)
    lists: dict[str, list[str]] = {}
    for param in PACKAGED_PARAMS:
        values = fetch(param)
        lists[param] = values
        write(param, {"param": param, "fetched": today, "values": values})
        print(f"{param}.json: {len(values)} values")  # noqa: T201
    for name, filters in DERIVED_LISTS.items():
        lists[name] = derive(name, filters, now.year - 1, today)
    ENUMS.write_text(render(lists, today), encoding="utf-8")
    print(f"{ENUMS.name}: {len(lists)} enums")  # noqa: T201
    with (REFERENCE / "columns.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["column", "dimension", "max_length", "definition"]
        )
        writer.writeheader()
        writer.writerows(columns_from_snapshot())
    print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


def render_only() -> None:
    """Regenerate ``enums.py`` from the packaged lists, packaged and derived, without a request."""
    dates: set[str] = set()
    lists: dict[str, list[str]] = {}
    for name in (*PACKAGED_PARAMS, *DERIVED_LISTS):
        packaged = read(name)
        lists[name] = packaged.values
        dates.add(packaged.fetched.isoformat())
    if len(dates) > 1:
        raise SystemExit(f"the packaged lists were fetched on different days: {sorted(dates)}")
    ENUMS.write_text(render(lists, dates.pop() if dates else None), encoding="utf-8")
    print(f"{ENUMS.name}: {len(lists)} enums, from the packaged files")  # noqa: T201


def main() -> None:
    """Refresh from upstream, or with ``--render-only`` regenerate ``enums.py`` alone."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="regenerate enums.py from the packaged reference/*.json, without a request or a key",
    )
    args = parser.parse_args()
    if args.render_only:
        render_only()
    else:
        refresh()


if __name__ == "__main__":
    main()
