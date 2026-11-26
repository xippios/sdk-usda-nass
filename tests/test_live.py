"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them.
"""

import httpx
import pytest

from xippios.usda.nass import tasks
from xippios.usda.nass._client import BASE_URL, config

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_upstream_answers() -> None:
    """The base URL answers without a server error.

    A plain request, not the package's client, so no key goes out and it spends no keyed
    call; a keyed gateway's answer to it (a 403 or a 404, say) still shows the host is up.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": config.user_agent},
        timeout=config.timeouts.to_httpx(),
        follow_redirects=True,
    ) as http:
        response = await http.get(BASE_URL)
    assert response.status_code < 500


async def test_get_counts_live() -> None:
    result = await tasks.get_counts_async(
        {"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}
    )
    assert result.data > 0
    assert result.meta.request["commodity_desc"] == "CORN"


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(
        {
            "commodity_desc": "CORN",
            "year": 2012,
            "state_alpha": "VA",
            "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE",
        }
    )
    assert result.data
    commodity = result.data[0].commodity_desc  # bound first, so a failure prints no record
    assert commodity == "CORN"
    figure = result.data[0].value_number
    assert figure is not None


async def test_list_param_values_live() -> None:
    """A parameter the package does not ship, so the call reaches upstream."""
    from xippios.usda.nass.params import PACKAGED_PARAMS

    assert "commodity_desc" not in PACKAGED_PARAMS
    result = await tasks.list_param_values_async("commodity_desc")
    assert result.meta.endpoint == "get_param_values"
    count = len(result.data)  # bound first, so a failure prints a number, not the list
    assert count > 100
    has_corn = "CORN" in result.data
    assert has_corn
