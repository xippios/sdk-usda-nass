"""Refresh the upstream documentation snapshot in ``docs/upstream/`` (``/refresh-upstream``).

USDA NASS documents Quick Stats on two server-rendered HTML pages, and this script keeps
both as Markdown: the API page, https://quickstats.nass.usda.gov/api, as ``api.md``, its
four tabs (Introduction, Terms of Service, Usage, Request API Key) and the pop-ups of its
Usage tab (an example request, the column definitions, the operators) all in the page as
served, and the column definitions, https://quickstats.nass.usda.gov/param_define, as
``param_define.md``. ``reduce`` converts each page's ``div#indexbody`` with markdownify,
the page's chrome cut (``CHROME``) and the column-definitions table, whose dimension rows
span all three columns, kept as HTML (conventions §3). Quick Stats publishes no OpenAPI
document, and no page is JSON, so nothing is read with the frame's ``read_json``.

The script declares its snapshot, ``SNAPSHOT``, to core's frame, ``xippios.core.refresh``,
which fetches every page before it writes anything, checks the attribution, writes the
files and ``FETCHED.md`` and compares them in ``--check`` (conventions §3; sdk-core
ADR-0062). Every request goes through the package's own client,
``xippios.usda.nass._client.client``, so the documentation's host, the API's own, takes the
API's pace, and no page is a keyed sample, so the frame sends no key. The script's own code
is ``reduce`` and its declaration: the pages, the attribution, the words the attribution
check reads past (``VOCABULARY``) and how the pages are captured. ``reduce`` converts with
``markdownify``, the source's own dependency, pinned in the dev group of
``pyproject.toml``, since the script runs in the project's environment. No key is needed or
read. A run sends 2 requests, one a page, and the frame asks a page once more at most.
Run from the repository root::

    uv run python scripts/refresh_upstream.py            # fetch, then write the snapshot
    uv run python scripts/refresh_upstream.py --check    # fetch and compare; write nothing
"""

import html
from importlib.metadata import version
from pathlib import Path
from typing import Any

from markdownify import ATX, MarkdownConverter
from xippios.core.refresh import Page, Response, Snapshot, Statement, changed, decode, run

from xippios.usda.nass._client import client

ROOT = Path(__file__).resolve().parents[1]
DOCS_URL = "https://quickstats.nass.usda.gov/api"
"""Where the documentation lives: ``upstream_docs_url`` in ``.copier-answers.yml``."""

_NOTE = "converted to Markdown; the column-definitions table has merged cells and is kept as HTML"
PAGES: tuple[Page, ...] = (
    Page(DOCS_URL, "api.md", note=_NOTE),
    Page("https://quickstats.nass.usda.gov/param_define", "param_define.md", note=_NOTE),
)
"""Every page the snapshot records, in the order of ``FETCHED.md``'s rows."""

_TERMS = "the Terms of Service tab of the api page, and a copy in its key request form"
ATTRIBUTION: tuple[Statement, ...] = (
    Statement("NASS API Terms of Service", DOCS_URL, where=_TERMS),
    Statement(
        "This product uses the NASS API but is not endorsed or certified by NASS.",
        DOCS_URL,
        where="the notice the Attribution section of those terms asks every service to display",
    ),
)
"""Every copyright line, licence or terms of use the documentation states, as printed.

The api page prints the NASS API Terms of Service on its Terms of Service tab, and a copy
in its key request form, with the notice their Attribution section asks every service that
uses the API to display; param_define states none.
"""

VOCABULARY: tuple[str, ...] = (
    "Introduction Terms of Service Usage",
    "agree to the NASS Terms of Service",
    "Do you agree with Terms of Service?",
    "subject to your acceptance of the terms and conditions contained herein",
    "subject to the terms and conditions of this Agreement",
)
"""What the api page prints in which "Terms of Service" or "terms and conditions" states
nothing new, each in its context, as the frame's search reads the page's visible text.

The first three are its references to the recorded terms: the label of the Terms of
Service tab between the Introduction and Usage tabs of its tab menu, read from the tab's
markup, ``<div class="menu" ...> Terms of Service <br clear="all"> <br clear="all">
</div>``, which the first fetching run after the port confirms; the Introduction's "agree
to the NASS Terms of Service"; and the key form's question "Do you agree with Terms of
Service?". The last two are sentences of the terms themselves, which the frame's search
reads where the script's own check did not.
"""

CONTENT_ID = "indexbody"
"""The ``div`` each page keeps its documentation in; the masthead, the menu bar, the scripts
and the analytics tags sit outside it."""

CHROME: tuple[tuple[str, dict[str, str]], ...] = (
    ("div", {"class": "nav"}),
    ("div", {"id": "close"}),
    ("form", {}),
    ("head", {}),
)
"""What ``reduce`` cuts inside ``CONTENT_ID``, as a tag and its attributes.

The api page's tab menu (Introduction, Terms of Service, Usage, Request API Key), the
Close(X) control of every pop-up, the key request form (its fields, its agreement question
and a copy of the terms, which ``reduce`` first checks against the Terms of Service tab)
and the head of the Word document both pages embed, its styles and metadata.
"""

HTML_TABLES = {"api.md": 1, "param_define.md": 1}
"""How many tables each file keeps as HTML, the ones with merged cells (conventions §3).

``reduce`` stops the run on any other count, so the rows' notes stay true.
"""


def _text(element: Any) -> str:
    """The text of a BeautifulSoup element, its whitespace collapsed."""
    return " ".join(element.get_text("").split())


def _merged(table: Any) -> bool:
    """Whether a table has a merged cell or a table nested in it, which a pipe table loses."""
    cells = table.find_all(["td", "th"])
    spans = any(cell.get(name, "1") != "1" for cell in cells for name in ("colspan", "rowspan"))
    return spans or table.find("table") is not None


def _html_table(url: str, table: Any) -> str:
    """A table with merged cells as HTML: its rows, its cells with their spans and text."""
    lines = ["<table>"]
    for row in table.find_all("tr"):
        cells = []
        for cell in row.find_all(["td", "th"], recursive=False):
            if cell.find(["a", "img", "table", "ul", "ol"]) is not None:
                raise changed(url, "a cell of the table with merged cells holds more than text")
            spans = "".join(
                f' {name}="{html.escape(cell[name])}"'
                for name in ("colspan", "rowspan")
                if cell.get(name, "1") != "1"
            )
            text = html.escape(_text(cell), quote=False)
            cells.append(f"<{cell.name}{spans}>{text}</{cell.name}>")
        lines.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join([*lines, "</table>"])


class _Converter(MarkdownConverter):
    """markdownify, the chrome cut and a table with merged cells kept as HTML.

    The stub markdownify ships declares ``convert`` and ``convert_soup``; the elements it
    hands to a ``convert_<tag>`` hook are BeautifulSoup's, typed ``Any`` here, and so is its
    own ``convert_table``, reached through ``super()``.
    """

    def __init__(self, url: str) -> None:
        super().__init__(heading_style=ATX, bullets="-", escape_underscores=False)
        self.url = url
        self.html_tables = 0

    def convert_soup(self, soup: Any) -> str:
        """Convert the page's ``CONTENT_ID`` without ``CHROME``."""
        root = soup.find("div", id=CONTENT_ID)
        if root is None:
            raise changed(self.url, f"there is no div#{CONTENT_ID}")
        copy, terms = root.find("div", id="tos"), root.find("div", id="disclaim")
        if copy is not None and (
            terms is None or _text(copy).removeprefix("Close(X)").strip() != _text(terms)
        ):
            raise changed(self.url, "the key form's copy of the terms is not the terms tab's")
        for name, attrs in CHROME:
            for element in root.find_all(name, attrs=attrs):
                element.decompose()
        return super().convert_soup(root)

    def convert_table(self, el: Any, text: str, parent_tags: set[str]) -> str:
        """A pipe table, as markdownify makes it, or HTML where a cell is merged."""
        if not _merged(el):
            base: Any = super()
            pipe: str = base.convert_table(el, text, parent_tags)
            return pipe
        self.html_tables += 1
        return "\n\n" + _html_table(self.url, el) + "\n\n"


def _tidy(markdown: str) -> str:
    """Outside fenced code: no trailing whitespace, no run of blank lines; one final newline.

    markdownify marks a line break (``<br>``) with two trailing spaces, so a break becomes a
    plain newline, and the pages' runs of breaks become one blank line.
    """
    lines: list[str] = []
    fenced = False
    for line in markdown.strip().split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            line = line.rstrip()
            if not line and (not lines or not lines[-1]):
                continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def reduce(page: Page, response: Response) -> bytes:
    """``page``'s HTML as Markdown: its ``CONTENT_ID`` through markdownify (``_Converter``).

    The run stops with ``changed``, before anything is written, when the page has no
    ``CONTENT_ID``, when the key form's copy of the terms is not the Terms of Service tab's,
    or when the file would keep another number of HTML tables than ``HTML_TABLES`` says.
    """
    converter = _Converter(page.url)
    markdown = converter.convert(decode(response))
    expected = HTML_TABLES.get(page.file or "", 0)
    if converter.html_tables != expected:
        found = converter.html_tables
        raise changed(page.url, f"{found} tables with merged cells, where {expected} were known")
    return _tidy(markdown).encode("utf-8")


CAPTURE = (
    "Both pages are server-rendered HTML; the api page's four tabs and the pop-ups of its "
    "Usage tab are all in the page as served and shown by script. Each page's "
    f"`div#indexbody` is converted to Markdown with markdownify {version('markdownify')} "
    f"(Beautiful Soup {version('beautifulsoup4')}, html.parser), headings, lists, code and "
    "tables kept and underscores left unescaped, so that names read as upstream writes "
    "them. The masthead, the menu bar and the scripts outside it are left out, and so are, "
    "inside it, the api page's tab menu, the pop-ups' Close(X) controls, the key request "
    "form (its fields, its agreement question and a copy of the terms, which the script "
    "checks against the Terms of Service tab) and the head of the Word document both pages "
    "embed. The column-definitions table, which the api page embeds whole from param_define, "
    "has merged cells, its four dimension rows spanning all three columns, so both files "
    "keep it as HTML (conventions §3): its rows, and its cells with their colspan and their "
    "text, whitespace collapsed and Word's styling left out.\n\n"
    "The attribution check reads a page's visible text, so the 2008 copyright footer that "
    "both pages keep commented out is not recorded as stated. It reads past the api page's "
    "three references to the recorded terms, its tab menu's label, the Introduction's "
    "agreement and the key form's question, and past two sentences of the terms that say "
    "terms and conditions, none of which states anything new."
)
"""``FETCHED.md``'s "How this is captured": what is converted, cut or left out, and why."""

SNAPSHOT = Snapshot(
    name="USDA NASS Quick Stats",
    slug="usda-nass",
    pages=PAGES,
    attribution=ATTRIBUTION,
    vocabulary=VOCABULARY,
    capture=CAPTURE,
    out=ROOT / "docs/upstream",
    reduce=reduce,
    client=client,
)
"""The snapshot, as core's frame runs it through the package's client (sdk-core ADR-0062)."""


if __name__ == "__main__":
    raise SystemExit(run(SNAPSHOT))
