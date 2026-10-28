"""The package's one configured ``AsyncClient``, its error mapping and its cache (conventions §6).

The client keeps one bounded memory cache, for the list lookups alone: a
``get_param_values`` answer is kept for 24 hours in the process, and a lookup within them
sends nothing; ``api_GET`` and ``get_counts`` are never cached. A cached answer's
``retrieved_at`` is the time it was stored, which ``get_answer`` reads (ADR-0015,
decision 5; conventions §4).
"""

from typing import Any

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    MemoryCache,
    NotFoundError,
    QueryKeyAuth,
    RateLimit,
    XippiosError,
)

from xippios.usda.nass._version import __version__

SOURCE = "usda-nass"
BASE_URL = "https://quickstats.nass.usda.gov/api"
API_KEY_ENV = "NASS_API_KEY"  # pragma: allowlist secret (a variable name, not a key)
# A self-imposed pace: upstream documents no per-second or per-minute limit (ADR-0010 decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)

_NO_MATCH = "bad request - invalid query"

# The path as the cache filter sees it: the base URL's ``/api``, then the wrapper's path.
_LIST_PATH = "/api/get_param_values/"
# A parameter's values change rarely: a list is kept for a day, then fetched again.
_LIST_TTL = 24 * 60 * 60.0


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


def _list_lookup(request: httpx.Request) -> bool:
    """The cache's filter: a ``get_param_values`` request, and no other."""
    return request.url.path == _LIST_PATH


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    # Core's default bounds hold: 256 entries outnumber the 39 Quick Stats columns,
    # and ``cache_max_bytes`` (8 MiB) is far above the lists measured (``domain_desc``,
    # 22,194 bytes of compact JSON, the largest); a larger answer is returned and not kept.
    cache=MemoryCache(ttl=_LIST_TTL),
    cache_filter=_list_lookup,
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
