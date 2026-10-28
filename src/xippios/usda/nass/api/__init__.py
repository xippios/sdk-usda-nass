"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

A wrapper's module and function carry the upstream operation's id snake_cased
(conventions §2); the verbatim id stays in the first line of the wrapper's docstring and
in the ``endpoint=`` it passes. ``/add-endpoint`` adds them.
"""

from xippios.usda.nass.api.api_get import api_get
from xippios.usda.nass.api.get_counts import get_counts
from xippios.usda.nass.api.get_param_values import get_param_values

__all__ = ["api_get", "get_counts", "get_param_values"]
