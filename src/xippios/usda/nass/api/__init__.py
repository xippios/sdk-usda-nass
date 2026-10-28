"""Endpoint wrappers, layer 1: one async function per upstream operation (conventions §2).

A wrapper's module and function carry the upstream operation name in snake case
(conventions §2), here from the path: ``/api/api_GET/`` is ``api_get``. The verbatim name
stays in the first line of the wrapper's docstring and in the ``endpoint=`` it passes.
``/add-endpoint`` adds them.
"""

from xippios.usda.nass.api.api_get import api_get
from xippios.usda.nass.api.get_counts import get_counts
from xippios.usda.nass.api.get_param_values import ParamValues, get_param_values

__all__ = ["ParamValues", "api_get", "get_counts", "get_param_values"]
