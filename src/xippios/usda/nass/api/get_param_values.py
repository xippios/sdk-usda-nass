"""``GET /api/get_param_values``: every value a Quick Stats parameter can take.

Reference: ``docs/upstream/api.md``, resource 2. The payload is keyed by the parameter
name: ``{"sector_desc": ["ANIMALS & PRODUCTS", "CROPS", ...]}``. An unknown parameter
(HTTP 400 ``{"<param>": ["no value"]}``) is mapped in ``_client.classify``. The client
keeps an answer for 24 hours (``_client.config.cache``), so the wrapper reads through
``AsyncClient.get_answer``, which says when the answer was retrieved: on a cache hit the
time it was stored (ADR-0015, decision 5; conventions §4 and §6).
"""

from datetime import datetime
from typing import NamedTuple

from xippios.core import ValidationError, parse

from xippios.usda.nass._client import SOURCE, client

__all__ = ["ParamValues", "get_param_values"]


class ParamValues(NamedTuple):
    """The values of one Quick Stats parameter and when they were retrieved.

    Attributes:
        values: The values, in upstream order, e.g. ``["ANIMALS & PRODUCTS", "CROPS"]``.
        retrieved_at: Timezone-aware UTC: on a cache hit the time the answer was stored,
            else the time it arrived; a task's ``ResultMeta.retrieved_at``.
    """

    values: list[str]
    retrieved_at: datetime


async def get_param_values(param: str) -> ParamValues:
    """Call ``get_param_values`` for one Quick Stats parameter.

    Args:
        param: A column name from ``docs/upstream/param_define.md``, e.g. ``"sector_desc"``.

    Raises:
        NotFoundError: Quick Stats has no parameter of that name.
    """
    answer = await client.get_answer("/get_param_values/", params={"param": param})
    raw = answer.payload
    payload = parse(dict[str, list[str]], raw, source=SOURCE, endpoint="get_param_values")
    if param not in payload:
        raise ValidationError(
            f"{SOURCE}: get_param_values answered without a {param!r} key",
            raw=raw,
            source=SOURCE,
        )
    return ParamValues(payload[param], answer.retrieved_at)
