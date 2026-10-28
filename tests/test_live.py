"""Live smoke tests, one per task, skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

``/add-endpoint`` adds them.
"""

from datetime import date
from decimal import Decimal
from itertools import pairwise

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
    """A parameter the package does not ship, so the call reaches upstream."""
    from xippios.usda.nass.params import PACKAGED_PARAMS

    assert "commodity_desc" not in PACKAGED_PARAMS
    result = await tasks.list_param_values_async("commodity_desc")
    assert result.meta.endpoint == "get_param_values"
    count = len(result.data)  # bound first, so a failure prints a number, not the list
    assert count > 100
    has_corn = "CORN" in result.data
    assert has_corn


async def test_crop_progress_live() -> None:
    from xippios.usda.nass.enums import ProgressStage, StateAlpha

    result = await tasks.get_crop_progress_async(
        "CORN", 2024, state=StateAlpha.IA, stage=ProgressStage.PCT_PLANTED
    )
    assert result.data
    assert result.data[-1].value_number is not None
    assert result.data[-1].value_number >= 90


async def test_crop_condition_live() -> None:
    from xippios.usda.nass.enums import ConditionCategory, StateAlpha
    from xippios.usda.nass.models import CropProgressRecord

    result = await tasks.get_crop_condition_async(
        "CORN", 2024, state=StateAlpha.IA, category=ConditionCategory.PCT_GOOD
    )
    assert result.meta.endpoint == "api_GET"
    count = len(result.data)
    assert count >= 15  # a season of weekly ratings
    assert all(isinstance(row, CropProgressRecord) for row in result.data)
    assert {row.unit_desc for row in result.data} == {"PCT GOOD"}
    assert all(row.value_number is not None and 0 <= row.value_number <= 100 for row in result.data)
    assert all(row.week_ending is not None for row in result.data)
    weeks = [row.week_ending or date.min for row in result.data]
    assert all(earlier <= later for earlier, later in pairwise(weeks))


async def test_county_yield_live() -> None:
    from xippios.usda.nass.enums import StateAlpha

    result = await tasks.get_county_yield_async("CORN", 2023, state=StateAlpha.DE)
    assert result.data
    assert {row.county_name for row in result.data} >= {"KENT", "SUSSEX"}


async def test_county_production_live() -> None:
    from xippios.usda.nass.enums import StateAlpha
    from xippios.usda.nass.models import CountyEstimateRecord

    result = await tasks.get_county_production_async("CORN", 2023, state=StateAlpha.DE)
    assert result.meta.endpoint == "api_GET"
    assert result.data
    assert all(isinstance(row, CountyEstimateRecord) for row in result.data)
    assert {row.statisticcat_desc for row in result.data} == {"PRODUCTION"}
    assert {row.agg_level_desc for row in result.data} == {"COUNTY"}
    assert {row.county_name for row in result.data} >= {"KENT", "SUSSEX"}
    order = [
        (row.state_alpha, row.county_name, row.util_practice_desc, row.prodn_practice_desc)
        for row in result.data
    ]
    assert all(earlier <= later for earlier, later in pairwise(order))


async def test_acreage_live() -> None:
    from xippios.usda.nass.enums import StateAlpha
    from xippios.usda.nass.models import AreaStatistic

    result = await tasks.get_acreage_async(
        "CORN", 2023, AreaStatistic.AREA_PLANTED, state=StateAlpha.IA
    )
    assert len(result.data) == 1
    assert result.data[0].value_number == Decimal("13100000")


async def test_acreage_forecasts_live() -> None:
    from xippios.usda.nass.models import AcreageRecord, AreaStatistic

    result = await tasks.get_acreage_forecasts_async("CORN", 2023, AreaStatistic.AREA_PLANTED)
    assert result.meta.endpoint == "api_GET"
    count = len(result.data)
    assert count >= 2  # the March and June reports at least
    assert all(isinstance(row, AcreageRecord) for row in result.data)
    assert {row.state_alpha for row in result.data} == {"US"}
    assert {row.unit_desc for row in result.data} == {"ACRES"}
    assert "YEAR" not in {row.reference_period_desc for row in result.data}
    order = [(row.load_time, row.util_practice_desc) for row in result.data]
    assert all(earlier <= later for earlier, later in pairwise(order))


async def test_prices_received_live() -> None:
    from xippios.usda.nass.enums import StateAlpha

    result = await tasks.get_prices_received_async("CORN", 2023, state=StateAlpha.IA)
    assert len(result.data) >= 12
    assert any(row.reference_period_desc == "JAN" for row in result.data)


async def test_census_farms_live() -> None:
    from xippios.usda.nass.enums import StateAlpha
    from xippios.usda.nass.models import CensusFarmsRecord, FarmStatistic

    result = await tasks.get_census_farms_async(
        2022, FarmStatistic.AREA_OPERATED, state=StateAlpha.DE, by_county=True
    )
    meta = result.meta
    assert meta.endpoint == "api_GET"
    assert meta.total is None
    count = len(result.data)
    assert count >= 3  # a figure at least for each of Delaware's three counties
    assert all(isinstance(row, CensusFarmsRecord) for row in result.data)
    sources = {row.source_desc for row in result.data}
    assert sources == {"CENSUS"}
    levels = {row.agg_level_desc for row in result.data}
    assert levels == {"COUNTY"}
    statistics = {row.statisticcat_desc for row in result.data}
    assert statistics == {"AREA OPERATED"}
    totals = {(row.class_desc, row.prodn_practice_desc) for row in result.data}
    assert totals == {("ALL CLASSES", "ALL PRODUCTION PRACTICES")}
    counties = {row.county_name for row in result.data}
    assert counties == {"KENT", "NEW CASTLE", "SUSSEX"}
    has_acres = "ACRES" in {row.unit_desc for row in result.data}
    assert has_acres
    order = [(row.state_alpha, row.county_name, row.unit_desc) for row in result.data]
    assert all(earlier <= later for earlier, later in pairwise(order))
