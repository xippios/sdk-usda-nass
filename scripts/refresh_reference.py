"""Refresh the packaged reference data from upstream (``/refresh-reference-data``).

The script declares its lists to core's frame, ``xippios.core.refresh``, in one ``Lists``
(sdk-core ADR-0062): one ``Listed`` per packaged list, the nine parameter lists of
``PACKAGED_PARAMS``, each fetched by one ``get_param_values`` call through the layer-1
wrapper (never the task, which would answer from the package) and stamped with the
wrapper's ``retrieved_at``, its values as records of one field named by the parameter
(conventions §3). The frame fetches every list before it writes one, each request sent
once and counted, and writes the packaged files with ``PackagedList.write`` and the
provenance rows of ``reference/README.md``; no list declares an enum, so the frame leaves
``enums.py`` alone and the package ships none.

The script's own code is the fetch, ``columns.csv`` and the read timeout. ``columns.csv`` is
rebuilt from the column table in ``docs/upstream/param_define.md``, which the snapshot keeps
as HTML (conventions §3): the declaration's ``before`` parses the table before the first
request, so a snapshot the parser cannot read stops the run before anything is sent, and
its ``after`` writes the file once every list was fetched, on a full run alone. The client
waits ``READ_TIMEOUT`` for an answer around the run. Run from the repository root with the
API key in the environment, since every Quick Stats endpoint takes it::

    uv run python scripts/refresh_reference.py

A full run sends 9 requests, one ``get_param_values`` per packaged parameter, each sent
once with no retry; Quick Stats reports no quota left (``QUOTA_HEADER``). The frame's
``--only <list> [<list> ...]`` fetches the named lists alone and keeps every other file,
``columns.csv`` among them, and its ``--render-only`` writes the provenance rows from the
packaged files without a request and without a key.
"""

import csv
import io
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from functools import partial
from html.parser import HTMLParser
from pathlib import Path

from xippios.core import AsyncClient, PackagedList
from xippios.core.refresh import Listed, Lists, run

from xippios.usda.nass import api
from xippios.usda.nass._client import client
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "src/xippios/usda/nass/reference"
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


async def fetch_param(param: str) -> PackagedList:
    """A packaged parameter's values, fetched by one ``get_param_values`` call."""
    answer = await api.get_param_values(param)
    return PackagedList(
        param=param,
        endpoint="get_param_values",
        fetched=answer.retrieved_at,
        records=[{param: value} for value in answer.payload],
    )


class ColumnsCsv:
    """``columns.csv``, made from the snapshot's column table and written on a full run.

    The declaration's ``before`` hook parses the table before the first request, and its
    ``after`` hook writes the file once every list was fetched, so ``--only`` keeps it as it
    is.
    """

    def __init__(self) -> None:
        self.text: str | None = None

    def before(self) -> None:
        """Parse the snapshot's column table; a table the parser cannot read stops the run."""
        self.text = columns_csv(columns_from_snapshot())

    def after(self, written: Mapping[str, PackagedList]) -> None:
        """Write ``columns.csv`` once every list was fetched, else keep it as it is."""
        if self.text is None or set(written) != set(PACKAGED_PARAMS):
            return
        COLUMNS.write_text(self.text, encoding="utf-8", newline="")
        print("columns.csv rebuilt from docs/upstream/param_define.md")  # noqa: T201


COLUMNS_CSV = ColumnsCsv()

LISTS = Lists(
    package=PACKAGE,
    lists=tuple(
        Listed(
            param,
            partial(fetch_param, param),
            endpoint="get_param_values",
            origin=f"`GET /api/get_param_values?param={param}`",
        )
        for param in PACKAGED_PARAMS
    ),
    packaged=PACKAGED_PARAMS,
    client=client,
    quota_header=QUOTA_HEADER,
    before=COLUMNS_CSV.before,
    after=COLUMNS_CSV.after,
)
"""The nine packaged parameter lists as the frame fetches and writes them, none with an enum,
and ``columns.csv`` beside them through the two hooks (sdk-core ADR-0062)."""


@contextmanager
def read_timeout(target: AsyncClient) -> Iterator[None]:
    """``target`` for the block with the read timeout ``READ_TIMEOUT``, then as it was.

    The other timeouts and the retry stay ``target``'s; the frame sends each request once.
    Core builds the client's pool, and with it the timeouts, at the first request in an
    event loop: the run sends the script's first request, so its pool takes them.
    """
    configured = target.config
    target.config = replace(configured, read_timeout=READ_TIMEOUT)
    try:
        yield
    finally:
        target.config = configured


if __name__ == "__main__":
    with read_timeout(client):
        raise SystemExit(run(LISTS))
