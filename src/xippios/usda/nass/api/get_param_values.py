"""``GET /api/get_param_values``: every value a Quick Stats parameter can take.

Reference: ``docs/upstream/api.md``, resource 2. The payload is keyed by the parameter
name: ``{"sector_desc": ["ANIMALS & PRODUCTS", "CROPS", ...]}``. Observed on
2026-10-22: an unknown parameter answers HTTP 400 ``{"<param>": ["no value"]}``.
"""

import httpx
from xippios.core import NotFoundError, ValidationError, parse
from xippios.core.errors import BODY_LIMIT, raise_for_status

from xippios.usda.nass._client import SOURCE, client

__all__ = ["get_param_values"]


def _no_value(response: httpx.Response, param: str) -> bool:
    try:
        return bool(response.json().get(param) == ["no value"])
    except (ValueError, AttributeError):
        return False


async def get_param_values(param: str) -> list[str]:
    """Call ``get_param_values`` for one Quick Stats parameter.

    Args:
        param: A column name from ``docs/upstream/param_define.md``, e.g. ``"sector_desc"``.

    Raises:
        NotFoundError: Quick Stats has no parameter of that name.
    """
    response = await client.request(
        "GET", "/get_param_values/", params={"param": param}, raise_on_error=False
    )
    if response.status_code == 400 and _no_value(response, param):
        raise NotFoundError(f"Quick Stats has no parameter {param!r}", source=SOURCE)
    raise_for_status(response, source=SOURCE)
    try:
        raw = response.json()
    except ValueError as exc:
        raise ValidationError(
            f"{SOURCE}: get_param_values answered with something other than JSON",
            raw=response.text[:BODY_LIMIT],
            source=SOURCE,
        ) from exc
    payload = parse(dict[str, list[str]], raw, source=SOURCE, endpoint="get_param_values")
    if param not in payload:
        raise ValidationError(
            f"{SOURCE}: get_param_values answered without a {param!r} key",
            raw=raw,
            source=SOURCE,
        )
    return payload[param]
