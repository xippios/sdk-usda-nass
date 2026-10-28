"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Writes ``src/xippios/usda/nass/reference/<param>.json`` for every packaged parameter
list through the layer-1 wrapper (never the task, which would answer from the package),
with ``PackagedList.write``: the parameter, the upstream operation, the UTC time of the
fetch to the second and the values as records of one field named by the parameter
(conventions §3). The derived lists, progress stages and condition categories, come from
one national year of weekly ``api_GET`` rows, the query they come from kept as the file's
``note``. Then ``enums.py`` is regenerated from the packaged files by one
``xippios.core.reference.render_enums`` call, one ``StrEnum`` per packaged and derived
list (member names derived from the values, values verbatim), each class naming the day
its list was fetched, and formatted with ``ruff format`` and ``ruff check --fix``, as it
is committed (ADR-0008); and ``columns.csv`` is rebuilt from the column table in
``docs/upstream/param_define.md``, which the snapshot keeps as HTML (conventions §3). The
table is parsed before any file is written, so a snapshot the parser cannot read leaves
every packaged file as it was. Quick Stats' lists are value lists, so there is no
``IntEnum`` path. Run from the repository root with what the list endpoints need in the
environment, the API key, since every Quick Stats endpoint takes it::

    uv run python scripts/refresh_reference.py

``--render-only`` regenerates ``enums.py`` from the packaged ``reference/*.json`` alone,
the six parameter lists and the two derived ones, without a request and without a key:
after a core release changes the renderer (conventions §15, item 6), it changes
``enums.py`` and nothing else.
"""

import argparse
import csv
import io
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from xippios.core import PackagedList, sync
from xippios.core.reference import render_enums

from xippios.usda.nass import api
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/nass"
REFERENCE = PACKAGE_DIR / "reference"
PARAM_DEFINE = ROOT / "docs/upstream/param_define.md"
ENUMS = PACKAGE_DIR / "enums.py"
GENERATOR = "scripts/refresh_reference.py"

COLUMNS = REFERENCE / "columns.csv"

# The snapshot's column names where they differ from the columns' names in the data: the
# stray space upstream prints in one key, and the two data value columns as api_GET names
# them.
_ARTIFACTS = {
    "reference_period_ desc": "reference_period_desc",
    "CV %": "CV (%)",
    "value": "Value",
}
_HEADER = ["Column or Header Name", "Max Length", "Definition"]
_FIELDS = ["column", "dimension", "max_length", "definition"]


class _TableRows(HTMLParser):
    """The ``<tr>`` rows of an HTML document, each a list of its cells' text and colspan.

    A cell's text is its character data with whitespace collapsed, entities unescaped
    (``convert_charrefs``), whatever inline markup it holds.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int]]] = []
        self._row: list[tuple[str, int]] | None = None
        self._cell: list[str] | None = None
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open a row, or a cell inside an open row."""
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._colspan = int(dict(attrs).get("colspan") or 1)

    def handle_endtag(self, tag: str) -> None:
        """Close the open cell into its row, or the open row into the rows."""
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append((" ".join("".join(self._cell).split()), self._colspan))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        """Collect the text of the open cell."""
        if self._cell is not None:
            self._cell.append(data)


def columns_from_snapshot() -> list[dict[str, str]]:
    """Column name, dimension, max length and definition from the snapshot's HTML table.

    The first ``<tr>`` is the header; a ``<tr>`` of one ``colspan="3"`` cell names the
    dimension of the rows below it; every other row is one column. The search page's
    header in parentheses after a column name is dropped, and ``_ARTIFACTS`` maps the
    names upstream prints differently from the data.
    """
    table = _TableRows()
    table.feed(PARAM_DEFINE.read_text(encoding="utf-8"))
    table.close()
    if not table.rows or [text for text, _ in table.rows[0]] != _HEADER:
        raise SystemExit(f"no HTML column table headed {_HEADER} in {PARAM_DEFINE}")
    rows: list[dict[str, str]] = []
    dimension = ""
    for cells in table.rows[1:]:
        if len(cells) == 1 and cells[0][1] == len(_HEADER):
            dimension = cells[0][0]
            continue
        if len(cells) != len(_HEADER) or not dimension:
            raise SystemExit(f"unexpected row in {PARAM_DEFINE}: {[text for text, _ in cells]}")
        (column, _), (max_length, _), (definition, _) = cells
        raw = re.sub(r"\s*\(.*\)$", "", column)
        name = _ARTIFACTS.get(raw, raw)
        rows.append(
            {
                "column": name,
                "dimension": dimension,
                "max_length": max_length,
                "definition": definition,
            }
        )
    if not 35 <= len(rows) <= 45:
        raise SystemExit(f"expected about 39 columns in {PARAM_DEFINE}, parsed {len(rows)}")
    return rows


def columns_csv(rows: list[dict[str, str]]) -> str:
    """``columns.csv`` as committed: a header line, then one line per column, CRLF-ended."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


_ENUM_NAMES = {"progress_stages": "ProgressStage", "condition_categories": "ConditionCategory"}


def write(name: str, packaged: PackagedList) -> None:
    """Write ``reference/<name>.json``: the list as ``PackagedList.write`` writes it."""
    path = REFERENCE / f"{name}.json"
    packaged.write(path)
    print(f"{path.name}: {len(packaged.records)} values from {packaged.endpoint}")  # noqa: T201


def read(name: str) -> PackagedList:
    """The packaged ``reference/<name>.json``, as ``write`` wrote it."""
    path = REFERENCE / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"{path.name} is not packaged yet: run the script without --render-only")
    return PackagedList.model_validate_json(path.read_text(encoding="utf-8"))


def note(query: Mapping[str, str | int]) -> str:
    """A derived list's ``note``: the ``api_GET`` query its ``unit_desc`` values come from."""
    filters = ", ".join(f"{key}={value}" for key, value in query.items())
    return f"distinct unit_desc of api_GET with {filters}"


def derive(name: str, filters: dict[str, str | int], year: int) -> None:
    """Distinct ``unit_desc`` values of one national year of weekly rows, written to a file."""
    query: dict[str, str | int] = {**filters, "freq_desc": "WEEKLY", "year": year}
    rows = sync(api.api_get)(query).data
    values = sorted({row.unit_desc for row in rows})
    print(f"{name}: {len(rows)} rows")  # noqa: T201
    packaged = PackagedList(
        param="unit_desc",
        endpoint="api_GET",
        fetched=datetime.now(UTC),
        note=note(query),
        records=[{"unit_desc": value} for value in values],
    )
    write(name, packaged)


def render() -> None:
    """Regenerate ``enums.py`` from the packaged lists, packaged and derived, as committed."""
    lists: dict[str, list[str]] = {}
    fetched: dict[str, str] = {}
    for name in (*PACKAGED_PARAMS, *DERIVED_LISTS):
        packaged = read(name)
        lists[name] = [record[packaged.param] for record in packaged.records]
        fetched[name] = f"{packaged.fetched:%Y-%m-%d}"
    module = render_enums(lists, fetched=fetched, class_names=_ENUM_NAMES, generator=GENERATOR)
    ENUMS.write_text(module, encoding="utf-8")
    sys.stdout.flush()
    for command in (["format"], ["check", "--fix"]):
        run = subprocess.run([sys.executable, "-m", "ruff", *command, str(ENUMS)], cwd=ROOT)
        if run.returncode:
            raise SystemExit(f"ruff {' '.join(command)} left {ENUMS.name} failing")
    print(f"{ENUMS.name}: {len(lists)} enums, from the packaged files")  # noqa: T201


def refresh() -> None:
    """Fetch the packaged lists, derive stages and categories, rebuild enums.py and columns.csv.

    The column table is parsed first: a snapshot the parser cannot read stops the run
    before any request and before any file is written.
    """
    columns = columns_csv(columns_from_snapshot())
    year = datetime.now(UTC).year - 1
    fetch = sync(api.get_param_values)
    for param in PACKAGED_PARAMS:
        values = fetch(param)
        packaged = PackagedList(
            param=param,
            endpoint="get_param_values",
            fetched=datetime.now(UTC),
            records=[{param: value} for value in values],
        )
        write(param, packaged)
    for name, filters in DERIVED_LISTS.items():
        derive(name, filters, year)
    render()
    COLUMNS.write_text(columns, encoding="utf-8", newline="")
    print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


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
        render()
    else:
        refresh()


if __name__ == "__main__":
    main()
