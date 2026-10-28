"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

``/add-endpoint`` adds them.
"""

from xippios.usda.nass.api.api_GET import api_GET
from xippios.usda.nass.api.get_counts import get_counts
from xippios.usda.nass.api.get_param_values import get_param_values

__all__ = ["api_GET", "get_counts", "get_param_values"]
