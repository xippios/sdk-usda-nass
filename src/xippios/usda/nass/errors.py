"""Quick Stats failure modes with a distinct, documented meaning (conventions §5)."""

from xippios.core import XippiosError

from xippios.usda.nass._client import SOURCE

__all__ = ["RECORD_LIMIT", "QueryTooLarge"]

RECORD_LIMIT = 50_000
"""Most records ``api_GET`` returns for one query (``docs/upstream/api.md``)."""


class QueryTooLarge(XippiosError):
    """The query would return more than Quick Stats' 50,000-record maximum.

    Raised by ``get_data`` before fetching, from the count ``get_counts`` reports, and by
    the ``api_GET`` wrapper when upstream answers HTTP 413 ``exceeds limit=50000``.

    Attributes:
        count: Records the query would return, when known.
        limit: The upstream maximum.
    """

    def __init__(self, count: int | None, *, limit: int = RECORD_LIMIT) -> None:
        size = f"{count:,} records" if count is not None else "more records than allowed"
        super().__init__(
            f"query would return {size}; Quick Stats serves at most {limit:,} per call. "
            "Narrow the filters, for example by year, state_alpha, agg_level_desc or "
            "statisticcat_desc, or split the query into several.",
            source=SOURCE,
        )
        self.count = count
        self.limit = limit
