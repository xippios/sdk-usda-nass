"""Quick Stats failure modes with a distinct, documented meaning (conventions §5)."""

from xippios.core import QueryTooLarge as CoreQueryTooLarge

from xippios.usda.nass._client import SOURCE

__all__ = [
    "COUNTS_SENT",
    "COUNT_SENT",
    "MCP_SPLIT_YEARS",
    "NARROW",
    "RECORD_LIMIT",
    "SPLIT_CEILING",
    "QueryTooLarge",
]

RECORD_LIMIT = 50_000
"""Most records ``api_GET`` returns for one query (``docs/upstream/api.md``)."""

SPLIT_CEILING = 20
"""Most years one ``get_data(split_by_year=True)`` call splits into in Python and over HTTP.

A task that assembles a period series states its ceiling (conventions §4). A split of
more years is refused before its first yearly count: a two-sided range before any call,
``year__GE`` alone after its first count; a range one call serves whole is not split. No
ceiling goes above it (``tasks.SPLIT``, core's ``Ceiling``).
"""

MCP_SPLIT_YEARS = 11
"""The split ceiling the entry point ``xippios-usda-nass-mcp`` starts the MCP server with.

Eleven years, the most whose split stays within the about two dozen requests that one tool
call may spend before the client's retries (conventions §8): two keyed requests a year, a
count and the data, so 22 for a two-sided range and 23 for ``year__GE`` alone, whose range
is counted first. Its ``--split-years`` sets another, from 1 to ``SPLIT_CEILING``
(``tasks.mcp_add_options``, ``tasks.mcp_apply_options``).
"""

NARROW = (
    "Narrow the filters, for example by year, state_alpha, agg_level_desc or "
    "statisticcat_desc, or call get_data with split_by_year=True (over MCP, the tool "
    f"usda_nass_get_data) on a bounded year range of at most {SPLIT_CEILING} years in Python "
    f"and over HTTP, {MCP_SPLIT_YEARS} by default on the MCP server (--split-years)."
)
"""What narrows a whole query over the limit, the sentences that end its refusal (§8)."""

COUNT_SENT = "The count was sent, and no record was asked for."
"""What a refusal after the count of a whole query says was sent (conventions §5)."""

COUNTS_SENT = "Only counts were sent, and no record was asked for."
"""What a refusal of one year over the limit says was sent: its count, after any count of
the call before it, which a split's refusal names by the years answered (conventions §5)."""


class QueryTooLarge(CoreQueryTooLarge):
    """The query would return more than Quick Stats' 50,000-record maximum (HTTP 422).

    Core's class, which words the message (sdk-core ADR-0053), kept as a subclass for
    ``year``. Raised by ``get_data`` before fetching, from the count ``get_counts``
    reports, for the whole query or, with ``split_by_year``, for the one year that alone
    is over the limit; and by ``classify`` when upstream answers HTTP 413 ``exceeds
    limit=50000``, naming the request it refused. A refusal from a count says what was
    sent after its first sentence, ``COUNT_SENT`` for the whole query and ``COUNTS_SENT``
    for a year, and upstream's HTTP 413, which refused the data request itself, names that
    request alone (conventions §5). The message for the whole query ends with ``NARROW``,
    narrower filters or a split by year; the one for a year names narrower filters only.
    The hint is static: it names the defaults, not a ceiling set for the process.

    Args:
        count: Records the query, or the year, would return, e.g. ``85_535``; ``None``
            for upstream's HTTP 413, which names no count.
        year: The year that alone is over the limit, when ``split_by_year`` found one,
            e.g. ``2021``; ``None`` otherwise.
        request: The request upstream refused, as ``request_description(response)``
            gives it, ``"GET /api/api_GET/"``, for the error ``classify`` maps; ``None``
            for a refusal before the data request.

    Attributes:
        count: As given.
        limit: The upstream maximum, ``RECORD_LIMIT``.
        narrow: The sentences that end the message.
        year: As given.
        request: As given.
    """

    def __init__(
        self, count: int | None, *, year: int | None = None, request: str | None = None
    ) -> None:
        if year is not None:
            narrow = (
                f"Year {year} alone is over the limit, so split_by_year cannot fetch it. "
                f"{COUNTS_SENT} Narrow the filters, for example by state_alpha, "
                "agg_level_desc or statisticcat_desc."
            )
        elif count is not None:
            narrow = f"{COUNT_SENT} {NARROW}"
        else:
            narrow = NARROW
        super().__init__(count, limit=RECORD_LIMIT, narrow=narrow, request=request, source=SOURCE)
        self.year = year
