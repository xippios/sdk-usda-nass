"""Pydantic models mirroring USDA NASS Quick Stats payloads.

One model per upstream object, subclassing ``xippios.core.UpstreamModel``, with fields
named as upstream names them in snake_case. Within-source hygiene only: dates become
``datetime.date``, numbers become numbers, upstream enumerations become ``StrEnum``.
No cross-source normalisation (ADR-0003): an upstream concept stays an upstream concept.

Quick Stats sends every value as a string, counts and years included; the models coerce
the numeric ones. See ``docs/upstream/api.md`` and ``param_define.md``.
"""

from collections.abc import Mapping

from xippios.core import UpstreamModel

__all__ = ["Filters", "GetCountsResponse"]

Filters = Mapping[str, str | int]
"""Quick Stats query parameters, as upstream names them.

Keys are column names from ``docs/upstream/param_define.md`` (``commodity_desc``,
``state_alpha``, ``year``, ...), optionally suffixed with an operator: ``__LE``, ``__LT``,
``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``. Example:
``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``.
"""


class GetCountsResponse(UpstreamModel):
    """Payload of ``GET /api/get_counts``: ``{"count": "27"}``.

    Attributes:
        count: Number of records the same filters would return from ``api_GET``.
    """

    count: int
