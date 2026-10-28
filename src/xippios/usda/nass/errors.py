"""Quick Stats failure modes with a distinct, documented meaning (conventions §5)."""

from xippios.core import InvalidRequestError

from xippios.usda.nass._client import SOURCE

__all__ = ["RECORD_LIMIT", "QueryTooLarge"]

RECORD_LIMIT = 50_000
"""Most records ``api_GET`` returns for one query (``docs/upstream/api.md``)."""


class QueryTooLarge(InvalidRequestError):
    """The query would return more than Quick Stats' 50,000-record maximum (HTTP 422).

    Raised by ``get_data`` before fetching, from the count ``get_counts`` reports, for
    the whole query or, with ``split_by_year``, for the one year that alone is over the
    limit; and by the ``api_get`` wrapper when upstream answers HTTP 413
    ``exceeds limit=50000``.

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
                "statisticcat_desc, or split the query into several."
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
