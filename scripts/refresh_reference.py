"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

Writes ``src/xippios/usda/nass/reference/<param>.json`` for every packaged parameter
list through the layer-1 wrapper (never the task, which would answer from the package),
with ``PackagedList.write``: the parameter, the upstream operation, the UTC time of the
fetch to the second and the values as records of one field named by the parameter
(conventions §3). ``columns.csv`` is rebuilt from the column table in
``docs/upstream/param_define.md``, which the snapshot keeps as HTML (conventions §3). The
table is parsed before any request, and every list is fetched before the first file is
written, so a snapshot the parser cannot read, or a fetch that fails, leaves every
packaged file as it was. Run from the repository root with what the list endpoints need
in the environment, the API key, since every Quick Stats endpoint takes it::

    uv run python scripts/refresh_reference.py

The package's client sends each request once, ``RetryPolicy(max_attempts=1)``, so a 5xx
or a 429 spends no second keyed call: a run that fails writes nothing and is run again.
After the fetches it prints the requests it sent, a failed run's too; Quick Stats reports
no quota left (``QUOTA_HEADER``). A full run sends 9: one ``get_param_values`` per
packaged parameter. ``--only <list> [<list> ...]`` fetches the named lists of
``PACKAGED_PARAMS`` alone, writes their files and keeps every other
file as it is, ``columns.csv`` among them, as a change that packages a new list does;
since the package reads every list, each list it keeps must be packaged already, which
is checked before the first request.
"""

import argparse
import csv
import io
import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import httpx
from xippios.core import AsyncClient, PackagedList, RetryPolicy, sync

from xippios.usda.nass import api
from xippios.usda.nass._client import client
from xippios.usda.nass.params import PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "src/xippios/usda/nass"
REFERENCE = PACKAGE_DIR / "reference"
PARAM_DEFINE = ROOT / "docs/upstream/param_define.md"

COLUMNS = REFERENCE / "columns.csv"


QUOTA_HEADER: str | None = None
"""The response header in which upstream reports the requests left in its quota: none,
since Quick Stats documents no quota and its recorded answers carry no such header."""

READ_TIMEOUT = 300.0
"""The run's read timeout in seconds, how long a request waits for its answer to arrive,
where the client's own configuration waits 60 (conventions §6): two runs on 2026-11-20 got
no answer for ``agg_level_desc`` within 60 seconds, and one request for it with this
timeout was answered in 7.5 (https://github.com/xippios/sdk-usda-nass/issues/78)."""

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


class Meter:
    """What a run spent: the requests it sent and the quota left that upstream reported.

    The client's ``observe`` hook, which core calls with every response from the wire. It
    calls the hook the client had first, a quota policy's say (sdk-core ADR-0037), and keeps
    the last count that upstream sent in ``QUOTA_HEADER``. A request is counted by its
    response: with no retry each has one, but for one that fails in transport, whose error
    ends the run.
    """

    def __init__(self, observe: Callable[[httpx.Response], None] | None) -> None:
        self.sent = 0
        self.left: int | None = None
        self._observe = observe

    def __call__(self, response: httpx.Response) -> None:
        """Count ``response`` and keep the quota it reports, after the hook it replaces."""
        if self._observe is not None:
            self._observe(response)
        self.sent += 1
        value = response.headers.get(QUOTA_HEADER) if QUOTA_HEADER else None
        if value is not None and value.isascii() and value.isdigit():
            self.left = int(value)

    def report(self) -> str:
        """The requests sent and the quota left, as upstream last reported it, one line."""
        left = "not reported" if self.left is None else f"{self.left} ({QUOTA_HEADER})"
        return f"requests sent: {self.sent}; quota left: {left}"


@contextmanager
def metered(target: AsyncClient) -> Iterator[Meter]:
    """``target`` for the block: one attempt per request, each counted, then the report.

    ``RetryPolicy(max_attempts=1)`` keeps a 5xx, a 429 or a timeout from spending a second
    keyed call, and the read timeout is ``READ_TIMEOUT``, the other timeouts ``target``'s.
    Core builds the client's pool, and with it the timeouts, at the first request in an
    event loop: the run sends the script's first request, so its pool takes them.
    ``target``'s configuration is restored after the block, and the report is printed, a
    failed run's too.
    """
    configured = target.config
    meter = Meter(configured.observe)
    target.config = replace(
        configured,
        timeouts=replace(configured.timeouts, read=READ_TIMEOUT),
        retry=RetryPolicy(max_attempts=1),
        observe=meter,
    )
    try:
        yield meter
    finally:
        target.config = configured
        print(meter.report())  # noqa: T201


def write(name: str, packaged: PackagedList) -> None:
    """Write ``reference/<name>.json``: the list as ``PackagedList.write`` writes it."""
    path = REFERENCE / f"{name}.json"
    packaged.write(path)
    print(f"{path.name}: {len(packaged.records)} values from {packaged.endpoint}")  # noqa: T201


def fetch_param(param: str) -> PackagedList:
    """A packaged parameter's values, fetched by one ``get_param_values`` call."""
    answer = sync(api.get_param_values)(param)
    return PackagedList(
        param=param,
        endpoint="get_param_values",
        fetched=answer.retrieved_at,
        records=[{param: value} for value in answer.payload],
    )


def refresh(only: Sequence[str] = ()) -> None:
    """Fetch the lists, then write their files and, on a full run, columns.csv.

    The column table is parsed, ``only``, the lists ``--only`` names, checked, and every
    list it keeps found packaged, before the first request: a snapshot the parser cannot
    read, a list the script does not package, or a kept list whose file is absent stops
    the run before anything is sent or written, since the package reads every list. Every
    list is fetched before the first file is written, each request sent once and counted.
    """
    columns = columns_csv(columns_from_snapshot())
    if unknown := [name for name in only if name not in PACKAGED_PARAMS]:
        raise SystemExit(f"--only: no list {', '.join(unknown)} in {', '.join(PACKAGED_PARAMS)}")
    chosen = set(only or PACKAGED_PARAMS)
    kept = [name for name in PACKAGED_PARAMS if name not in chosen]
    if missing := [name for name in kept if not (REFERENCE / f"{name}.json").is_file()]:
        raise SystemExit(f"{', '.join(missing)} is not packaged yet: run without --only")
    with metered(client):
        lists = [(param, fetch_param(param)) for param in PACKAGED_PARAMS if param in chosen]
    for name, packaged in lists:
        write(name, packaged)
    if not only:
        COLUMNS.write_text(columns, encoding="utf-8", newline="")
        print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


def main(argv: Sequence[str] | None = None) -> None:
    """Refresh from upstream, every list or some lists alone with ``--only``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--only",
        nargs="+",
        default=[],
        metavar="LIST",
        help="fetch these lists alone and keep every other file",
    )
    args = parser.parse_args(argv)
    refresh(args.only)


if __name__ == "__main__":
    main()
