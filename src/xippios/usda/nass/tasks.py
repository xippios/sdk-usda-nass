"""Task-shaped functions for USDA NASS Quick Stats.

The public API (ADR-0001, layer 2). A task composes endpoint wrappers from ``api/``,
resolves pagination and reference lookups, and returns ``Result[T]`` with full
``ResultMeta``. Write the async version, derive the sync one with ``xippios.core.sync``,
and list the sync name in ``__all__``: the MCP server and the HTTP router register
exactly what is named there.

Docstrings are read by agents: one sentence first, then ``Args:`` with examples of
valid values for every parameter. ``/add-endpoint`` walks through the whole recipe.
"""

from xippios.core import Result, ResultMeta, sync

from xippios.usda.nass import api
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.errors import RECORD_LIMIT, QueryTooLarge
from xippios.usda.nass.models import Filters, QuickStatsRecord

__all__ = ["get_counts", "get_data"]


async def get_counts_async(filters: Filters) -> Result[int]:
    """Count the Quick Stats records a set of filters would return, before fetching them.

    ``api_GET`` returns at most 50,000 records; check the count first and narrow the
    filters when it is higher.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values. Columns are the What, Where and When dimensions, for example
            ``commodity_desc`` (``"CORN"``), ``statisticcat_desc`` (``"AREA PLANTED"``),
            ``agg_level_desc`` (``"STATE"``, ``"COUNTY"``), ``state_alpha`` (``"VA"``),
            ``year`` (``2012``), ``freq_desc`` (``"ANNUAL"``). Operators are suffixes:
            ``__LE``, ``__LT``, ``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``,
            so ``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``
            counts corn records for Virginia from 2012 on.
    """
    response = await api.get_counts(filters)
    meta = ResultMeta(source=SOURCE, endpoint="get_counts", request=dict(filters))
    return Result(data=response.count, meta=meta)


get_counts = sync(get_counts_async)


async def get_data_async(filters: Filters) -> Result[list[QuickStatsRecord]]:
    """Fetch published Quick Stats estimates for a set of filters, up to 50,000 records.

    Calls ``get_counts`` first: a count of zero returns an empty result without a second
    call, and a count above 50,000 raises ``QueryTooLarge`` with the count and a hint to
    narrow, before anything is fetched. Each record carries every Quick Stats column;
    ``value`` is the published figure as a string (``"510,000"``, or a suppression code
    such as ``"(D)"``) and ``value_number`` the parsed number.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values; the same shape as for ``get_counts``. A query that stays well under
            the limit names the commodity, the statistic, the level and the time, e.g.
            ``{"commodity_desc": "CORN", "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE", "state_alpha": "VA", "year": 2012}``.
    """
    count = (await api.get_counts(filters)).count
    meta = ResultMeta(source=SOURCE, endpoint="api_GET", request=dict(filters))
    if count == 0:
        return Result(data=[], meta=meta)
    if count > RECORD_LIMIT:
        raise QueryTooLarge(count)
    response = await api.api_GET(filters)
    return Result(data=response.data, meta=meta)


get_data = sync(get_data_async)
