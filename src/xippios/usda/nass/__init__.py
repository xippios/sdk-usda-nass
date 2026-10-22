"""Typed client, MCP tools and HTTP routes for USDA NASS Quick Stats.

Distribution ``xippios-usda-nass``. Public API: ``__version__`` and the task
functions re-exported here. Endpoint wrappers under ``api/`` and the configured client
in ``_client`` are internal.
"""

from xippios.usda.nass._version import __version__
from xippios.usda.nass.tasks import (
    get_acreage,
    get_counts,
    get_county_production,
    get_county_yield,
    get_crop_condition,
    get_crop_progress,
    get_data,
    get_prices_received,
    list_param_values,
)

__all__ = [
    "__version__",
    "get_acreage",
    "get_counts",
    "get_county_production",
    "get_county_yield",
    "get_crop_condition",
    "get_crop_progress",
    "get_data",
    "get_prices_received",
    "list_param_values",
]
