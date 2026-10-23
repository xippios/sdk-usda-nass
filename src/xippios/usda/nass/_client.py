"""The configured ``xippios.core`` client for USDA NASS Quick Stats.

One ``AsyncClient`` for the whole package: task functions share its rate limiter and
cache, and the same instance serves the sync facades and the MCP server.
"""

from typing import Any

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    NotFoundError,
    QueryKeyAuth,
    RateLimit,
    XippiosError,
)

from xippios.usda.nass._version import __version__

SOURCE = "usda-nass"
BASE_URL = "https://quickstats.nass.usda.gov/api"
API_KEY_ENV = "NASS_API_KEY"  # pragma: allowlist secret (a variable name, not a key)
RATE_LIMIT = RateLimit(per_minute=30)

_NO_MATCH = "bad request - invalid query"


def _payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def classify(response: httpx.Response) -> XippiosError | None:
    """Quick Stats' documented and observed error shapes, mapped once (ADR-0008).

    Observed on 2026-10-22 beyond ``docs/upstream/api.md``: a query over the 50,000-record
    maximum answers HTTP 413 ``{"error": ["exceeds limit=50000"]}``; filters that match no
    record answer HTTP 400 ``{"error": ["bad request - invalid query"]}``; an unknown
    ``get_param_values`` parameter answers HTTP 400 ``{"<param>": ["no value"]}``.
    """
    if response.status_code == 413:
        from xippios.usda.nass.errors import QueryTooLarge

        return QueryTooLarge(None)
    if response.status_code == 400:
        payload = _payload(response)
        if isinstance(payload, dict):
            if payload.get("error") == [_NO_MATCH]:
                return NotFoundError(
                    f"no Quick Stats record matches these filters (upstream: {_NO_MATCH})",
                    source=SOURCE,
                )
            missing = [name for name, value in payload.items() if value == ["no value"]]
            if missing:
                return NotFoundError(f"Quick Stats has no parameter {missing[0]!r}", source=SOURCE)
    return None


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    classify=classify,
)
# The key is read from the environment on the first request, never at import.
auth = QueryKeyAuth("key", API_KEY_ENV, source=SOURCE)
client = AsyncClient(config, auth=auth)

__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "RATE_LIMIT",
    "SOURCE",
    "auth",
    "classify",
    "client",
    "config",
]
