"""``GET /api/api_GET``: published estimates for a set of filters.

Reference: ``docs/upstream/api.md``, resource 1. Observed on 2026-10-22, beyond the
documentation: a query over the 50,000-record maximum answers HTTP 413
``{"error": ["exceeds limit=50000"]}``, and filters that match no record answer HTTP 400
``{"error": ["bad request - invalid query"]}`` rather than an empty list.
"""

from typing import Any

import httpx
from xippios.core import NotFoundError, ValidationError, parse
from xippios.core.errors import BODY_LIMIT, raise_for_status

from xippios.usda.nass._client import SOURCE, client
from xippios.usda.nass.errors import QueryTooLarge
from xippios.usda.nass.models import ApiGetResponse, Filters

__all__ = ["api_GET"]

_NO_MATCH = "bad request - invalid query"


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ValidationError(
            f"{SOURCE}: api_GET answered with something other than JSON",
            raw=response.text[:BODY_LIMIT],
            source=SOURCE,
        ) from exc


def _error_text(response: httpx.Response) -> str:
    try:
        errors = response.json().get("error", [])
    except (ValueError, AttributeError):
        return ""
    return "; ".join(str(item) for item in errors)


async def api_GET(filters: Filters) -> ApiGetResponse:
    """Call ``api_GET`` with Quick Stats filter parameters, as upstream names them.

    Args:
        filters: Column names, optionally suffixed with an operator, mapped to values,
            e.g. ``{"commodity_desc": "CORN", "year": 2012, "state_alpha": "VA"}``.
            ``format`` is always JSON.

    Raises:
        QueryTooLarge: Upstream refused the query as over the 50,000-record maximum.
        NotFoundError: No record matches the filters.
    """
    params = {**dict(filters), "format": "JSON"}
    response = await client.request("GET", "/api_GET/", params=params, raise_on_error=False)
    if response.status_code == 413:
        raise QueryTooLarge(None)
    if response.status_code == 400 and _error_text(response) == _NO_MATCH:
        raise NotFoundError(
            f"no Quick Stats record matches these filters (upstream: {_NO_MATCH})",
            source=SOURCE,
        )
    raise_for_status(response, source=SOURCE)
    return parse(ApiGetResponse, _json(response), source=SOURCE, endpoint="api_GET")
