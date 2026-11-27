"""The package's one configured ``AsyncClient``, its error mapping and its cache (conventions §6).

The client keeps core's bounded memory cache with a lifetime per path prefix, since Quick
Stats serves public data to a read-only client (conventions §6; sdk-core ADR-0061, decision
11): a ``get_param_values`` answer is kept for a day in the process, and an answer of
``get_counts`` or ``api_GET`` for 300 seconds, by the maintainer's decision of 2026-11-26. A
lookup, a count or a query repeated within its lifetime sends nothing, a split's yearly
counts and data among them, so a year that Quick Stats publishes within those 300 seconds
reads as none until its entry expires. A body over ``cache_max_bytes``, core's 8 MiB, passes
unstored, as a year of data can (sdk-core ADR-0040). A cached answer's ``retrieved_at`` is
the time it was stored, which ``get_answer`` reads, and an answer is stored only once
``get_answer`` parsed it (sdk-core ADR-0037, decision 5; conventions §4).
"""

from typing import Any

import httpx
from xippios.core import (
    AsyncClient,
    ClientConfig,
    EnvVar,
    InvalidRequestError,
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

# The paths as the cache's prefixes see them: the base URL's ``/api``, then the wrapper's.
_LIST_PATH = "/api/get_param_values/"
# A parameter's values change rarely: a list is kept for a day, then fetched again.
_LIST_TTL = 24 * 60 * 60.0
_COUNT_PATH = "/api/get_counts/"
_DATA_PATH = "/api/api_GET/"
# A count and the data it counts are kept as long as each other, so a repeated query reads
# its count and its records from one moment of upstream's.
_DATA_TTL = 300.0


def _payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _no_value(param: str, request: str) -> XippiosError:
    """Quick Stats' HTTP 400 ``{"<param>": ["no value"]}``, by the name it answers.

    A name that no column of the packaged table holds is upstream's refusal of the call as
    given, an ``InvalidRequestError`` (conventions §5; sdk-core ADR-0007, amendment
    2026-11-18, point b). A column of the table that upstream lists no values of is a code
    the packaged table holds and upstream's live answer lacks, a ``NotFoundError``.
    """
    # Imported here, as ``QueryTooLarge`` is: ``params`` imports ``SOURCE`` from this module.
    from xippios.usda.nass.params import columns

    if any(column.column == param for column in columns()):
        return NotFoundError(
            f"Quick Stats lists no values of the column {param!r}: {request} answered HTTP 400 "
            'with "no value"',
            source=SOURCE,
        )
    return InvalidRequestError(
        f'{param!r} is not a Quick Stats column: {request} answered HTTP 400 with "no value"',
        source=SOURCE,
    )


def classify(response: httpx.Response) -> XippiosError | None:
    """Quick Stats' error shapes, mapped once (sdk-core ADR-0031).

    The three error answers as Quick Stats sends them, beyond the messages that
    ``docs/upstream/api.md`` lists, stand in ``docs/upstream/OBSERVED.md`` under
    "Error answers": HTTP 413 ``{"error": ["exceeds limit=50000"]}`` is ``QueryTooLarge``,
    HTTP 400 ``{"error": ["bad request - invalid query"]}`` from filters that match no record
    a ``NotFoundError``, and HTTP 400 ``{"<param>": ["no value"]}`` from ``get_param_values``
    an ``InvalidRequestError`` naming the parameter where the packaged column table lacks
    it, else a ``NotFoundError`` naming the column (``_no_value``). Each error names the
    request by core's ``request_description``, its method and path, never its host or its
    query, which carries the key (conventions §5; sdk-core ADR-0030).
    """
    request = request_description(response)
    if response.status_code == 413:
        from xippios.usda.nass.errors import QueryTooLarge

        return QueryTooLarge(None, request=request)
    if response.status_code == 400:
        payload = _payload(response)
        if isinstance(payload, dict):
            if payload.get("error") == [_NO_MATCH]:
                return NotFoundError(
                    f"no Quick Stats record matches the filters of {request} (upstream: "
                    f"{_NO_MATCH})",
                    source=SOURCE,
                )
            missing = [name for name, value in payload.items() if value == ["no value"]]
            if missing:
                return _no_value(missing[0], request)
    return None


config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
    # Core's default bounds hold: 256 entries outnumber the 39 Quick Stats columns and a
    # split's 41 answers, and ``cache_max_bytes`` (8 MiB) is far above the longest list
    # (``docs/upstream/OBSERVED.md``, "The lists' lengths"); a larger answer, of about 9,000
    # records or more ("A record is about 900 bytes"), is returned and not kept.
    cache=MemoryCache(
        lifetimes={_LIST_PATH: _LIST_TTL, _COUNT_PATH: _DATA_TTL, _DATA_PATH: _DATA_TTL}
    ),
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
