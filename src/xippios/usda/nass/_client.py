"""The package's one configured ``AsyncClient``, its error mapping and its cache (conventions §6).

The client keeps core's bounded memory cache with a lifetime per path prefix, one prefix
here: a ``get_param_values`` answer is kept for a day in the process, and a lookup within it
sends nothing; ``api_GET`` and ``get_counts`` match no prefix and are never kept (sdk-core
ADR-0040). A cached answer's ``retrieved_at`` is the time it was stored, which
``get_answer`` reads, and an answer is stored only once ``get_answer`` parsed it (sdk-core
ADR-0037, decision 5; conventions §4).
"""

from typing import Any

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    EnvVar,
    KeyAuth,
    MemoryCache,
    NotFoundError,
    RateLimit,
    XippiosError,
    request_description,
)

from xippios.usda.nass._version import __version__

SOURCE = "usda-nass"
BASE_URL = "https://quickstats.nass.usda.gov/api"
API_KEY_ENV = "NASS_API_KEY"  # pragma: allowlist secret (a variable name, not a key)
ENV_VARS: tuple[EnvVar, ...] = (EnvVar(API_KEY_ENV, secret=True, required=True),)
"""The variables the package reads, for a host (conventions §7; sdk-core ADR-0026, amendment
2026-11-18, point c). An ``EnvVar`` names a variable and reads none; a variable the source reads
beside these joins the list."""
# A self-imposed pace: upstream documents no per-second or per-minute limit (sdk-core ADR-0033
# decision 1).
RATE_LIMIT = RateLimit(per_minute=30, burst=1)

_NO_MATCH = "bad request - invalid query"

# The path as the cache's prefixes see it: the base URL's ``/api``, then the wrapper's path.
_LIST_PATH = "/api/get_param_values/"
# A parameter's values change rarely: a list is kept for a day, then fetched again.
_LIST_TTL = 24 * 60 * 60.0


def _payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def classify(response: httpx.Response) -> XippiosError | None:
    """Quick Stats' documented and observed error shapes, mapped once (sdk-core ADR-0031).

    Observed on 2026-10-22 beyond ``docs/upstream/api.md``: a query over the 50,000-record
    maximum answers HTTP 413 ``{"error": ["exceeds limit=50000"]}``; filters that match no
    record answer HTTP 400 ``{"error": ["bad request - invalid query"]}``; an unknown
    ``get_param_values`` parameter answers HTTP 400 ``{"<param>": ["no value"]}``.
    """
    if response.status_code == 413:
        from xippios.usda.nass.errors import QueryTooLarge

        return QueryTooLarge(None, request=request_description(response))
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
    # Core's default bounds hold: 256 entries outnumber the 39 Quick Stats columns,
    # and ``cache_max_bytes`` (8 MiB) is far above the lists measured (``domain_desc``,
    # 22,194 bytes of compact JSON, the largest; ``commodity_desc``, a list fetched live,
    # 6,792 bytes as recorded on 2026-10-28); a larger answer is returned and not kept.
    cache=MemoryCache(lifetimes={_LIST_PATH: _LIST_TTL}),
    classify=classify,
)
# The key is read from the environment on the first request, never at import.
auth = KeyAuth(API_KEY_ENV, location="query", name="key", source=SOURCE)
client = AsyncClient(config, auth=auth)

__all__ = [
    "API_KEY_ENV",
    "BASE_URL",
    "ENV_VARS",
    "RATE_LIMIT",
    "SOURCE",
    "auth",
    "classify",
    "client",
    "config",
]
