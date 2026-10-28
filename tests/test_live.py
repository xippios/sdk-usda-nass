"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them.
"""

from decimal import Decimal

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
    assert result.data[0].commodity_desc == "CORN"
    assert result.data[0].value_number is not None


async def test_list_param_values_live() -> None:
    result = await tasks.list_param_values_async("sector_desc")
    assert "CROPS" in result.data


async def test_crop_progress_live() -> None:
    from xippios.usda.nass.enums import ProgressStage, StateAlpha

    result = await tasks.get_crop_progress_async(
        "CORN", 2024, state=StateAlpha.IA, stage=ProgressStage.PCT_PLANTED
    )
    assert result.data
    assert result.data[-1].value_number is not None
    assert result.data[-1].value_number >= 90


async def test_county_yield_live() -> None:
    from xippios.usda.nass.enums import StateAlpha

    result = await tasks.get_county_yield_async("CORN", 2023, state=StateAlpha.DE)
    assert result.data
    assert {row.county_name for row in result.data} >= {"KENT", "SUSSEX"}


async def test_acreage_live() -> None:
    from xippios.usda.nass.enums import StateAlpha
    from xippios.usda.nass.models import AreaStatistic

    result = await tasks.get_acreage_async(
        "CORN", 2023, AreaStatistic.AREA_PLANTED, state=StateAlpha.IA
    )
    assert len(result.data) == 1
    assert result.data[0].value_number == Decimal("13100000")


async def test_prices_received_live() -> None:
    from xippios.usda.nass.enums import StateAlpha

    result = await tasks.get_prices_received_async("CORN", 2023, state=StateAlpha.IA)
    assert len(result.data) >= 12
    assert any(row.reference_period_desc == "JAN" for row in result.data)
