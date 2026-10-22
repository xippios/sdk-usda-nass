"""``GET /api/get_param_values``: every value a Quick Stats parameter can take.

Reference: ``docs/upstream/api.md``, resource 2. The payload is keyed by the parameter
name: ``{"sector_desc": ["ANIMALS & PRODUCTS", "CROPS", ...]}``. An unknown parameter
(HTTP 400 ``{"<param>": ["no value"]}``) is mapped in ``_client.classify``.
"""

from xippios.core import ValidationError, parse

from xippios.usda.nass._client import SOURCE, client

__all__ = ["get_param_values"]


async def get_param_values(param: str) -> list[str]:
    """Call ``get_param_values`` for one Quick Stats parameter.

    Args:
        param: A column name from ``docs/upstream/param_define.md``, e.g. ``"sector_desc"``.

    Raises:
        NotFoundError: Quick Stats has no parameter of that name.
    """
    raw = await client.get_json("/get_param_values/", params={"param": param})
    payload = parse(dict[str, list[str]], raw, source=SOURCE, endpoint="get_param_values")
    if param not in payload:
        raise ValidationError(
            f"{SOURCE}: get_param_values answered without a {param!r} key",
            raw=raw,
            source=SOURCE,
        )
    return payload[param]
