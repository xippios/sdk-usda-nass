"""The configured ``xippios.core`` client for USDA NASS Quick Stats.

One ``AsyncClient`` for the whole package: task functions share its rate limiter and
cache, and the same instance serves the sync facades and the MCP server.
"""

from xippios.core import AsyncClient, ClientConfig, QueryKeyAuth, RateLimit

from xippios.usda.nass._version import __version__

SOURCE = "usda-nass"
BASE_URL = "https://quickstats.nass.usda.gov/api"
API_KEY_ENV = "NASS_API_KEY"  # pragma: allowlist secret (a variable name, not a key)
RATE_LIMIT = RateLimit(per_minute=30)

config = ClientConfig(
    source=SOURCE,
    version=__version__,
    base_url=BASE_URL,
    rate_limit=RATE_LIMIT,
)
# The key is read from the environment on the first request, never at import.
auth = QueryKeyAuth("key", API_KEY_ENV, source=SOURCE)
client = AsyncClient(config, auth=auth)

__all__ = ["API_KEY_ENV", "BASE_URL", "RATE_LIMIT", "SOURCE", "client", "config"]
