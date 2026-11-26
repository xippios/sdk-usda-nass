"""``GET /api/get_param_values``: every value a Quick Stats parameter can take.

Reference: ``docs/upstream/api.md``, resource 2. The payload is keyed by the parameter
name: ``{"sector_desc": ["ANIMALS & PRODUCTS", "CROPS", ...]}``. An unknown parameter
(HTTP 400 ``{"<param>": ["no value"]}``) is mapped in ``_client.classify``. The client
keeps an answer for a day (``_client.config.cache``), so the wrapper reads through
``AsyncClient.get_answer``, which parses the payload before the cache stores it and says
when the answer was retrieved: on a cache hit the time it was stored (sdk-core ADR-0037,
decision 5; conventions §4 and §6).
"""

from xippios.core import Answer, ValidationError

from xippios.usda.nass._client import SOURCE, client

__all__ = ["get_param_values"]


async def get_param_values(param: str) -> Answer[list[str]]:
    """Call ``get_param_values`` for one Quick Stats parameter.

    Args:
        param: A column name from ``docs/upstream/param_define.md``, e.g. ``"sector_desc"``.

    Returns:
        The values, in upstream order, e.g. ``["ANIMALS & PRODUCTS", "CROPS"]``, with
        ``retrieved_at``, timezone-aware UTC: on a cache hit the time the answer was
        stored, else the time it arrived; a task's ``ResultMeta.retrieved_at``.

    Raises:
        NotFoundError: Quick Stats has no parameter of that name.
        ValidationError: The answer is no mapping of names to lists of texts, which the
            cache does not keep, so the next call asks again; or it holds no list under
            the parameter's name.
    """
    answer = await client.get_answer(
        "/get_param_values/",
        params={"param": param},
        parse=dict[str, list[str]],
        endpoint="get_param_values",
    )
    if param not in answer.payload:
        raise ValidationError(
            f"{SOURCE}: get_param_values answered without a {param!r} key",
            raw=answer.payload,
            source=SOURCE,
        )
    return Answer(answer.payload[param], answer.retrieved_at)
