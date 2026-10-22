"""Typed client, MCP tools and HTTP routes for USDA NASS Quick Stats.

Distribution ``xippios-usda-nass``. Public API: ``__version__`` and the task
functions re-exported here. Endpoint wrappers under ``api/`` and the configured client
in ``_client`` are internal.
"""

from xippios.usda.nass._version import __version__
from xippios.usda.nass.tasks import get_counts, get_data, list_param_values

__all__ = ["__version__", "get_counts", "get_data", "list_param_values"]
