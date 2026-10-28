"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

import argparse
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from xippios.core import (
    InvalidRequestError,
    MemoryCache,
    NotFoundError,
    PackagedList,
    Result,
    UnknownCode,
    UpstreamModel,
    load_json,
)
from xippios.core.client import cache_key
from xippios.core.http import status_for
from xippios.core.mcp import build_parser, main
from xippios.core.redaction import scrub_url
from xippios.core.testing import (
    REDACTED,
    ReplayFixture,
    assert_projection,
    assert_time_between,
    load_fixture,
    mcp_call,
    mcp_call_text,
    recorded_query,
    sent_query,
    sent_urls,
)

from xippios.usda.nass import api, enums, tasks
from xippios.usda.nass._client import BASE_URL, config
from xippios.usda.nass.errors import MCP_SPLIT_YEARS, SPLIT_CEILING, QueryTooLarge
from xippios.usda.nass.mcp import run, server
from xippios.usda.nass.models import (
    AcreageRecord,
    ApiGetResponse,
    AreaStatistic,
    CensusFarmsRecord,
    CountyEstimateRecord,
    CropProgressRecord,
    FarmStatistic,
    LivestockCommodity,
    LivestockInventoryRecord,
    MilkProductionRecord,
    PriceReceivedRecord,
    QuickStatsRecord,
)
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGE, PACKAGED_PARAMS, columns

EXAMPLE_FILTERS: dict[str, str | int] = {
    "commodity_desc": "CORN",
    "year__GE": 2012,
    "state_alpha": "VA",
}


def test_get_counts_replays_the_documented_example(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("get_counts", "corn_va_since_2012")
    result = tasks.get_counts(EXAMPLE_FILTERS)
    assert result.data == 22345
    assert result.meta.total == 22345
    assert result.meta.source == "usda-nass"
    assert result.meta.endpoint == "get_counts"
    assert result.meta.request == EXAMPLE_FILTERS
    sent = sent_query(route)
    assert sent["commodity_desc"] == "CORN"
    assert sent["year__GE"] == "2012"
    assert sent["state_alpha"] == "VA"
    assert "key" in sent


@pytest.mark.anyio
async def test_unknown_columns_are_ignored_upstream(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Characterisation at layer 1: Quick Stats drops unknown columns and counts everything."""
    replay_fixture("get_counts", "unknown_column")
    assert (await api.get_counts({"not_a_column": "x"})).count == 57873464


def test_unknown_filter_keys_are_rejected_before_any_call(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_counts({"comodity_desc": "CORN", "year__GTE": 2012, "state_alpha": "XX"})
    assert not isinstance(info.value, UnknownCode)  # the keys are checked before the values
    message = str(info.value)
    assert "'comodity_desc' is not a Quick Stats column" in message
    assert "did you mean commodity_desc" in message
    assert "'year__GTE': unknown operator 'GTE'" in message
    assert "__GE" in message
    assert not respx_mock.calls


def test_every_documented_operator_passes_validation(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_counts", "corn_va_since_2012")
    for key in ["year__LE", "year__LT", "year__GT", "year__GE", "commodity_desc__LIKE",
                "commodity_desc__NOT_LIKE", "state_alpha__NE", "Value"]:  # fmt: skip
        assert tasks.get_counts({key: "x"}).data == 22345


def test_query_too_large_is_an_invalid_request_for_http_too() -> None:
    assert issubclass(QueryTooLarge, InvalidRequestError)
    assert status_for(QueryTooLarge(70_000)) == 422


def fetched_as_written(name: str) -> datetime:
    """A packaged file's ``fetched``, read from its text: UTC to the second, with ``Z``.

    ``PackagedList.write`` writes it so (``"2026-10-28T15:01:38Z"``); a bare date, as the
    files carried before the refresh of 2026-10-28, fails here rather than read as midnight.
    """
    text = load_json(PACKAGE, f"{name}.json")["fetched"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text), (name, text)
    when = datetime.fromisoformat(text)
    assert when.utcoffset() == timedelta(0), (name, text)
    return when


@pytest.mark.parametrize("param", PACKAGED_PARAMS)
def test_enums_match_the_packaged_lists(param: str) -> None:
    cls = getattr(enums, "".join(part.capitalize() for part in param.split("_")))
    packaged = PackagedList.load(PACKAGE, param)
    values = [record[param] for record in packaged.records]
    assert [member.value for member in cls] == values
    assert cls.__doc__ == f"Values of ``{param}`` (fetched {packaged.fetched:%Y-%m-%d})."


def test_enum_members_keep_upstream_values_and_the_hand_names() -> None:
    """Derived names, and the ones the refresh script sets (``member_names``): every dollar
    unit by the DOLLARS / PER rule, and the two spelled-out landlord domains."""
    assert {"statisticcat_desc", "unit_desc", "domain_desc"} <= set(PACKAGED_PARAMS)
    assert enums.StateAlpha.VA.value == "VA"
    assert enums.SectorDesc.ANIMALS_AND_PRODUCTS.value == "ANIMALS & PRODUCTS"
    assert enums.AggLevelDesc.REGION_MULTI_STATE.value == "REGION : MULTI-STATE"
    assert enums.StatisticcatDesc.AREA_PLANTED.value == "AREA PLANTED"
    assert enums.DomainDesc.TOTAL.value == "TOTAL"
    assert enums.UnitDesc.ACRES.value == "ACRES"
    assert enums.UnitDesc.DOLLARS.value == "$"
    assert enums.UnitDesc.BU.value == "BU"
    assert enums.UnitDesc.DOLLARS_PER_BU.value == "$ / BU"
    assert enums.UnitDesc.LB_CHERRY_BASIS.value == "LB, CHERRY BASIS"
    assert enums.UnitDesc.DOLLARS_PER_LB_CHERRY_BASIS.value == "$ / LB, CHERRY BASIS"
    assert enums.UnitDesc.ACRE_FEET.value == "ACRE FEET"
    assert enums.UnitDesc.DOLLARS_PER_ACRE.value == "$ / ACRE"
    assert enums.UnitDesc.DOLLARS_PER_TON_DRY_BASIS.value == "$ / TON, DRY BASIS"
    assert enums.UnitDesc.DOLLARS_PER_1_000_EGGS.value == "$ / 1,000 EGGS"
    assert enums.UnitDesc.DOLLARS_CHERRY_BASIS.value == "$, CHERRY BASIS"
    for member in enums.UnitDesc:
        assert member.name.startswith("DOLLARS") == ("$" in member.value), member
        assert member.name.startswith("DOLLARS_PER_") == member.value.startswith("$ / "), member
    landlords = "LANDLORDS_NON_OPERATING_VALUE_OF_LAND_AND_BUILDINGS"
    assert enums.DomainDesc[landlords].value == (
        "LANDLORDS, NON-OPERATING, VALUE OF LAND & BUILDINGS"
    )
    assert enums.DomainDesc[f"{landlords}_SPELLED_OUT"].value == (
        "LANDLORDS, NON-OPERATING, VALUE OF LAND AND BUILDINGS"
    )
    assert sum(member.name.endswith("_SPELLED_OUT") for member in enums.DomainDesc) == 2


def test_enum_members_are_accepted_as_filter_values(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A member passes the packaged-list check by its value."""
    route = replay_fixture("get_counts", "corn_va_since_2012")
    result = tasks.get_counts(
        {"state_alpha": enums.StateAlpha.VA, "sector_desc": enums.SectorDesc.CROPS}
    )
    assert result.meta.request["state_alpha"] == "VA"
    assert sent_query(route)["sector_desc"] == "CROPS"


@pytest.mark.anyio
async def test_upstream_counts_no_records_for_an_unknown_packaged_value(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The refusal's premise, recorded at layer 1 on 2026-10-28: Quick Stats answers a
    ``state_alpha`` it does not know with HTTP 200 and a count of 0, the answer a query
    without data gets."""
    route = replay_fixture("get_counts", "unknown_state_alpha")
    assert (await api.get_counts({"state_alpha": "XX"})).count == 0
    assert sent_query(route)["state_alpha"] == "XX"


def test_a_packaged_value_in_lower_case_passes_and_is_sent_as_given(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Quick Stats folds case, recorded on 2026-10-28: ``state_alpha=va`` with the filters
    of ``EXAMPLE_FILTERS`` counts 22,347, where ``VA`` counted 22,345 on 2026-10-22, so
    the packaged-list check accepts ``va`` and sends it unchanged."""
    route = replay_fixture("get_counts", "corn_va_since_2012_lowercase")
    filters = {**EXAMPLE_FILTERS, "state_alpha": "va"}
    result = tasks.get_counts(filters)
    assert (result.data, result.meta.total) == (22347, 22347)
    assert result.meta.request == filters
    assert sent_query(route)["state_alpha"] == "va"


@pytest.mark.parametrize("task", [tasks.get_counts, tasks.get_data])
def test_unknown_packaged_value_is_refused_before_any_call(
    respx_mock: respx.MockRouter, task: Callable[..., object]
) -> None:
    """Quick Stats counts no records for a value it does not know, the answer a query
    without data gets, so the package refuses it with core's ``UnknownCode`` (§5)."""
    with pytest.raises(UnknownCode) as info:
        task({"commodity_desc": "CORN", "state_alpha": "XX"})
    fetched = fetched_as_written("state_alpha")
    assert str(info.value).startswith(
        f"'XX' is not a state_alpha in the packaged state_alpha list (fetched {fetched:%Y-%m-%d})."
    )
    assert (
        "list_param_values('state_alpha') lists the known values (over MCP, the tool "
        "usda_nass_list_param_values)."
    ) in str(info.value)
    assert (info.value.param, info.value.value, info.value.list_name) == (
        "state_alpha", "XX", "state_alpha",
    )  # fmt: skip
    assert info.value.fetched == fetched
    assert info.value.closest == ()  # no two-letter code is close enough to "XX"
    assert isinstance(info.value, InvalidRequestError)
    assert status_for(info.value) == 422
    assert not respx_mock.calls


@pytest.mark.parametrize(
    ("param", "value", "known"),
    [
        ("state_alpha", "vaa", "VA"),
        ("sector_desc", "crop", "CROPS"),
        ("freq_desc", "WEEK", "WEEKLY"),
    ],
)
def test_unknown_packaged_value_names_the_closest_known_ones(
    respx_mock: respx.MockRouter, param: str, value: str, known: str
) -> None:
    """The hint names the closest known values in their canonical spelling, upper case
    as upstream writes them, whatever the case given."""
    with pytest.raises(UnknownCode) as info:
        tasks.get_data({"commodity_desc": "CORN", param: value})
    assert info.value.closest[0][0] == known
    assert f"Did you mean {known}" in str(info.value)
    assert f"packaged {param} list (fetched {fetched_as_written(param):%Y-%m-%d})" in str(
        info.value
    )
    assert not respx_mock.calls


def test_every_packaged_parameter_is_checked(respx_mock: respx.MockRouter) -> None:
    for param in PACKAGED_PARAMS:
        with pytest.raises(UnknownCode) as info:
            tasks.get_counts({param: "NOT A VALUE"})
        assert (info.value.param, info.value.fetched) == (param, fetched_as_written(param))
    assert not respx_mock.calls


def test_operator_keys_of_packaged_parameters_are_sent_as_given(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("get_counts", "no_match")
    result = tasks.get_counts({"state_alpha__LIKE": "X", "sector_desc__NE": "NOT A SECTOR"})
    assert route.called
    # (0, 0) is the no_match fixture's count, recorded for year=1800, not for this query.
    assert (result.data, result.meta.total) == (0, 0)
    sent = sent_query(route)
    assert (sent["state_alpha__LIKE"], sent["sector_desc__NE"]) == ("X", "NOT A SECTOR")


SMALL_FILTERS: dict[str, str | int] = {
    "commodity_desc": "CORN",
    "year": 2012,
    "state_alpha": "VA",
    "statisticcat_desc": "AREA PLANTED",
    "agg_level_desc": "STATE",
}


def test_get_data_parses_every_column(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_va_since_2012")
    fetched = replay_fixture("api_get", "corn_va_2012_area_planted")
    result = tasks.get_data(SMALL_FILTERS)
    assert fetched.called
    assert result.meta.endpoint == "api_GET"
    assert result.meta.request == SMALL_FILTERS
    assert len(result.data) == 2
    # The count get_counts reported, as recorded for EXAMPLE_FILTERS: upstream's statement,
    # never len(data) (conventions §4, ADR-0012).
    assert result.meta.total == 22345
    record = result.data[0]
    assert record.commodity_desc == "CORN"
    assert record.year == 2012
    assert record.value == "510,000"
    assert record.value_number == Decimal("510000")
    assert record.cv_percent == ""
    assert record.week_ending is None
    assert record.load_time == datetime(2015, 6, 3, 15, 8, 31)
    assert record.short_desc == "CORN - ACRES PLANTED"
    assert sent_query(fetched)["format"] == "JSON"


def test_get_data_refuses_before_fetching_when_over_the_limit(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_counts", "unknown_column")
    fetched = replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        tasks.get_data({"commodity_desc": "CORN"})
    assert info.value.count == 57873464
    assert "57,873,464" in str(info.value)
    assert "narrow" in str(info.value).lower()
    assert not fetched.called


def test_get_data_returns_empty_without_fetching_when_nothing_matches(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_counts", "no_match")
    fetched = replay_fixture("api_get", "no_match")
    result = tasks.get_data({"commodity_desc": "CORN", "year": 1800, "state_alpha": "VA"})
    assert result.data == []
    assert result.meta.total == 0
    assert not fetched.called


@pytest.mark.anyio
async def test_api_get_maps_upstream_errors(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        await api.api_get({"commodity_desc": "CORN"})
    assert info.value.count is None


@pytest.mark.anyio
async def test_api_get_maps_no_match_to_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "no_match")
    with pytest.raises(NotFoundError, match="invalid query"):
        await api.api_get({"commodity_desc": "CORN", "year": 1800})


def test_value_number_handles_suppression_codes() -> None:
    record = QuickStatsRecord.model_validate(
        {**EXAMPLE_RECORD, "Value": "(D)"},
    )
    assert record.value == "(D)"
    assert record.value_number is None


EXAMPLE_RECORD = {
    "CV (%)": "", "Value": "1,234.5", "agg_level_desc": "STATE", "asd_code": "",
    "asd_desc": "", "begin_code": "00", "class_desc": "ALL CLASSES",
    "commodity_desc": "CORN", "congr_district_code": "", "country_code": "9000",
    "country_name": "UNITED STATES", "county_ansi": "", "county_code": "",
    "county_name": "", "domain_desc": "TOTAL", "domaincat_desc": "NOT SPECIFIED",
    "end_code": "00", "freq_desc": "ANNUAL", "group_desc": "FIELD CROPS",
    "load_time": "2015-06-03 15:08:31.000", "location_desc": "VIRGINIA",
    "prodn_practice_desc": "ALL PRODUCTION PRACTICES", "reference_period_desc": "YEAR",
    "region_desc": "", "sector_desc": "CROPS", "short_desc": "CORN - ACRES PLANTED",
    "source_desc": "SURVEY", "state_alpha": "VA", "state_ansi": "51",
    "state_fips_code": "51", "state_name": "VIRGINIA", "statisticcat_desc": "AREA PLANTED",
    "unit_desc": "ACRES", "util_practice_desc": "ALL UTILIZATION PRACTICES",
    "watershed_code": "00000000", "watershed_desc": "", "week_ending": "", "year": "2012",
    "zip_5": "",
}  # fmt: skip


@pytest.mark.anyio
async def test_get_param_values_replays_the_documented_example(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Layer 1 is unaffected by packaging: the wrapper asks upstream, through the cache."""
    route = replay_fixture("get_param_values", "sector_desc")
    before = datetime.now(UTC)
    values, retrieved_at = await api.get_param_values("sector_desc")
    after = datetime.now(UTC)
    assert values == ["ANIMALS & PRODUCTS", "CROPS", "DEMOGRAPHICS", "ECONOMICS", "ENVIRONMENTAL"]
    assert sent_query(route)["param"] == "sector_desc"
    assert_time_between(retrieved_at, before, after)


def test_list_param_values_goes_live_for_an_unpackaged_parameter(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    assert "commodity_desc" not in PACKAGED_PARAMS
    route = replay_fixture("get_param_values", "commodity_desc")
    before = datetime.now(UTC)
    result = tasks.list_param_values("commodity_desc")
    after = datetime.now(UTC)
    assert route.called
    assert sent_query(route)["param"] == "commodity_desc"
    assert result.meta.endpoint == "get_param_values"
    assert result.meta.request == {"param": "commodity_desc"}
    assert_time_between(result.meta.retrieved_at, before, after)
    assert {"CORN", "SOYBEANS"} <= set(result.data)
    assert len(result.data) > 200


def stored_at(param: str) -> datetime:
    """When the client's cache stored the ``get_param_values`` answer for ``param``."""
    assert config.cache is not None
    url = httpx.URL(f"{BASE_URL}/get_param_values/", params={"param": param})
    entry = config.cache.get(cache_key("GET", url))
    assert entry is not None
    return datetime.fromtimestamp(entry.stored_at, UTC)


def test_a_list_fetched_live_is_cached_and_carries_its_stored_time(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A second lookup sends nothing and carries the time the cache stored the first
    answer, not a clock reading of its own (ADR-0015, decision 5; conventions §4).

    The plugin empties every ``MemoryCache`` around each test (ADR-0013), so the hit is
    proved inside this one. The first call, a miss, carries the time its answer arrived,
    which core reads just after storing it; both times lie in the first call's bracket.
    """
    assert isinstance(config.cache, MemoryCache)
    assert config.cache.ttl == 24 * 60 * 60
    route = replay_fixture("get_param_values", "commodity_desc")
    before = datetime.now(UTC)
    first = tasks.list_param_values("commodity_desc")
    after = datetime.now(UTC)
    second = tasks.list_param_values("commodity_desc")
    assert route.call_count == 1
    assert second.data == first.data
    assert len(second.data) > 200
    stored = stored_at("commodity_desc")
    assert second.meta.retrieved_at == stored
    assert_time_between(stored, before, after)
    assert_time_between(first.meta.retrieved_at, before, after)
    unstamped = {"retrieved_at"}
    assert second.meta.model_dump(exclude=unstamped) == first.meta.model_dump(exclude=unstamped)
    assert second.meta.published_at is None


def test_counts_are_never_cached(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    route = replay_fixture("get_counts", "corn_va_since_2012")
    first = tasks.get_counts(EXAMPLE_FILTERS)
    second = tasks.get_counts(EXAMPLE_FILTERS)
    assert route.call_count == 2
    assert (first.data, second.data) == (22345, 22345)
    assert isinstance(config.cache, MemoryCache)
    assert len(config.cache) == 0


def test_data_is_never_cached(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    counted = replay_fixture("get_counts", "corn_va_since_2012")
    fetched = replay_fixture("api_get", "corn_va_2012_area_planted")
    first = tasks.get_data(SMALL_FILTERS)
    second = tasks.get_data(SMALL_FILTERS)
    assert fetched.call_count == 2
    assert counted.call_count == 2
    assert len(second.data) == len(first.data) == 2
    assert isinstance(config.cache, MemoryCache)
    assert len(config.cache) == 0


@pytest.mark.anyio
async def test_list_param_values_over_mcp_is_whole_past_the_default_cap(
    respx_mock: respx.MockRouter,
) -> None:
    """``statisticcat_desc``, past the default cap of 200 rows, answered from the package
    with no upstream call: the tool's own cap, ``tasks.MCP_CAPS`` (ADR-0016), lets every
    one through, so no note is added."""
    payload = await mcp_call(server, "usda_nass_list_param_values", {"param": "statisticcat_desc"})
    assert not respx_mock.calls
    assert len(payload["data"]) == len(PackagedList.load(PACKAGE, "statisticcat_desc").records)
    assert len(payload["data"]) > 200
    assert "note" not in payload
    assert tasks.MCP_CAPS["list_param_values"].max_rows == 1000


@pytest.mark.anyio
async def test_list_param_values_over_mcp_is_whole_for_a_live_list(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """A list fetched live, ``commodity_desc``, past the default cap too, is whole."""
    route = replay_fixture("get_param_values", "commodity_desc")
    payload = await mcp_call(server, "usda_nass_list_param_values", {"param": "commodity_desc"})
    assert route.called
    assert len(payload["data"]) > 200
    assert "CORN" in payload["data"]
    assert "note" not in payload


def test_list_param_values_unknown_parameter_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_param_values", "unknown_param")
    with pytest.raises(NotFoundError, match="not_a_column"):
        tasks.list_param_values("not_a_column")


@pytest.mark.parametrize("param", PACKAGED_PARAMS)
def test_packaged_parameters_are_answered_without_a_network_call(
    param: str, respx_mock: respx.MockRouter
) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    packaged = PackagedList.load(PACKAGE, param)
    result = tasks.list_param_values(param)
    assert result.data == [record[param] for record in packaged.records]
    assert result.data
    assert result.meta.endpoint == "get_param_values"
    assert result.meta.retrieved_at == fetched_as_written(param)
    assert result.meta.vintage is None
    assert result.meta.published_at is None
    assert result.meta.total is None
    assert result.meta.request == {"param": param}
    assert not respx_mock.calls


def test_packaged_answers_hold_known_values(respx_mock: respx.MockRouter) -> None:
    assert "CROPS" in tasks.list_param_values("sector_desc").data
    assert "VA" in tasks.list_param_values("state_alpha").data
    assert "AREA PLANTED" in tasks.list_param_values("statisticcat_desc").data
    assert {"ACRES", "$ / BU"} <= set(tasks.list_param_values("unit_desc").data)
    assert "TOTAL" in tasks.list_param_values("domain_desc").data
    assert not respx_mock.calls


def test_columns_cover_every_record_field() -> None:
    names = {column.column for column in columns()}
    assert names >= {
        "commodity_desc",
        "state_alpha",
        "year",
        "Value",
        "CV (%)",
        "reference_period_desc",
    }
    record_fields = {
        (str(field.validation_alias) if field.validation_alias else name)
        for name, field in QuickStatsRecord.model_fields.items()
    }
    assert record_fields <= names
    assert {column.dimension for column in columns()} == {
        'The "WHAT" (or Commodity) dimension',
        'The "WHERE" (or Location) dimension',
        'The "WHEN" (or Time) dimension',
        "The Data Value",
    }


def test_crop_progress_state_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    fetched = replay_fixture("api_get", "corn_progress_planted_ia_2024")
    result = tasks.get_crop_progress(
        "CORN", 2024, state=enums.StateAlpha.IA, stage=enums.ProgressStage.PCT_PLANTED
    )
    assert result.meta.request == {
        "commodity_desc": "CORN",
        "statisticcat_desc": "PROGRESS",
        "freq_desc": "WEEKLY",
        "year": 2024,
        "agg_level_desc": "STATE",
        "state_alpha": "IA",
        "unit_desc": "PCT PLANTED",
    }
    assert sent_query(fetched)["statisticcat_desc"] == "PROGRESS"
    assert len(result.data) == 11
    weeks = [row.week_ending or date.min for row in result.data]
    assert weeks == sorted(weeks)
    first, last = result.data[0], result.data[-1]
    assert first.week_ending == date(2024, 3, 31)
    assert (first.value, first.value_number) == ("0", Decimal("0"))
    assert last.week_ending == date(2024, 6, 9)
    assert last.value_number == Decimal("98")  # NASS stops the series short of 100
    assert {row.unit_desc for row in result.data} == {"PCT PLANTED"}
    assert {row.state_alpha for row in result.data} == {"IA"}
    assert last.short_desc == "CORN - PROGRESS, MEASURED IN PCT PLANTED"
    assert isinstance(last.load_time, datetime)


def test_crop_progress_national_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_progress_planted_us_2024")
    result = tasks.get_crop_progress("CORN", 2024, stage=enums.ProgressStage.PCT_PLANTED)
    assert result.meta.request["agg_level_desc"] == "NATIONAL"
    assert "state_alpha" not in result.meta.request
    assert {row.state_alpha for row in result.data} == {"US"}
    assert {row.state_name for row in result.data} == {"US TOTAL"}


def test_crop_condition_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_condition_good_ia_2024")
    result = tasks.get_crop_condition(
        "CORN", 2024, state=enums.StateAlpha.IA, category=enums.ConditionCategory.PCT_GOOD
    )
    assert result.meta.request["statisticcat_desc"] == "CONDITION"
    assert result.meta.request["unit_desc"] == "PCT GOOD"
    assert len(result.data) == 21
    assert {row.statisticcat_desc for row in result.data} == {"CONDITION"}
    assert all(row.value_number is not None and 0 <= row.value_number <= 100 for row in result.data)


def test_derived_enums_match_their_lists_and_provenance() -> None:
    stages = PackagedList.load(PACKAGE, "progress_stages")
    categories = PackagedList.load(PACKAGE, "condition_categories")
    assert [m.value for m in enums.ProgressStage] == [r["unit_desc"] for r in stages.records]
    assert [m.value for m in enums.ConditionCategory] == [
        r["unit_desc"] for r in categories.records
    ]
    for derived in (stages, categories):
        assert (derived.param, derived.endpoint) == ("unit_desc", "api_GET")
    for name in DERIVED_LISTS:
        assert PackagedList.load(PACKAGE, name).fetched == fetched_as_written(name)
    assert stages.note is not None
    assert "statisticcat_desc=PROGRESS" in stages.note
    assert "agg_level_desc=NATIONAL" in stages.note
    assert set(DERIVED_LISTS) == {"progress_stages", "condition_categories"}
    assert enums.ProgressStage.PCT_PLANTED.value == "PCT PLANTED"
    assert [m.value for m in enums.ConditionCategory] == [
        "PCT EXCELLENT", "PCT FAIR", "PCT GOOD", "PCT POOR", "PCT VERY POOR",
    ]  # fmt: skip


def test_county_yield_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    fetched = replay_fixture("api_get", "corn_yield_de_2023_county")
    result = tasks.get_county_yield("CORN", 2023, state=enums.StateAlpha.DE)
    assert result.meta.request == {
        "commodity_desc": "CORN",
        "statisticcat_desc": "YIELD",
        "agg_level_desc": "COUNTY",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "year": 2023,
        "state_alpha": "DE",
    }
    assert sent_query(fetched)["agg_level_desc"] == "COUNTY"
    assert len(result.data) == 9
    assert [row.county_name for row in result.data[:3]] == ["KENT"] * 3
    assert {row.county_name for row in result.data} == {"KENT", "NEW CASTLE", "SUSSEX"}
    assert {row.prodn_practice_desc for row in result.data} == {
        "ALL PRODUCTION PRACTICES", "IRRIGATED", "NON-IRRIGATED",
    }  # fmt: skip
    assert {row.unit_desc for row in result.data} == {"BU / ACRE"}
    kent_all = next(
        row
        for row in result.data
        if row.county_name == "KENT" and row.prodn_practice_desc == "ALL PRODUCTION PRACTICES"
    )
    assert (kent_all.value, kent_all.value_number) == ("194.5", Decimal("194.5"))
    assert kent_all.cv_percent == Decimal("2.5")
    assert kent_all.county_code == "001"
    assert kent_all.asd_desc == "CENTRAL"
    assert all(
        row.cv_percent is None
        for row in result.data
        if row.prodn_practice_desc != "ALL PRODUCTION PRACTICES"
    )


def test_county_production_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_production_de_2023_county")
    result = tasks.get_county_production("CORN", 2023, state=enums.StateAlpha.DE)
    assert result.meta.request["statisticcat_desc"] == "PRODUCTION"
    assert {row.unit_desc for row in result.data} == {"BU"}
    sussex_all = next(
        row
        for row in result.data
        if row.county_name == "SUSSEX" and row.prodn_practice_desc == "ALL PRODUCTION PRACTICES"
    )
    assert sussex_all.value_number == Decimal("18397000")
    assert sussex_all.cv_percent == Decimal("8.7")


def test_county_series_without_state_covers_the_country(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "corn_yield_de_2023_county")
    result = tasks.get_county_yield("CORN", 2023)
    assert "state_alpha" not in result.meta.request
    assert result.meta.request["agg_level_desc"] == "COUNTY"


def test_acreage_planted_state(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    fetched = replay_fixture("api_get", "corn_area_planted_ia_2023")
    result = tasks.get_acreage("CORN", 2023, AreaStatistic.AREA_PLANTED, state=enums.StateAlpha.IA)
    assert result.meta.request == {
        "commodity_desc": "CORN",
        "statisticcat_desc": "AREA PLANTED",
        "unit_desc": "ACRES",
        "domain_desc": "TOTAL",
        "prodn_practice_desc": "ALL PRODUCTION PRACTICES",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "agg_level_desc": "STATE",
        "year": 2023,
        "state_alpha": "IA",
    }
    assert sent_query(fetched)["unit_desc"] == "ACRES"
    assert len(result.data) == 1
    row = result.data[0]
    assert row.value_number == Decimal("13100000")
    assert row.util_practice_desc == "ALL UTILIZATION PRACTICES"
    assert row.source_desc == "SURVEY"
    assert row.cv_percent is None


def test_acreage_harvested_splits_grain_and_silage(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "corn_area_harvested_ia_2023")
    result = tasks.get_acreage(
        "CORN", 2023, AreaStatistic.AREA_HARVESTED, state=enums.StateAlpha.IA
    )
    assert result.meta.request["statisticcat_desc"] == "AREA HARVESTED"
    assert [(row.util_practice_desc, row.value_number) for row in result.data] == [
        ("GRAIN", Decimal("12550000")),
        ("SILAGE", Decimal("380000")),
    ]


def test_acreage_national(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_area_planted_us_2023")
    result = tasks.get_acreage("CORN", 2023, AreaStatistic.AREA_PLANTED)
    assert result.meta.request["agg_level_desc"] == "NATIONAL"
    assert "state_alpha" not in result.meta.request
    assert result.data[0].state_alpha == "US"
    assert result.data[0].value_number == Decimal("94641000")


def test_prices_received_state_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    fetched = replay_fixture("api_get", "corn_price_received_ia_2023")
    result = tasks.get_prices_received("CORN", 2023, state=enums.StateAlpha.IA)
    assert result.meta.request == {
        "commodity_desc": "CORN",
        "statisticcat_desc": "PRICE RECEIVED",
        "domain_desc": "TOTAL",
        "agg_level_desc": "STATE",
        "year": 2023,
        "state_alpha": "IA",
    }
    assert sent_query(fetched)["statisticcat_desc"] == "PRICE RECEIVED"
    assert len(result.data) == 13
    first = result.data[0]
    assert (first.freq_desc, first.reference_period_desc, first.value_number) == (
        "ANNUAL", "MARKETING YEAR", Decimal("4.61"),
    )  # fmt: skip
    months = result.data[1:]
    assert [row.reference_period_desc for row in months] == [
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    ]  # fmt: skip
    assert months[0].value_number == Decimal("6.74")
    assert months[-1].value_number == Decimal("4.89")
    assert {row.unit_desc for row in result.data} == {"$ / BU"}
    assert months[0].begin_code == "01"


def test_prices_received_national_monthly(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "corn_price_received_us_2023_monthly")
    result = tasks.get_prices_received("CORN", 2023, frequency=enums.FreqDesc.MONTHLY)
    assert result.meta.request["agg_level_desc"] == "NATIONAL"
    assert result.meta.request["freq_desc"] == "MONTHLY"
    assert "state_alpha" not in result.meta.request
    assert len(result.data) == 24
    assert {row.unit_desc for row in result.data} == {"$ / BU", "PCT OF PARITY"}
    jan = [row for row in result.data if row.reference_period_desc == "JAN"]
    assert [(row.unit_desc, row.value_number) for row in jan] == [
        ("$ / BU", Decimal("6.63")),
        ("PCT OF PARITY", Decimal("43")),
    ]


# --- the livestock slices, decision 9 (a) (Johannes, 2026-10-26 and 2026-10-28) ---

INVENTORY_FILTERS: dict[str, str | int] = {  # get_livestock_inventory's fixed filters
    "statisticcat_desc": "INVENTORY",
    "unit_desc": "HEAD",
    "domain_desc": "TOTAL",
    "freq_desc": "POINT IN TIME",
    "source_desc": "SURVEY",
}
MILK_FILTERS: dict[str, str | int] = {  # get_milk_production's fixed filters
    "commodity_desc": "MILK",
    "class_desc": "ALL CLASSES",
    "statisticcat_desc": "PRODUCTION",
    "unit_desc": "LB",
    "domain_desc": "TOTAL",
    "source_desc": "SURVEY",
}
HOG_CLASSES = [  # Iowa's hog classes of api_get/hogs_inventory_ia_2024, in class order
    "ALL CLASSES", "BREEDING", "MARKET", "MARKET, 120 TO 179 LBS", "MARKET, 50 TO 119 LBS",
    "MARKET, GE 180 LBS", "MARKET, LT 50 LBS",
]  # fmt: skip
MILK_PERIODS = [  # the months and quarters upstream files as MONTHLY, in slice order
    "JAN", "JAN THRU MAR", "FEB", "MAR", "APR", "APR THRU JUN", "MAY", "JUN",
    "JUL", "JUL THRU SEP", "AUG", "SEP", "OCT", "OCT THRU DEC", "NOV", "DEC",
]  # fmt: skip


def assert_sent_as_recorded(route: respx.Route, fixtures_dir: Path, case: str) -> None:
    """The task sent the very query ``api_get/<case>`` was recorded with (key redacted)."""
    fixture = load_fixture(fixtures_dir / "api_get" / f"{case}.json")
    assert sent_query(route) == recorded_query(fixture)


def test_livestock_inventory_national_series(
    replay_fixture: ReplayFixture, fixtures_dir: Path
) -> None:
    fetched = replay_fixture("api_get", "cattle_inventory_us_2024")
    result = tasks.get_livestock_inventory(LivestockCommodity.CATTLE, 2024)
    assert result.meta.request == {
        "commodity_desc": "CATTLE",
        **INVENTORY_FILTERS,
        "year": 2024,
        "agg_level_desc": "NATIONAL",
    }
    assert_sent_as_recorded(fetched, fixtures_dir, "cattle_inventory_us_2024")
    assert result.meta.endpoint == "api_GET"
    assert result.meta.total is None
    assert result.meta.published_at is None
    assert len(result.data) == 14
    assert all(isinstance(row, LivestockInventoryRecord) for row in result.data)
    assert {(row.state_alpha, row.state_name) for row in result.data} == {("US", "US TOTAL")}
    assert {
        (row.statisticcat_desc, row.unit_desc, row.freq_desc, row.source_desc)
        for row in result.data
    } == {("INVENTORY", "HEAD", "POINT IN TIME", "SURVEY")}
    # The national cattle series of 2024 has one survey day, as recorded on 2026-10-28.
    assert {row.reference_period_desc for row in result.data} == {"FIRST OF JAN"}
    assert {(row.begin_code, row.end_code) for row in result.data} == {("01", "01")}
    classes = [row.class_desc for row in result.data]
    assert classes == sorted(classes)
    herd = next(row for row in result.data if row.class_desc == "INCL CALVES")
    assert (herd.short_desc, herd.value, herd.value_number) == (
        "CATTLE, INCL CALVES - INVENTORY", "87,157,400", Decimal("87157400"),
    )  # fmt: skip
    on_feed = result.data[0]
    assert (on_feed.class_desc, on_feed.prodn_practice_desc, on_feed.short_desc) == (
        "ALL CLASSES", "ON FEED", "CATTLE, ON FEED - INVENTORY",
    )  # fmt: skip
    assert {row.prodn_practice_desc for row in result.data[1:]} == {"ALL PRODUCTION PRACTICES"}
    assert all(row.load_time.tzinfo is None for row in result.data)


def test_livestock_inventory_state_series_sorted_by_day_then_class(
    replay_fixture: ReplayFixture, fixtures_dir: Path
) -> None:
    fetched = replay_fixture("api_get", "hogs_inventory_ia_2024")
    result = tasks.get_livestock_inventory(LivestockCommodity.HOGS, 2024, state=enums.StateAlpha.IA)
    assert result.meta.request == {
        "commodity_desc": "HOGS",
        **INVENTORY_FILTERS,
        "year": 2024,
        "agg_level_desc": "STATE",
        "state_alpha": "IA",
    }
    assert_sent_as_recorded(fetched, fixtures_dir, "hogs_inventory_ia_2024")
    assert (result.meta.endpoint, result.meta.total, result.meta.published_at) == (
        "api_GET", None, None,
    )  # fmt: skip
    assert len(result.data) == 28
    days = ["FIRST OF MAR", "FIRST OF JUN", "FIRST OF SEP", "FIRST OF DEC"]
    assert [row.reference_period_desc for row in result.data] == [
        day for day in days for _ in HOG_CLASSES
    ]
    assert [row.begin_code for row in result.data[:: len(HOG_CLASSES)]] == ["03", "06", "09", "12"]
    assert [row.class_desc for row in result.data] == HOG_CLASSES * len(days)
    # Upstream sends the rows class by class; the slice orders them by day, then class.
    upstream = recorded_chunk(fixtures_dir, "hogs_inventory_ia_2024")
    assert [record.class_desc for record in upstream[: len(days)]] == ["ALL CLASSES"] * len(days)
    march, december = result.data[0], result.data[3 * len(HOG_CLASSES)]
    assert (march.short_desc, march.value, march.value_number) == (
        "HOGS - INVENTORY", "25,200,000", Decimal("25200000"),
    )  # fmt: skip
    assert (december.reference_period_desc, december.class_desc, december.value_number) == (
        "FIRST OF DEC", "ALL CLASSES", Decimal("24300000"),
    )  # fmt: skip
    assert {row.state_alpha for row in result.data} == {"IA"}


def test_livestock_inventory_sends_one_class(replay_fixture: ReplayFixture) -> None:
    """``class_desc`` goes out beside the fixed filters; the national cattle answer is
    replayed for it, so only what was sent is checked."""
    fetched = replay_fixture("api_get", "cattle_inventory_us_2024")
    result = tasks.get_livestock_inventory(
        LivestockCommodity.CATTLE, 2024, class_desc="INCL CALVES"
    )
    assert result.meta.request["class_desc"] == "INCL CALVES"
    sent = sent_query(fetched)
    assert (sent["commodity_desc"], sent["class_desc"]) == ("CATTLE", "INCL CALVES")


def test_livestock_inventory_class_without_records_is_not_found(
    replay_fixture: ReplayFixture,
) -> None:
    """A ``class_desc`` with no record raises ``NotFoundError``, as the docstring says.

    Upstream's answer to filters that match nothing, HTTP 400 ``bad request - invalid
    query`` (``api_get/no_match``, recorded for ``year=1800``), is served for the class
    query, at no keyed cost; upstream's answer to this class itself is not recorded.
    """
    query = httpx.QueryParams({"class_desc": "NO SUCH CLASS"})
    unmatched = replay_fixture(
        "api_get", "no_match", url=f"{BASE_URL}/api_GET/?{query}", match_params=["class_desc"]
    )
    with pytest.raises(NotFoundError, match="invalid query"):
        tasks.get_livestock_inventory(LivestockCommodity.CATTLE, 2024, class_desc="NO SUCH CLASS")
    assert sent_query(unmatched)["class_desc"] == "NO SUCH CLASS"


def test_milk_production_state_monthly(replay_fixture: ReplayFixture, fixtures_dir: Path) -> None:
    fetched = replay_fixture("api_get", "milk_production_wi_2024_monthly")
    result = tasks.get_milk_production(
        2024, state=enums.StateAlpha.WI, frequency=enums.FreqDesc.MONTHLY
    )
    assert result.meta.request == {
        **MILK_FILTERS,
        "year": 2024,
        "agg_level_desc": "STATE",
        "state_alpha": "WI",
        "freq_desc": "MONTHLY",
    }
    assert_sent_as_recorded(fetched, fixtures_dir, "milk_production_wi_2024_monthly")
    assert (result.meta.endpoint, result.meta.total, result.meta.published_at) == (
        "api_GET", None, None,
    )  # fmt: skip
    assert all(isinstance(row, MilkProductionRecord) for row in result.data)
    assert [row.reference_period_desc for row in result.data] == MILK_PERIODS
    codes = [(row.begin_code, row.end_code) for row in result.data]
    assert codes == sorted(codes)
    assert {row.freq_desc for row in result.data} == {"MONTHLY"}
    assert {row.short_desc for row in result.data} == {"MILK - PRODUCTION, MEASURED IN LB"}
    assert {(row.state_alpha, row.unit_desc) for row in result.data} == {("WI", "LB")}
    january, first_quarter = result.data[0], result.data[1]
    assert (january.value, january.value_number) == ("2,711,000,000", Decimal("2711000000"))
    assert (first_quarter.begin_code, first_quarter.end_code, first_quarter.value_number) == (
        "01", "03", Decimal("8058000000"),
    )  # fmt: skip


def test_milk_production_national_year_then_months(
    replay_fixture: ReplayFixture, fixtures_dir: Path
) -> None:
    fetched = replay_fixture("api_get", "milk_production_us_2024")
    result = tasks.get_milk_production(2024)
    assert result.meta.request == {**MILK_FILTERS, "year": 2024, "agg_level_desc": "NATIONAL"}
    assert_sent_as_recorded(fetched, fixtures_dir, "milk_production_us_2024")
    assert (result.meta.endpoint, result.meta.total, result.meta.published_at) == (
        "api_GET", None, None,
    )  # fmt: skip
    assert len(result.data) == 17
    year, months = result.data[0], result.data[1:]
    assert (year.freq_desc, year.reference_period_desc, year.begin_code, year.end_code) == (
        "ANNUAL", "YEAR", "00", "00",
    )  # fmt: skip
    assert year.value_number == Decimal("225889000000")
    assert [row.reference_period_desc for row in months] == MILK_PERIODS
    assert {row.freq_desc for row in months} == {"MONTHLY"}
    # The class keeps the milk series alone: the manufactured dairy products upstream files
    # nationally under other classes of the same statistic and unit are left out.
    assert {(row.class_desc, row.short_desc) for row in result.data} == {
        ("ALL CLASSES", "MILK - PRODUCTION, MEASURED IN LB")
    }
    assert {row.state_alpha for row in result.data} == {"US"}


@pytest.mark.anyio
async def test_upstream_files_dairy_products_beside_milk_production_in_lb(
    replay_fixture: ReplayFixture, fixtures_dir: Path
) -> None:
    """The premise of the milk slice's ``class_desc``, recorded at layer 1 on 2026-10-28:
    nationally, its other fixed filters count 147 records for 2024, the milk series and
    ten manufactured dairy products (dry and condensed milk), of which ``ALL CLASSES``
    keeps the 17 of the milk series."""
    national = {**MILK_FILTERS, "year": 2024, "agg_level_desc": "NATIONAL"}
    every_class = {key: value for key, value in national.items() if key != "class_desc"}
    # The more specific fixture first: respx tries routes in order (conventions §10).
    milk = replay_fixture("get_counts", "milk_production_us_2024", match_params=["class_desc"])
    every = replay_fixture("get_counts", "milk_production_us_2024_every_class")
    assert (await api.get_counts(national)).count == 17
    assert (await api.get_counts(every_class)).count == 147
    for route, case in (
        (milk, "milk_production_us_2024"),
        (every, "milk_production_us_2024_every_class"),
    ):
        fixture = load_fixture(fixtures_dir / "get_counts" / f"{case}.json")
        assert sent_query(route) == recorded_query(fixture)


@pytest.mark.parametrize(
    "model",
    [
        CropProgressRecord,
        CountyEstimateRecord,
        AcreageRecord,
        PriceReceivedRecord,
        CensusFarmsRecord,
        LivestockInventoryRecord,
        MilkProductionRecord,
    ],
)
def test_projections_are_faithful(model: type[UpstreamModel]) -> None:
    record = QuickStatsRecord.model_validate({**EXAMPLE_RECORD, "CV (%)": "2.5"})
    overrides = {"cv_percent": Decimal("2.5")} if "cv_percent" in model.model_fields else {}
    projected = model.project(record, **overrides)
    assert_projection(projected, record, **overrides)
    assert set(model.model_fields) <= set(QuickStatsRecord.model_fields)
    assert projected.model_dump(mode="json")["value_number"] == 1234.5


SLICE_CALLS: dict[str, Callable[[], Result[Any]]] = {
    "corn_progress_planted_ia_2024": lambda: tasks.get_crop_progress(
        "CORN", 2024, state=enums.StateAlpha.IA, stage=enums.ProgressStage.PCT_PLANTED
    ),
    "hogs_inventory_ia_2024": lambda: tasks.get_livestock_inventory(
        LivestockCommodity.HOGS, 2024, state=enums.StateAlpha.IA
    ),
    "milk_production_wi_2024_monthly": lambda: tasks.get_milk_production(
        2024, state=enums.StateAlpha.WI, frequency=enums.FreqDesc.MONTHLY
    ),
}
"""A slice's call per ``api_get`` fixture it replays."""


@pytest.mark.parametrize("case", SLICE_CALLS)
def test_slices_skip_the_count_and_leave_published_at_empty(
    replay_fixture: Callable[[str, str], respx.Route], case: str
) -> None:
    counted = replay_fixture("get_counts", "corn_progress_planted_ia_2024")
    replay_fixture("api_get", case)
    result = SLICE_CALLS[case]()
    assert not counted.called
    assert result.meta.total is None
    assert result.meta.published_at is None
    assert result.meta.vintage is None
    assert all(row.load_time.tzinfo is None for row in result.data)


def test_get_data_keeps_the_count_and_leaves_published_at_empty(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    counted = replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    result = tasks.get_data(SMALL_FILTERS)
    assert counted.called
    assert result.meta.total == 22345
    assert result.meta.published_at is None


def test_acreage_forecasts_state_and_national(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_get", "corn_area_harvested_forecasts_ia_2023")
    result = tasks.get_acreage_forecasts(
        "CORN", 2023, AreaStatistic.AREA_HARVESTED, state=enums.StateAlpha.IA
    )
    assert result.meta.request["reference_period_desc__NE"] == "YEAR"
    assert "reference_period_desc" not in result.meta.request
    assert [row.reference_period_desc for row in result.data] == [
        "YEAR - JUN ACREAGE", "YEAR - AUG FORECAST", "YEAR - SEP FORECAST",
        "YEAR - OCT FORECAST", "YEAR - NOV FORECAST",
    ]  # fmt: skip
    assert [row.value_number for row in result.data][:2] == [
        Decimal("12900000"),
        Decimal("12900000"),
    ]
    loads = [row.load_time for row in result.data]
    assert loads == sorted(loads)


def test_acreage_forecasts_national(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_area_planted_forecasts_us_2023")
    result = tasks.get_acreage_forecasts("CORN", 2023, AreaStatistic.AREA_PLANTED)
    assert result.meta.request["agg_level_desc"] == "NATIONAL"
    assert [row.reference_period_desc for row in result.data][:2] == [
        "YEAR - MAR ACREAGE", "YEAR - JUN ACREAGE",
    ]  # fmt: skip
    assert result.data[0].value_number == Decimal("91996000")


@pytest.mark.anyio
async def test_mcp_tool_call_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("api_get", "corn_progress_planted_ia_2024")
    payload = await mcp_call(
        server,
        "usda_nass_get_crop_progress",
        {"commodity": "CORN", "year": 2024, "state": "IA", "stage": "PCT PLANTED"},
    )
    assert len(payload["data"]) == 11
    first = payload["data"][0]
    assert (first["value"], first["value_number"], first["week_ending"]) == ("0", 0.0, "2024-03-31")
    assert payload["meta"]["published_at"] is None
    with pytest.raises(AssertionError, match=r"InvalidRequestError.*comodity_desc"):
        await mcp_call(server, "usda_nass_get_counts", {"filters": {"comodity_desc": "CORN"}})
    text = await mcp_call_text(server, "usda_nass_get_data", {"filters": {"state_alpha": "XX"}})
    assert text.startswith(
        "error: UnknownCode: 'XX' is not a state_alpha in the packaged state_alpha list"
    )


def test_http_route_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.nass.http import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    replay_fixture("api_get", "corn_area_planted_ia_2023")
    response = client.get(
        "/usda-nass/get_acreage",
        params={"commodity": "CORN", "year": 2023, "statistic": "AREA PLANTED", "state": "IA"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"][0]["value_number"] == 13100000
    rejected = client.post("/usda-nass/get_counts", json={"filters": {"comodity_desc": "CORN"}})
    assert rejected.status_code == 422
    assert rejected.json()["title"] == "InvalidRequestError"
    unknown = client.post("/usda-nass/get_counts", json={"filters": {"state_alpha": "XX"}})
    assert unknown.status_code == 422
    assert unknown.json()["title"] == "UnknownCode"
    assert "packaged state_alpha list" in unknown.json()["detail"]


# --- get_census_farms, decision 9 (d) (Johannes, 2026-10-28) ---

CENSUS_FILTERS: dict[str, str | int] = {  # get_census_farms' fixed filters, counted 2026-10-28
    "source_desc": "CENSUS",
    "group_desc": "FARMS & LAND & ASSETS",
    "commodity_desc": "FARM OPERATIONS",
    "class_desc": "ALL CLASSES",
    "prodn_practice_desc": "ALL PRODUCTION PRACTICES",
    "domain_desc": "TOTAL",
}


def test_census_farms_national(replay_fixture: ReplayFixture) -> None:
    counted = replay_fixture("get_counts", "corn_progress_planted_ia_2024")
    fetched = replay_fixture("api_get", "census_farms_operations_us_2022")
    result = tasks.get_census_farms(2022, FarmStatistic.OPERATIONS)
    expected = {
        **CENSUS_FILTERS,
        "statisticcat_desc": "OPERATIONS",
        "year": "2022",
        "agg_level_desc": "NATIONAL",
    }
    assert sent_query(fetched) == {**expected, "format": "JSON", "key": REDACTED}
    assert result.meta.request == {**expected, "year": 2022}
    assert not counted.called  # a slice skips the count (decision 5)
    assert result.meta.endpoint == "api_GET"
    assert result.meta.total is None
    assert result.meta.published_at is None
    assert all(isinstance(row, CensusFarmsRecord) for row in result.data)
    assert [row.unit_desc for row in result.data] == ["OPERATIONS", "PCT OF FARM OPERATIONS"]
    farms, share = result.data
    assert (farms.value, farms.value_number) == ("1,900,487", Decimal("1900487"))
    assert farms.short_desc == "FARM OPERATIONS - NUMBER OF OPERATIONS"
    assert farms.cv_percent == Decimal("1.9")
    assert share.value_number == Decimal("100")
    assert share.cv_percent is None  # upstream prints "(L)" in CV (%)
    assert {(row.state_alpha, row.state_name, row.county_name) for row in result.data} == {
        ("US", "US TOTAL", ""),
    }
    assert {(row.source_desc, row.statisticcat_desc, row.year) for row in result.data} == {
        ("CENSUS", "OPERATIONS", 2022),
    }


def test_census_farms_state(replay_fixture: ReplayFixture) -> None:
    fetched = replay_fixture("api_get", "census_farms_area_operated_ia_2022")
    result = tasks.get_census_farms(2022, FarmStatistic.AREA_OPERATED, state=enums.StateAlpha.IA)
    sent = sent_query(fetched)
    assert {key: sent[key] for key in CENSUS_FILTERS} == CENSUS_FILTERS
    assert (sent["statisticcat_desc"], sent["agg_level_desc"], sent["state_alpha"]) == (
        "AREA OPERATED", "STATE", "IA",
    )  # fmt: skip
    assert result.meta.request["state_alpha"] == "IA"
    assert result.meta.total is None
    assert result.meta.published_at is None
    units = [row.unit_desc for row in result.data]
    assert units == sorted(units)
    assert set(units) == {
        "ACRES", "ACRES / OPERATION", "ACRES / OPERATION, MEDIAN", "PCT OF AG LAND",
        "PCT OF TOTAL LAND",
    }  # fmt: skip
    acres = result.data[0]
    assert (acres.unit_desc, acres.value_number) == ("ACRES", Decimal("29978165"))
    assert acres.short_desc == "FARM OPERATIONS - ACRES OPERATED"
    assert acres.cv_percent == Decimal("2.6")
    assert {(row.agg_level_desc, row.state_alpha, row.county_code) for row in result.data} == {
        ("STATE", "IA", ""),
    }


def test_census_farms_counties_of_a_state(replay_fixture: ReplayFixture) -> None:
    fetched = replay_fixture("api_get", "census_farms_operations_de_2022_county")
    result = tasks.get_census_farms(
        2022, FarmStatistic.OPERATIONS, state=enums.StateAlpha.DE, by_county=True
    )
    sent = sent_query(fetched)
    assert {key: sent[key] for key in CENSUS_FILTERS} == CENSUS_FILTERS
    assert (sent["agg_level_desc"], sent["state_alpha"], sent["year"]) == ("COUNTY", "DE", "2022")
    assert result.meta.request["agg_level_desc"] == "COUNTY"
    assert result.meta.total is None
    assert [(row.county_name, row.county_code, row.value_number) for row in result.data] == [
        ("KENT", "001", Decimal("770")),
        ("NEW CASTLE", "003", Decimal("335")),
        ("SUSSEX", "005", Decimal("1053")),
    ]  # sorted by county; upstream answered New Castle first
    assert {row.unit_desc for row in result.data} == {"OPERATIONS"}
    kent = result.data[0]
    assert (kent.asd_code, kent.asd_desc, kent.county_ansi) == ("50", "CENTRAL", "001")
    assert kent.cv_percent == Decimal("9.0")


def test_census_farms_county_area_units(replay_fixture: ReplayFixture) -> None:
    replay_fixture("api_get", "census_farms_area_operated_de_2022_county")
    result = tasks.get_census_farms(
        2022, FarmStatistic.AREA_OPERATED, state=enums.StateAlpha.DE, by_county=True
    )
    assert len(result.data) == 12
    order = [(row.state_alpha, row.county_name, row.unit_desc) for row in result.data]
    assert order == sorted(order)
    assert [row.county_name for row in result.data[:4]] == ["KENT"] * 4
    assert {row.unit_desc for row in result.data} == {
        "ACRES", "ACRES / OPERATION", "ACRES / OPERATION, MEDIAN", "PCT OF TOTAL LAND",
    }  # fmt: skip
    sussex_acres = next(
        row for row in result.data if row.county_name == "SUSSEX" and row.unit_desc == "ACRES"
    )
    assert sussex_acres.value_number == Decimal("262079")
    assert all(
        row.cv_percent is None for row in result.data if row.unit_desc == "PCT OF TOTAL LAND"
    )  # upstream prints "(H)" in CV (%)


def test_census_farms_every_county_sends_no_state(replay_fixture: ReplayFixture) -> None:
    # No every-county fixture: Delaware's answers a request without a state; only the query counts.
    fetched = replay_fixture("api_get", "census_farms_operations_de_2022_county")
    result = tasks.get_census_farms(2022, FarmStatistic.OPERATIONS, by_county=True)
    sent = sent_query(fetched)
    assert sent["agg_level_desc"] == "COUNTY"
    assert "state_alpha" not in sent
    assert {key: sent[key] for key in CENSUS_FILTERS} == CENSUS_FILTERS
    assert "state_alpha" not in result.meta.request
    assert result.meta.request["agg_level_desc"] == "COUNTY"


@pytest.mark.anyio
async def test_census_farms_over_mcp(replay_fixture: ReplayFixture) -> None:
    replay_fixture("api_get", "census_farms_operations_de_2022_county")
    payload = await mcp_call(
        server,
        "usda_nass_get_census_farms",
        {"year": 2022, "statistic": "OPERATIONS", "state": "DE", "by_county": True},
    )
    assert [row["county_name"] for row in payload["data"]] == ["KENT", "NEW CASTLE", "SUSSEX"]
    kent = payload["data"][0]
    assert (kent["value"], kent["value_number"], kent["cv_percent"]) == ("770", 770, 9.0)
    assert payload["meta"]["endpoint"] == "api_GET"
    assert payload["meta"]["total"] is None
    assert payload["meta"]["published_at"] is None
    request = payload["meta"]["request"]
    assert (request["agg_level_desc"], request["state_alpha"]) == ("COUNTY", "DE")


def test_census_farms_over_http(replay_fixture: ReplayFixture) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.nass.http import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    replay_fixture("api_get", "census_farms_area_operated_ia_2022")
    response = client.get(
        "/usda-nass/get_census_farms",
        params={"year": 2022, "statistic": "AREA OPERATED", "state": "IA"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 5
    assert (body["data"][0]["unit_desc"], body["data"][0]["value_number"]) == ("ACRES", 29978165)
    assert body["meta"]["request"]["agg_level_desc"] == "STATE"
    unknown = client.get("/usda-nass/get_census_farms", params={"year": 2022, "statistic": "FARMS"})
    assert unknown.status_code == 422


@pytest.mark.anyio
async def test_livestock_tools_end_to_end_over_mcp(replay_fixture: ReplayFixture) -> None:
    replay_fixture("api_get", "hogs_inventory_ia_2024", match_params=["commodity_desc"])
    replay_fixture("api_get", "milk_production_wi_2024_monthly", match_params=["commodity_desc"])
    inventory = await mcp_call(
        server,
        "usda_nass_get_livestock_inventory",
        {"commodity": "HOGS", "year": 2024, "state": "IA"},
    )
    assert len(inventory["data"]) == 28
    first = inventory["data"][0]
    assert (first["class_desc"], first["reference_period_desc"]) == ("ALL CLASSES", "FIRST OF MAR")
    assert (first["value"], first["value_number"]) == ("25,200,000", 25200000)
    assert inventory["meta"]["request"]["commodity_desc"] == "HOGS"
    assert inventory["meta"]["total"] is None
    assert inventory["meta"]["published_at"] is None
    milk = await mcp_call(
        server,
        "usda_nass_get_milk_production",
        {"year": 2024, "state": "WI", "frequency": "MONTHLY"},
    )
    assert [row["reference_period_desc"] for row in milk["data"]] == MILK_PERIODS
    assert milk["data"][0]["value_number"] == 2711000000
    refused = await mcp_call_text(
        server, "usda_nass_get_livestock_inventory", {"commodity": "GOATS", "year": 2024}
    )
    assert refused.startswith("error: InvalidRequestError: commodity")


def test_livestock_routes_end_to_end_over_http(replay_fixture: ReplayFixture) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.nass.http import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    replay_fixture("api_get", "cattle_inventory_us_2024", match_params=["commodity_desc"])
    replay_fixture("api_get", "milk_production_us_2024", match_params=["commodity_desc"])
    inventory = client.get(
        "/usda-nass/get_livestock_inventory", params={"commodity": "CATTLE", "year": 2024}
    )
    assert inventory.status_code == 200, inventory.text
    rows = inventory.json()["data"]
    assert len(rows) == 14
    herd = next(row for row in rows if row["class_desc"] == "INCL CALVES")
    assert herd["value_number"] == 87157400
    milk = client.get("/usda-nass/get_milk_production", params={"year": 2024})
    assert milk.status_code == 200, milk.text
    assert milk.json()["meta"]["request"]["class_desc"] == "ALL CLASSES"
    assert [row["freq_desc"] for row in milk.json()["data"]][:2] == ["ANNUAL", "MONTHLY"]
    refused = client.get(
        "/usda-nass/get_livestock_inventory", params={"commodity": "GOATS", "year": 2024}
    )
    assert refused.status_code == 422


# --- get_data(split_by_year=True), decision 8 (Johannes, 2026-10-26 and 2026-10-28) ---

IA_FILTERS: dict[str, str | int] = {"state_alpha": "IA", "year__GE": 2023, "year__LE": 2024}
IA_SINCE_FILTERS: dict[str, str | int] = {"state_alpha": "IA", "year__GE": 2023}
IA_COUNTS = {2023: 8635, 2024: 12799}  # get_counts/ia_2023_2024_<year>, recorded 2026-10-28
IA_CHUNKS = {2023: "corn_price_received_ia_2023", 2024: "corn_progress_planted_ia_2024"}
PRICES_FILTERS: dict[str, str | int] = {  # the filters of api_get/corn_price_received_ia_2023
    "commodity_desc": "CORN",
    "statisticcat_desc": "PRICE RECEIVED",
    "domain_desc": "TOTAL",
    "agg_level_desc": "STATE",
    "state_alpha": "IA",
    "year__GE": 2023,
    "year__LE": 2024,
}
PRICES_COUNTS = {2023: 13, 2024: 13}  # get_counts/corn_price_received_ia_<year>, 2026-10-28
CORN_COUNTY_FILTERS: dict[str, str | int] = {
    "commodity_desc": "CORN",
    "agg_level_desc": "COUNTY",
    "year__GE": 2020,
    "year__LE": 2021,
}

THROUGH_THE_LIMIT = (  # QueryTooLarge's hint for a whole query (conventions §8)
    "Narrow the filters, for example by year, state_alpha, agg_level_desc or "
    "statisticcat_desc, or call get_data with split_by_year=True (over MCP, the tool "
    "usda_nass_get_data) on a bounded year range of at most 20 years in Python and over "
    "HTTP, 5 by default on the MCP server (--split-years)."
)


def sent_in_order(router: respx.MockRouter) -> list[tuple[str, str | None]]:
    """``(path, year)`` of every request the router answered, oldest first.

    Read from the URLs with credentials scrubbed, as ``sent_urls`` reads one route's, so
    that the order across routes shows and no request stays in the test's frame.
    """
    urls = [httpx.URL(scrub_url(call.request.url)) for call in router.calls]
    return [(url.path, url.params.get("year")) for url in urls]


def recorded_chunk(fixtures_dir: Path, case: str) -> list[QuickStatsRecord]:
    """The records an ``api_get`` fixture replays, parsed as the wrapper parses them."""
    fixture = load_fixture(fixtures_dir / "api_get" / f"{case}.json")
    return ApiGetResponse.model_validate_json(fixture.response.content).data


def mount_ia_split(replay_fixture: ReplayFixture) -> dict[str, respx.Route]:
    """Mount the Iowa split of ``IA_FILTERS``: the yearly counts and chunks, no range count.

    ``year__GE`` with ``year__LE`` is split without a count of the range, which Quick Stats
    would count as ``year__GE`` alone (the characterisation tests below). The yearly counts
    are Quick Stats' own for the queries the split sends (``state_alpha=IA&year=<y>``). The
    chunks replay a real Iowa answer of each year (``api_get/corn_price_received_ia_2023``,
    ``api_get/corn_progress_planted_ia_2024``), a slice of that year's records: a whole
    year's answer runs to megabytes, and the recorder cuts no JSON object (``max_bytes=``,
    ADR-0019 decision 5).
    """
    routes = {
        f"count_{year}": replay_fixture("get_counts", f"ia_2023_2024_{year}", match_params=["year"])
        for year in IA_COUNTS
    }
    routes |= {
        f"fetch_{year}": replay_fixture("api_get", case, match_params=["year"])
        for year, case in IA_CHUNKS.items()
    }
    return routes


def mount_real_split(replay_fixture: ReplayFixture) -> dict[str, respx.Route]:
    """Mount the real split of ``PRICES_FILTERS``: each year's count and answer, recorded
    for the very query the split sends (``get_counts/corn_price_received_ia_<year>`` and
    ``api_get/corn_price_received_ia_2024``, recorded 2026-10-28;
    ``api_get/corn_price_received_ia_2023``, recorded 2026-10-22), whole, not sliced."""
    routes: dict[str, respx.Route] = {}
    for year in PRICES_COUNTS:
        case = f"corn_price_received_ia_{year}"
        routes[f"count_{year}"] = replay_fixture("get_counts", case, match_params=["year"])
        routes[f"fetch_{year}"] = replay_fixture("api_get", case, match_params=["year"])
    return routes


def test_split_by_year_is_real_end_to_end(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, fixtures_dir: Path
) -> None:
    """The split's data path on recorded answers only: every query it sends is the one
    recorded, and the result is the two years' answers whole, in year order."""
    routes = mount_real_split(replay_fixture)
    result = tasks.get_data(PRICES_FILTERS, split_by_year=True)
    assert sent_in_order(respx_mock) == [
        ("/api/get_counts/", "2023"),
        ("/api/get_counts/", "2024"),
        ("/api/api_GET/", "2023"),
        ("/api/api_GET/", "2024"),
    ]
    for year in PRICES_COUNTS:
        for kind, endpoint in (("count", "get_counts"), ("fetch", "api_get")):
            fixture = load_fixture(fixtures_dir / endpoint / f"corn_price_received_ia_{year}.json")
            assert sent_query(routes[f"{kind}_{year}"]) == recorded_query(fixture)
    chunks = {
        year: recorded_chunk(fixtures_dir, f"corn_price_received_ia_{year}")
        for year in PRICES_COUNTS
    }
    assert len(result.data) == result.meta.total == sum(PRICES_COUNTS.values()) == 26
    assert result.data == chunks[2023] + chunks[2024]  # year order, each in upstream's order
    assert [row.year for row in result.data] == [2023] * 13 + [2024] * 13
    assert result.meta.endpoint == "api_GET"
    assert result.meta.request == {**PRICES_FILTERS, "split_by_year": True}


def test_get_data_splits_a_two_sided_year_range_by_year(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, fixtures_dir: Path
) -> None:
    """Every year counted first, then fetched in year order; no count of the range."""
    routes = mount_ia_split(replay_fixture)
    result = tasks.get_data(IA_FILTERS, split_by_year=True)
    chunks = {year: recorded_chunk(fixtures_dir, case) for year, case in IA_CHUNKS.items()}
    # Upstream's yearly counts summed, never len(data): the chunks replay slices (§4).
    assert result.meta.total == IA_COUNTS[2023] + IA_COUNTS[2024] == 21434
    assert len(result.data) == len(chunks[2023]) + len(chunks[2024]) == 24
    assert [row.year for row in result.data] == [2023] * 13 + [2024] * 11
    keys = [(row.year, row.reference_period_desc, row.week_ending) for row in result.data]
    assert keys == [
        (row.year, row.reference_period_desc, row.week_ending)
        for row in chunks[2023] + chunks[2024]
    ]  # each year's records in upstream's order
    assert result.meta.endpoint == "api_GET"
    assert result.meta.request == {**IA_FILTERS, "split_by_year": True}
    assert sent_in_order(respx_mock) == [
        ("/api/get_counts/", "2023"),
        ("/api/get_counts/", "2024"),
        ("/api/api_GET/", "2023"),
        ("/api/api_GET/", "2024"),
    ]
    for year in IA_COUNTS:
        sent = {"state_alpha": "IA", "year": str(year), "key": REDACTED}
        assert sent_query(routes[f"count_{year}"]) == sent
        assert sent_query(routes[f"fetch_{year}"]) == {**sent, "format": "JSON"}


def test_split_of_year_ge_alone_keeps_the_first_count(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """``year__GE`` alone is an open range upstream serves whole, so it is counted first and
    split only over the limit. ``get_counts/corn_county_2020_2021``, which upstream counted
    as ``year__GE=2020`` alone (85,535), stands in for Iowa's count from 2023 on (31,461,
    within the limit) to drive the split; ``get_counts/no_match`` (a count of 0) answers
    the years from 2025 to the current one, whose counts are not recorded."""
    routes = mount_ia_split(replay_fixture)
    first = replay_fixture(
        "get_counts",
        "corn_county_2020_2021",
        url=f"{BASE_URL}/get_counts/?state_alpha=IA&year__GE=2023",
        match_params=["year__GE"],
    )
    later = replay_fixture("get_counts", "no_match")
    result = tasks.get_data(IA_SINCE_FILTERS, split_by_year=True)
    years = range(2023, datetime.now(UTC).year + 1)
    assert sent_in_order(respx_mock) == [
        ("/api/get_counts/", None),
        *(("/api/get_counts/", str(year)) for year in years),
        ("/api/api_GET/", "2023"),
        ("/api/api_GET/", "2024"),
    ]
    assert sent_query(first) == {"state_alpha": "IA", "year__GE": "2023", "key": REDACTED}
    sent_later = [httpx.URL(url).params.get("year") for url in sent_urls(later)]
    assert sent_later == [str(year) for year in years if year not in IA_COUNTS]
    assert (routes["fetch_2023"].call_count, routes["fetch_2024"].call_count) == (1, 1)
    assert [row.year for row in result.data] == [2023] * 13 + [2024] * 11
    assert result.meta.total == sum(IA_COUNTS.values()) == 21434  # the years counted 0 add 0
    assert result.meta.request == {**IA_SINCE_FILTERS, "split_by_year": True}


def test_get_data_without_split_refuses_the_two_year_query(
    replay_fixture: ReplayFixture,
) -> None:
    counted = replay_fixture("get_counts", "corn_county_2020_2021")
    fetched = replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        tasks.get_data(CORN_COUNTY_FILTERS)
    assert (info.value.count, info.value.year) == (85535, None)
    assert str(info.value).startswith("query would return 85,535 records")
    assert str(info.value).endswith(THROUGH_THE_LIMIT)
    assert counted.call_count == 1
    assert not fetched.called


@pytest.mark.anyio
async def test_query_too_large_names_the_way_through_the_limit(
    replay_fixture: ReplayFixture,
) -> None:
    """Narrower filters, or ``get_data`` with ``split_by_year`` on at most 20 years
    (conventions §8); a year over the limit on its own names narrower filters only."""
    assert SPLIT_CEILING == 20
    assert str(QueryTooLarge(85_535)).endswith(THROUGH_THE_LIMIT)
    assert str(QueryTooLarge(None)).endswith(THROUGH_THE_LIMIT)  # upstream's HTTP 413
    alone = str(QueryTooLarge(57_873_464, year=2021))
    assert "split_by_year cannot fetch it. Narrow the filters, for example by state_alpha" in alone
    assert "split_by_year=True" not in alone
    replay_fixture("get_counts", "corn_county_2020_2021")
    text = await mcp_call_text(server, "usda_nass_get_data", {"filters": CORN_COUNTY_FILTERS})
    assert text.startswith("error: QueryTooLarge: query would return 85,535 records")
    assert text.endswith(THROUGH_THE_LIMIT)


def test_split_refuses_a_year_over_the_limit_before_fetching(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """2020 counts 7,727 (recorded 2026-10-28); the whole database's count,
    ``get_counts/unknown_column``, stands in for a 2021 over the limit on its own."""
    count_2020 = replay_fixture("get_counts", "corn_county_2020_2021_2020", match_params=["year"])
    count_2021 = replay_fixture(
        "get_counts",
        "unknown_column",
        url=f"{BASE_URL}/get_counts/?year=2021",
        match_params=["year"],
    )
    fetched = replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        tasks.get_data(CORN_COUNTY_FILTERS, split_by_year=True)
    assert (info.value.count, info.value.year) == (57873464, 2021)
    assert str(info.value).startswith(
        "year 2021 alone would return 57,873,464 records; Quick Stats serves at most 50,000"
    )
    assert "split_by_year cannot fetch it" in str(info.value)
    assert (count_2020.call_count, count_2021.call_count) == (1, 1)
    # No count of the range, and nothing fetched before every year is counted, though 2020 fits.
    assert sent_in_order(respx_mock) == [("/api/get_counts/", "2020"), ("/api/get_counts/", "2021")]
    assert not fetched.called


def test_split_of_one_year_over_the_limit_refuses_after_the_first_count(
    replay_fixture: ReplayFixture,
) -> None:
    counted = replay_fixture("get_counts", "unknown_column")
    fetched = replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        tasks.get_data({"commodity_desc": "CORN", "year": 2021}, split_by_year=True)
    assert (info.value.count, info.value.year) == (57873464, 2021)
    assert counted.call_count == 1  # the year's count is the first count
    assert not fetched.called


def test_split_counts_a_year_past_the_current_one_without_refusing_it(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """The ``year`` form keeps no future-year refusal (Johannes, 2026-10-28): with the flag,
    next year is counted as without it. ``get_counts/no_match`` (a count of 0, recorded for
    ``year=1800``) answers it, moved with ``url=``: an empty result, nothing fetched."""
    next_year = datetime.now(UTC).year + 1
    counted = replay_fixture(
        "get_counts",
        "no_match",
        url=f"{BASE_URL}/get_counts/?year={next_year}",
        match_params=["year"],
    )
    fetched = replay_fixture("api_get", "no_match")
    filters: dict[str, str | int] = {
        "commodity_desc": "CORN",
        "state_alpha": "VA",
        "year": next_year,
    }
    result = tasks.get_data(filters, split_by_year=True)
    assert (result.data, result.meta.total) == ([], 0)
    assert result.meta.request == {**filters, "split_by_year": True}
    assert sent_query(counted) == {
        "commodity_desc": "CORN",
        "state_alpha": "VA",
        "year": str(next_year),
        "key": REDACTED,
    }
    assert counted.call_count == len(respx_mock.calls) == 1  # one count, no fetch
    assert not fetched.called


@pytest.mark.parametrize(
    "years",
    [
        {},
        {"year__LE": 2021},
        {"year__LT": 2021},
        {"year__GT": 2020},
        {"year__NE": 2020},
        {"year__LIKE": "202"},
        {"year": 2021, "year__GE": 2020},
        {"year__GE": 2019, "year__LE": 2021, "year__NE": 2020},
    ],
)
def test_split_refuses_an_unbounded_year_range_before_any_call(
    respx_mock: respx.MockRouter, years: dict[str, str | int]
) -> None:
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data({"commodity_desc": "CORN", **years}, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value).startswith(
        "split_by_year needs the years bounded in one of three forms: year (one year, "
        "e.g. 2022), year__GE with year__LE (e.g. 2020 and 2023, neither past the current "
        "UTC year), or year__GE alone (up to the current UTC year); year filters given: "
    )
    assert str(info.value).endswith(f"given: {', '.join(sorted(years)) or 'none'}.")
    assert status_for(info.value) == 422
    assert not respx_mock.calls


@pytest.mark.parametrize(
    ("years", "text"),
    [
        ({"year__GE": 2024, "year__LE": 2023}, "the years run from 2024 to 2023"),
        ({"year": "2O22"}, "year='2O22' is not a year"),
    ],
)
def test_split_refuses_a_range_without_a_year_before_any_call(
    respx_mock: respx.MockRouter, years: dict[str, str | int], text: str
) -> None:
    with pytest.raises(InvalidRequestError, match=text):
        tasks.get_data({"commodity_desc": "CORN", **years}, split_by_year=True)
    assert not respx_mock.calls


@pytest.mark.parametrize(
    ("first", "last", "named"),
    [
        (-1, 1, "year__LE"),  # ends past the current year
        (1, 2, "year__LE"),  # wholly past it: the end is named
        (1, -1, "year__GE"),  # starts past it, and past its end
        (1, None, "year__GE"),  # year__GE alone, past the current year
    ],
)
def test_split_refuses_a_bound_past_the_current_utc_year_before_any_call(
    respx_mock: respx.MockRouter, first: int, last: int | None, named: str
) -> None:
    """A year Quick Stats has not published counts 0, as a year without records does, so
    the range must end by the current UTC year (Johannes, 2026-10-28). Offsets from the
    current year, read at call time."""
    now = datetime.now(UTC).year
    years: dict[str, str | int] = {"year__GE": now + first}
    if last is not None:
        years["year__LE"] = now + last
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data({"commodity_desc": "CORN", **years}, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value) == (
        f"split_by_year: {named}={years[named]} is past the current UTC year, {now}; the "
        f"range must end by {now}."
    )
    assert status_for(info.value) == 422
    assert not respx_mock.calls


def test_split_bounds_year_ge_alone_at_the_current_utc_year(
    replay_fixture: ReplayFixture,
) -> None:
    """``get_counts/no_match`` (a count of 0, recorded for year=1800) answers every year, so
    the range runs to the current year without a fetch."""
    start = datetime.now(UTC).year - 1
    first = replay_fixture(
        "get_counts",
        "corn_county_2020_2021",
        url=f"{BASE_URL}/get_counts/?year__GE={start}",
        match_params=["year__GE"],
    )
    yearly = replay_fixture("get_counts", "no_match")
    fetched = replay_fixture("api_get", "no_match")
    result = tasks.get_data({"state_alpha": "IA", "year__GE": start}, split_by_year=True)
    assert first.call_count == 1
    sent = [httpx.URL(url).params.get("year") for url in sent_urls(yearly)]
    assert sent == [str(start), str(start + 1)]
    assert sent[-1] == str(datetime.now(UTC).year)
    assert (result.data, result.meta.total) == ([], 0)
    assert not fetched.called


def ceiling_message(first: int, last: int) -> str:
    return (
        f"split_by_year covers at most 20 years per call; the years run from {first} to "
        f"{last}, {last - first + 1} years. Give a shorter range, e.g. year__GE={last - 19} "
        f"with year__LE={last}."
    )


def test_split_refuses_a_two_sided_range_of_more_than_twenty_years_before_any_call(
    respx_mock: respx.MockRouter,
) -> None:
    """The ceiling of conventions §4, the most years one call splits into: a two-sided
    range always splits, so 21 years, one too many, are refused before any call."""
    filters: dict[str, str | int] = {"commodity_desc": "CORN", "year__GE": 2000, "year__LE": 2020}
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data(filters, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value) == ceiling_message(2000, 2020)
    assert status_for(info.value) == 422
    assert not respx_mock.calls


def test_split_fetches_a_fitting_year_ge_range_whole_however_far_back(
    replay_fixture: ReplayFixture,
) -> None:
    """The ceiling binds a split, not the filters: ``year__GE`` 25 years back with a count
    within the limit is fetched whole. ``get_counts/corn_va_since_2012`` (22,345) stands
    in for the count, and ``api_get/corn_va_2012_area_planted`` replays a slice."""
    start = datetime.now(UTC).year - 25
    counted = replay_fixture(
        "get_counts",
        "corn_va_since_2012",
        url=f"{BASE_URL}/get_counts/?year__GE={start}",
        match_params=["year__GE"],
    )
    fetched = replay_fixture(
        "api_get",
        "corn_va_2012_area_planted",
        url=f"{BASE_URL}/api_GET/?year__GE={start}",
        match_params=["year__GE"],
    )
    filters: dict[str, str | int] = {
        "commodity_desc": "CORN",
        "state_alpha": "VA",
        "year__GE": start,
    }
    result = tasks.get_data(filters, split_by_year=True)
    assert (counted.call_count, fetched.call_count) == (1, 1)
    assert sent_query(fetched) == {
        **{key: str(value) for key, value in filters.items()},
        "format": "JSON",
        "key": REDACTED,
    }
    assert result.meta.total == 22345
    assert len(result.data) == 2
    assert result.meta.request == {**filters, "split_by_year": True}


@pytest.mark.parametrize("back", [20, 25])
def test_split_of_year_ge_alone_refuses_more_than_twenty_years_after_the_first_count(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter, back: int
) -> None:
    """Over the limit, ``year__GE`` alone 21 or 26 years back would split into more years
    than the ceiling: refused after the first count, before any yearly count or fetch.
    ``get_counts/corn_county_2020_2021`` (85,535) stands in for the count."""
    now = datetime.now(UTC).year
    start = now - back
    counted = replay_fixture(
        "get_counts",
        "corn_county_2020_2021",
        url=f"{BASE_URL}/get_counts/?year__GE={start}",
        match_params=["year__GE"],
    )
    fetched = replay_fixture("api_get", "exceeds_limit")
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data({"commodity_desc": "CORN", "year__GE": start}, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value) == ceiling_message(start, now)
    assert counted.call_count == 1
    assert sent_in_order(respx_mock) == [("/api/get_counts/", None)]
    assert not fetched.called


def test_split_accepts_twenty_years_of_a_two_sided_range(
    replay_fixture: ReplayFixture,
) -> None:
    """``get_counts/no_match`` (a count of 0) answers every year: twenty counts, no fetch."""
    yearly = replay_fixture("get_counts", "no_match")
    fetched = replay_fixture("api_get", "no_match")
    filters: dict[str, str | int] = {"commodity_desc": "CORN", "year__GE": 2001, "year__LE": 2020}
    result = tasks.get_data(filters, split_by_year=True)
    sent = [httpx.URL(url).params.get("year") for url in sent_urls(yearly)]
    assert sent == [str(year) for year in range(2001, 2021)]
    assert (result.data, result.meta.total) == ([], 0)
    assert not fetched.called


def test_split_accepts_twenty_years_from_year_ge_on(
    replay_fixture: ReplayFixture,
) -> None:
    """Over the limit, ``year__GE`` alone 19 years back splits into 20 years: the first
    count, ``get_counts/corn_county_2020_2021`` moved, then ``get_counts/no_match`` (a
    count of 0) for every year, and nothing fetched."""
    now = datetime.now(UTC).year
    start = now - 19
    first = replay_fixture(
        "get_counts",
        "corn_county_2020_2021",
        url=f"{BASE_URL}/get_counts/?year__GE={start}",
        match_params=["year__GE"],
    )
    yearly = replay_fixture("get_counts", "no_match")
    fetched = replay_fixture("api_get", "no_match")
    result = tasks.get_data({"commodity_desc": "CORN", "year__GE": start}, split_by_year=True)
    assert first.call_count == 1
    sent = [httpx.URL(url).params.get("year") for url in sent_urls(yearly)]
    assert sent == [str(year) for year in range(start, now + 1)]
    assert len(sent) == 20
    assert (result.data, result.meta.total) == ([], 0)
    assert not fetched.called


@pytest.mark.parametrize(
    ("filters", "count_case", "fetch_case", "total"),
    [
        (IA_SINCE_FILTERS, "ia_since_2023", "corn_price_received_ia_2023", 31461),
        (SMALL_FILTERS, "corn_va_since_2012", "corn_va_2012_area_planted", 22345),
    ],
)
def test_split_by_year_fetches_once_when_the_count_fits(
    replay_fixture: ReplayFixture,
    filters: dict[str, str | int],
    count_case: str,
    fetch_case: str,
    total: int,
) -> None:
    """``year__GE`` alone and ``year``: a count within the limit is fetched in one call
    with the filters as given; the fetch replays a slice of the answer (``mount_ia_split``
    says why)."""
    counted = replay_fixture("get_counts", count_case)
    fetched = replay_fixture("api_get", fetch_case)
    result = tasks.get_data(filters, split_by_year=True)
    assert (counted.call_count, fetched.call_count) == (1, 1)
    assert sent_query(fetched) == {
        **{key: str(value) for key, value in filters.items()},
        "format": "JSON",
        "key": REDACTED,
    }
    assert result.meta.total == total
    assert result.meta.request == {**filters, "split_by_year": True}


@pytest.mark.anyio
async def test_upstream_counts_year_ge_with_year_le_as_year_ge_alone(
    replay_fixture: ReplayFixture,
) -> None:
    """Characterisation at layer 1, recorded 2026-10-28: Quick Stats counts
    ``year__GE=2023&year__LE=2024`` for Iowa as ``year__GE=2023`` alone, 31,461, more
    than 2023 and 2024 count together; ``split_by_year``'s docstring says so."""
    ranged = replay_fixture("get_counts", "ia_2023_2024", match_params=["year__LE"])
    replay_fixture("get_counts", "ia_since_2023", match_params=["year__GE"])
    for year in IA_COUNTS:
        replay_fixture("get_counts", f"ia_2023_2024_{year}", match_params=["year"])
    counted = (await api.get_counts(IA_FILTERS)).count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).count
    yearly = [
        (await api.get_counts({"state_alpha": "IA", "year": year})).count for year in IA_COUNTS
    ]
    assert sent_urls(ranged) == [
        f"{BASE_URL}/get_counts/?state_alpha=IA&year__GE=2023&year__LE=2024&key={REDACTED}"
    ]
    assert counted == since == 31461
    assert yearly == [IA_COUNTS[2023], IA_COUNTS[2024]]
    assert sum(yearly) < counted


@pytest.mark.anyio
async def test_upstream_counts_year_le_sent_before_year_ge_as_year_ge_alone(
    replay_fixture: ReplayFixture,
) -> None:
    """Characterisation at layer 1, recorded 2026-10-28: with ``year__LE=2024`` sent
    before ``year__GE=2023``, Quick Stats still counts Iowa as ``year__GE=2023`` alone,
    31,461, so the order of the two bounds in the query does not change the count."""
    ranged = replay_fixture("get_counts", "ia_2023_2024_le_first", match_params=["year__LE"])
    replay_fixture("get_counts", "ia_since_2023", match_params=["year__GE"])
    filters: dict[str, str | int] = {"state_alpha": "IA", "year__LE": 2024, "year__GE": 2023}
    counted = (await api.get_counts(filters)).count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).count
    assert sent_urls(ranged) == [
        f"{BASE_URL}/get_counts/?state_alpha=IA&year__LE=2024&year__GE=2023&key={REDACTED}"
    ]
    assert counted == since == 31461
    assert counted > sum(IA_COUNTS.values())


@pytest.mark.anyio
async def test_upstream_counts_year_ge_with_year_lt_as_more_than_year_ge_alone(
    replay_fixture: ReplayFixture,
) -> None:
    """Characterisation at layer 1, recorded 2026-10-28: Quick Stats counts Iowa for
    ``year__GE=2023&year__LT=2025`` as 1,425,389, neither 2023 and 2024 together (21,434)
    nor ``year__GE=2023`` alone (31,461): beside ``year__LT`` the lower bound does not
    narrow the count."""
    ranged = replay_fixture("get_counts", "ia_2023_lt_2025", match_params=["year__LT"])
    replay_fixture("get_counts", "ia_since_2023", match_params=["year__GE"])
    filters: dict[str, str | int] = {"state_alpha": "IA", "year__GE": 2023, "year__LT": 2025}
    counted = (await api.get_counts(filters)).count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).count
    assert sent_urls(ranged) == [
        f"{BASE_URL}/get_counts/?state_alpha=IA&year__GE=2023&year__LT=2025&key={REDACTED}"
    ]
    assert counted == 1425389
    assert counted > since > sum(IA_COUNTS.values())


@pytest.mark.anyio
async def test_split_by_year_over_mcp(replay_fixture: ReplayFixture) -> None:
    mount_real_split(replay_fixture)
    payload = await mcp_call(
        server, "usda_nass_get_data", {"filters": PRICES_FILTERS, "split_by_year": True}
    )
    assert [row["year"] for row in payload["data"]] == [2023] * 13 + [2024] * 13
    assert payload["meta"]["total"] == 26
    assert payload["meta"]["request"] == {**PRICES_FILTERS, "split_by_year": True}
    assert "note" not in payload  # 26 rows, under the default cap
    text = await mcp_call_text(
        server, "usda_nass_get_data", {"filters": {"year__GT": 2020}, "split_by_year": True}
    )
    assert text.startswith("error: InvalidRequestError: split_by_year needs the years bounded")


def test_split_by_year_over_http(replay_fixture: ReplayFixture) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from xippios.usda.nass.http import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    mount_real_split(replay_fixture)
    response = client.post(
        "/usda-nass/get_data", json={"filters": PRICES_FILTERS, "split_by_year": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert [row["year"] for row in body["data"]] == [2023] * 13 + [2024] * 13
    assert body["meta"]["total"] == 26
    assert body["meta"]["request"] == {**PRICES_FILTERS, "split_by_year": True}
    refused = client.post(
        "/usda-nass/get_data", json={"filters": {"year__LE": 2021}, "split_by_year": True}
    )
    assert refused.status_code == 422
    assert refused.json()["title"] == "InvalidRequestError"
    assert "year__GE with year__LE" in refused.json()["detail"]


# --- the split ceiling on the MCP server, --split-years (Johannes, 2026-10-28) ---

SPLIT_REFUSAL = (
    "the split ceiling, --split-years on the MCP server, must be a whole number of years "
    "from 1 to 20, got {!r}."
)


@pytest.fixture
def restore_split_ceiling() -> Iterator[None]:
    """The split ceiling is process-wide: a test that sets it leaves the Python API's,
    ``SPLIT_CEILING``, for the tests after it."""
    yield
    tasks.set_split_ceiling(SPLIT_CEILING)


def test_the_split_ceilings_and_the_option() -> None:
    """20 years for the Python API and the HTTP router, the ceiling in force while no MCP
    server applied its options; ``--split-years`` on core's parser, 5 by default."""
    assert (SPLIT_CEILING, MCP_SPLIT_YEARS) == (20, 5)
    assert tasks.split_ceiling() == 20
    parser = build_parser(server.name, add_options=tasks.mcp_add_options)
    assert parser.parse_args([]).split_years == 5
    assert parser.parse_args(["--split-years", "3"]).split_years == 3
    assert parser.parse_args(["--split-years", "25"]).split_years == 25, (
        "the range is checked when the option is applied, then exit status 2"
    )
    assert (
        "--split-years YEARS most years one usda_nass_get_data call with split_by_year "
        "splits into, 1 to 20 (default 5); up to two keyed calls a year, so 5 years take at "
        "most 11 calls"
    ) in " ".join(parser.format_help().split())


@pytest.mark.usefixtures("restore_split_ceiling")
@pytest.mark.parametrize("years", [1, 5, 20])
def test_set_split_ceiling_takes_1_to_20(years: int) -> None:
    tasks.set_split_ceiling(years)
    assert tasks.split_ceiling() == years


@pytest.mark.usefixtures("restore_split_ceiling")
@pytest.mark.parametrize("years", [0, 21, -5, True, "5", 5.0, None])
def test_set_split_ceiling_refuses_anything_else(years: object) -> None:
    """Never above 20, never below 1, never a bool, a text or a float; the ceiling in
    force stays."""
    tasks.set_split_ceiling(10)
    with pytest.raises(InvalidRequestError) as info:
        tasks.set_split_ceiling(years)  # type: ignore[arg-type]
    assert str(info.value) == SPLIT_REFUSAL.format(years)
    assert tasks.split_ceiling() == 10


@pytest.mark.usefixtures("restore_split_ceiling")
def test_the_hooks_apply_the_option_through_cores_parser() -> None:
    """``--split-years 3`` applies 3, no option applies the default 5, and 25 is refused
    with the ceiling unchanged; ``mcp_apply_options`` returns the server itself."""
    parser = build_parser(server.name, add_options=tasks.mcp_add_options)
    for argv, expected in ((["--split-years", "3"], 3), ([], 5)):
        assert tasks.mcp_apply_options(parser.parse_args(argv), server) is server
        assert tasks.split_ceiling() == expected
    with pytest.raises(InvalidRequestError) as info:
        tasks.mcp_apply_options(parser.parse_args(["--split-years", "25"]), server)
    assert str(info.value) == SPLIT_REFUSAL.format(25)
    assert tasks.split_ceiling() == 5


@pytest.mark.usefixtures("restore_split_ceiling")
def test_the_entry_point_applies_split_years_or_exits_with_status_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mcp.run`` hands the hooks to core's ``main``: without the option the MCP server
    starts with 5, ``--split-years 3`` sets 3 before the server runs, on stdio; 25 or 0
    ends the process with exit status 2 and the refusal on stderr, before anything is
    served, the ceiling unchanged. The server's ``run`` is replaced, so nothing is served.
    The direct call to ``main`` lets mypy check the hooks against its signature."""
    served: list[dict[str, object]] = []
    monkeypatch.setattr(server, "run", lambda **kwargs: served.append(kwargs))
    monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp"])
    run()
    assert tasks.split_ceiling() == 5
    monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp", "--split-years", "3"])
    run()
    assert tasks.split_ceiling() == 3
    assert served == [{"transport": "stdio"}, {"transport": "stdio"}]
    for value in ("25", "0"):
        monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp", "--split-years", value])
        with pytest.raises(SystemExit) as exit_info:
            run()
        assert exit_info.value.code == 2
        assert capsys.readouterr().err.endswith(f"error: {SPLIT_REFUSAL.format(int(value))}\n")
    with pytest.raises(SystemExit) as direct:
        main(
            server,
            ["--split-years", "21"],
            add_options=tasks.mcp_add_options,
            apply_options=tasks.mcp_apply_options,
        )
    assert direct.value.code == 2
    assert capsys.readouterr().err.endswith(f"error: {SPLIT_REFUSAL.format(21)}\n")
    assert len(served) == 2, "nothing served after a refusal"
    assert tasks.split_ceiling() == 3


@pytest.mark.anyio
@pytest.mark.usefixtures("restore_split_ceiling")
async def test_the_mcp_server_refuses_a_split_beyond_its_ceiling_before_any_call(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """With the MCP server's default, 5, a two-sided range of six years is refused before
    any call (respx is active with no route mounted), naming the ceiling set for this
    process; the ceiling is process-wide, so a Python call meets it too. Five years pass:
    ``get_counts/no_match`` (a count of 0) answers each year, nothing is fetched."""
    assert tasks.mcp_apply_options(argparse.Namespace(split_years=5), server) is server
    six: dict[str, str | int] = {"commodity_desc": "CORN", "year__GE": 2015, "year__LE": 2020}
    refusal = (
        "split_by_year covers at most 5 years per call, the ceiling set for this process "
        "(the MCP server starts with 5 by default; --split-years raises it, up to 20); the "
        "years run from 2015 to 2020, 6 years. Give a shorter range, e.g. year__GE=2016 "
        "with year__LE=2020."
    )
    text = await mcp_call_text(
        server, "usda_nass_get_data", {"filters": six, "split_by_year": True}
    )
    assert text == f"error: InvalidRequestError: {refusal}"
    with pytest.raises(InvalidRequestError) as python:
        await tasks.get_data_async(six, split_by_year=True)
    assert str(python.value) == refusal
    assert not respx_mock.calls, "refused before any call"
    yearly = replay_fixture("get_counts", "no_match")
    fetched = replay_fixture("api_get", "no_match")
    payload = await mcp_call(
        server,
        "usda_nass_get_data",
        {"filters": {**six, "year__GE": 2016}, "split_by_year": True},
    )
    assert (payload["data"], payload["meta"]["total"]) == ([], 0)
    sent = [httpx.URL(url).params.get("year") for url in sent_urls(yearly)]
    assert sent == [str(year) for year in range(2016, 2021)]
    assert not fetched.called
