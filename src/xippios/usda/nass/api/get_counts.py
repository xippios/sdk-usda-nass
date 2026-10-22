"""``GET /api/get_counts``: how many records a set of filters would return.

Reference: ``docs/upstream/api.md``, resource 3. ``api_GET`` returns at most 50,000
records, so upstream recommends this call before fetching.
"""

from xippios.core import parse

from xippios.usda.nass._client import SOURCE, client
from xippios.usda.nass.models import Filters, GetCountsResponse

__all__ = ["get_counts"]


async def get_counts(filters: Filters) -> GetCountsResponse:
    """Call ``get_counts`` with Quick Stats filter parameters, as upstream names them.

    Args:
        filters: Column names, optionally suffixed with an operator, mapped to values,
            e.g. ``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``.
    """
    raw = await client.get_json("/get_counts/", params=dict(filters))
    return parse(GetCountsResponse, raw, source=SOURCE, endpoint="get_counts")
