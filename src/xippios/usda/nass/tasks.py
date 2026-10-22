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
from xippios.usda.nass.models import Filters

__all__ = ["get_counts"]


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
