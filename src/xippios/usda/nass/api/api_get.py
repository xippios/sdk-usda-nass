"""``GET /api/api_GET``: published estimates for a set of filters.

Reference: ``docs/upstream/api.md``, resource 1. Upstream's error shapes (HTTP 413 over the
record limit, HTTP 400 for filters matching nothing) are mapped once in
``xippios.usda.nass._client.classify``.
"""

from xippios.core import parse

from xippios.usda.nass._client import SOURCE, client
from xippios.usda.nass.models import ApiGetResponse, Filters

__all__ = ["api_get"]


async def api_get(filters: Filters) -> ApiGetResponse:
    """Call ``api_GET`` with Quick Stats filter parameters, as upstream names them.

    Args:
        filters: Column names, optionally suffixed with an operator, mapped to values,
            e.g. ``{"commodity_desc": "CORN", "year": 2012, "state_alpha": "VA"}``.
            ``format`` is always JSON.

    Raises:
        QueryTooLarge: Upstream refused the query as over the 50,000-record maximum.
        NotFoundError: No record matches the filters.
    """
    raw = await client.get_json("/api_GET/", params={**dict(filters), "format": "JSON"})
    return parse(ApiGetResponse, raw, source=SOURCE, endpoint="api_GET")
