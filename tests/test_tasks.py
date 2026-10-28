"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from xippios.core import (
    InvalidRequestError,
    MemoryCache,
    NotFoundError,
    PackagedList,
    UpstreamModel,
    load_json,
)
from xippios.core.client import cache_key
from xippios.core.http import status_for
from xippios.core.testing import assert_projection, assert_time_between, mcp_call, sent_query

from xippios.usda.nass import api, enums, tasks
from xippios.usda.nass._client import BASE_URL, config
from xippios.usda.nass.errors import QueryTooLarge
from xippios.usda.nass.mcp import server
from xippios.usda.nass.models import (
    AcreageRecord,
    AreaStatistic,
    CountyEstimateRecord,
    CropProgressRecord,
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
        tasks.get_counts({"comodity_desc": "CORN", "year__GTE": 2012})
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
    route = replay_fixture("get_counts", "corn_va_since_2012")
    result = tasks.get_counts(
        {"state_alpha": enums.StateAlpha.VA, "sector_desc": enums.SectorDesc.CROPS}
    )
    assert result.meta.request["state_alpha"] == "VA"
    assert sent_query(route)["sector_desc"] == "CROPS"


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


@pytest.mark.parametrize(
    "model", [CropProgressRecord, CountyEstimateRecord, AcreageRecord, PriceReceivedRecord]
)
def test_projections_are_faithful(model: type[UpstreamModel]) -> None:
    record = QuickStatsRecord.model_validate({**EXAMPLE_RECORD, "CV (%)": "2.5"})
    overrides = {"cv_percent": Decimal("2.5")} if "cv_percent" in model.model_fields else {}
    projected = model.project(record, **overrides)
    assert_projection(projected, record, **overrides)
    assert set(model.model_fields) <= set(QuickStatsRecord.model_fields)
    assert projected.model_dump(mode="json")["value_number"] == 1234.5


def test_slices_skip_the_count_and_leave_published_at_empty(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    counted = replay_fixture("get_counts", "corn_progress_planted_ia_2024")
    replay_fixture("api_get", "corn_progress_planted_ia_2024")
    result = tasks.get_crop_progress(
        "CORN", 2024, state=enums.StateAlpha.IA, stage=enums.ProgressStage.PCT_PLANTED
    )
    assert not counted.called
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
