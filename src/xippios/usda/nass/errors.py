"""Quick Stats failure modes with a distinct, documented meaning (conventions §5)."""

from xippios.core import InvalidRequestError

from xippios.usda.nass._client import SOURCE

__all__ = ["RECORD_LIMIT", "SPLIT_CEILING", "QueryTooLarge"]

RECORD_LIMIT = 50_000
"""Most records ``api_GET`` returns for one query (``docs/upstream/api.md``)."""

SPLIT_CEILING = 20
"""Most years one ``get_data(split_by_year=True)`` call covers, this package's ceiling.

A task that assembles a period series states its ceiling (conventions §4); a longer
range is refused before any call.
"""


class QueryTooLarge(InvalidRequestError):
    """The query would return more than Quick Stats' 50,000-record maximum (HTTP 422).

    Raised by ``get_data`` before fetching, from the count ``get_counts`` reports, for
    the whole query or, with ``split_by_year``, for the one year that alone is over the
    limit; and by the ``api_get`` wrapper when upstream answers HTTP 413
    ``exceeds limit=50000``. The message for the whole query names the way through the
    limit: narrower filters, or ``get_data`` with ``split_by_year=True`` on a bounded
    year range of at most ``SPLIT_CEILING`` years; the one for a year names narrower
    filters only.

    Attributes:
        count: Records the query, or the year, would return, when known.
        limit: The upstream maximum.
        year: The year that alone is over the limit, when ``split_by_year`` found one;
            ``None`` otherwise.
    """

    def __init__(
        self, count: int | None, *, limit: int = RECORD_LIMIT, year: int | None = None
    ) -> None:
        size = f"{count:,} records" if count is not None else "more records than allowed"
        if year is None:
            message = (
                f"query would return {size}; Quick Stats serves at most {limit:,} per call. "
                "Narrow the filters, for example by year, state_alpha, agg_level_desc or "
                "statisticcat_desc, or call get_data with split_by_year=True (over MCP, the "
                f"tool usda_nass_get_data) on a bounded year range of at most {SPLIT_CEILING} "
                "years."
            )
        else:
            message = (
                f"year {year} alone would return {size}; Quick Stats serves at most "
                f"{limit:,} per call, so split_by_year cannot fetch it. Narrow the filters, "
                "for example by state_alpha, agg_level_desc or statisticcat_desc."
            )
        super().__init__(message, source=SOURCE)
        self.count = count
        self.limit = limit
        self.year = year
