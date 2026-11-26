"""``GET /api/get_counts``: how many records a set of filters would return.

Reference: ``docs/upstream/api.md``, resource 3. ``api_GET`` returns at most 50,000
records, so upstream recommends this call before fetching. The wrapper reads through
``AsyncClient.get_answer``, the client's one reader of JSON (sdk-core ADR-0037).
"""

from xippios.core import Answer

from xippios.usda.nass._client import client
from xippios.usda.nass.models import Filters, GetCountsResponse

__all__ = ["get_counts"]


async def get_counts(filters: Filters) -> Answer[GetCountsResponse]:
    """Call ``get_counts`` with Quick Stats filter parameters, as upstream names them.

    Args:
        filters: Column names, optionally suffixed with an operator, mapped to values,
            e.g. ``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``.

    Returns:
        The parsed count with ``retrieved_at``, timezone-aware UTC, the time it arrived;
        a task's ``ResultMeta.retrieved_at``.
    """
    answer: Answer[GetCountsResponse] = await client.get_answer(
        "/get_counts/", params=dict(filters), parse=GetCountsResponse, endpoint="get_counts"
    )
    return answer
