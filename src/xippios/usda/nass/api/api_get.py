"""``GET /api/api_GET``: published estimates for a set of filters.

Reference: ``docs/upstream/api.md``, resource 1. Upstream's error shapes (HTTP 413 over the
record limit, HTTP 400 for filters matching nothing) are mapped once in
``xippios.usda.nass._client.classify``. The wrapper reads through
``AsyncClient.get_answer``, the client's one reader of JSON, which parses the payload and
says when the answer was retrieved (sdk-core ADR-0037; conventions §4 and §6).
"""

from xippios.core import Answer

from xippios.usda.nass._client import client
from xippios.usda.nass.models import ApiGetResponse, Filters

__all__ = ["api_get"]


async def api_get(filters: Filters) -> Answer[ApiGetResponse]:
    """Call ``api_GET`` with Quick Stats filter parameters, as upstream names them.

    Args:
        filters: Column names, optionally suffixed with an operator, mapped to values,
            e.g. ``{"commodity_desc": "CORN", "year": 2012, "state_alpha": "VA"}``.
            ``format`` is always JSON.

    Returns:
        The parsed answer with ``retrieved_at``, timezone-aware UTC, the time it arrived;
        a task's ``ResultMeta.retrieved_at``.

    Raises:
        QueryTooLarge: Upstream refused the query as over the 50,000-record maximum.
        NotFoundError: No record matches the filters.
    """
    answer: Answer[ApiGetResponse] = await client.get_answer(
        "/api_GET/",
        params={**dict(filters), "format": "JSON"},
        parse=ApiGetResponse,
        endpoint="api_GET",
    )
    return answer
