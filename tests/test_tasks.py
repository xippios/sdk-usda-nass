"""Structural checks every task must satisfy. Per-task tests with recorded fixtures go below."""

import inspect
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pytest
import respx
from xippios.core import InvalidRequestError, NotFoundError
from xippios.core.http import status_for

from xippios.usda.nass import __version__, api, enums, tasks
from xippios.usda.nass.errors import QueryTooLarge
from xippios.usda.nass.models import CountyEstimateRecord, CropProgressRecord, QuickStatsRecord
from xippios.usda.nass.params import (
    DERIVED_LISTS,
    PACKAGED_PARAMS,
    columns,
    derived_values,
    packaged_values,
)

TASKS = [getattr(tasks, name) for name in tasks.__all__]


def test_package_has_a_version() -> None:
    assert __version__


@pytest.mark.parametrize("task", TASKS, ids=tasks.__all__)
def test_task_is_a_sync_facade_with_an_agent_docstring(task: object) -> None:
    assert callable(task)
    assert hasattr(task, "async_fn"), "write the async function and derive the sync one with sync()"
    doc = inspect.getdoc(task) or ""
    assert doc, "task functions need a docstring: agents read it"
    assert doc.splitlines()[0].endswith("."), "the first line is one sentence"
    if inspect.signature(task).parameters:
        assert "Args:" in doc, "explain every parameter under Args: with valid-value examples"


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
    sent = route.calls.last.request.url.params
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


def test_enums_match_the_packaged_lists() -> None:
    for param in PACKAGED_PARAMS:
        cls = getattr(enums, "".join(part.capitalize() for part in param.split("_")))
        packaged = packaged_values(param)
        assert packaged is not None
        assert [member.value for member in cls] == packaged.values, param
    assert enums.StateAlpha.VA.value == "VA"
    assert enums.SectorDesc.ANIMALS_AND_PRODUCTS.value == "ANIMALS & PRODUCTS"
    assert enums.AggLevelDesc.REGION_MULTI_STATE.value == "REGION : MULTI-STATE"


def test_enum_members_are_accepted_as_filter_values(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("get_counts", "corn_va_since_2012")
    result = tasks.get_counts(
        {"state_alpha": enums.StateAlpha.VA, "sector_desc": enums.SectorDesc.CROPS}
    )
    assert result.meta.request["state_alpha"] == "VA"
    assert route.calls.last.request.url.params["sector_desc"] == "CROPS"


SMALL_FILTERS: dict[str, str | int] = {
    "commodity_desc": "CORN",
    "year": 2012,
    "state_alpha": "VA",
    "statisticcat_desc": "AREA PLANTED",
    "agg_level_desc": "STATE",
}


def test_get_data_parses_every_column(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_va_since_2012")
    fetched = replay_fixture("api_GET", "corn_va_2012_area_planted")
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
    assert fetched.calls.last.request.url.params["format"] == "JSON"


def test_get_data_refuses_before_fetching_when_over_the_limit(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_counts", "unknown_column")
    fetched = replay_fixture("api_GET", "exceeds_limit")
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
    fetched = replay_fixture("api_GET", "no_match")
    result = tasks.get_data({"commodity_desc": "CORN", "year": 1800, "state_alpha": "VA"})
    assert result.data == []
    assert not fetched.called


@pytest.mark.anyio
async def test_api_get_maps_upstream_errors(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_GET", "exceeds_limit")
    with pytest.raises(QueryTooLarge) as info:
        await api.api_GET({"commodity_desc": "CORN"})
    assert info.value.count is None


@pytest.mark.anyio
async def test_api_get_maps_no_match_to_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("api_GET", "no_match")
    with pytest.raises(NotFoundError, match="invalid query"):
        await api.api_GET({"commodity_desc": "CORN", "year": 1800})


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
    """Layer 1 is unaffected by packaging: the wrapper always calls upstream."""
    route = replay_fixture("get_param_values", "sector_desc")
    values = await api.get_param_values("sector_desc")
    assert values == ["ANIMALS & PRODUCTS", "CROPS", "DEMOGRAPHICS", "ECONOMICS", "ENVIRONMENTAL"]
    assert route.calls.last.request.url.params["param"] == "sector_desc"


def test_list_param_values_goes_live_for_an_unpackaged_parameter(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    route = replay_fixture("get_param_values", "statisticcat_desc")
    result = tasks.list_param_values("statisticcat_desc")
    assert route.called
    assert result.meta.endpoint == "get_param_values"
    assert result.meta.request == {"param": "statisticcat_desc"}
    assert "AREA PLANTED" in result.data
    assert len(result.data) > 200


def test_list_param_values_unknown_parameter_is_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_param_values", "unknown_param")
    with pytest.raises(NotFoundError, match="not_a_column"):
        tasks.list_param_values("not_a_column")


def test_packaged_parameters_are_answered_without_a_network_call(
    respx_mock: respx.MockRouter,
) -> None:
    """respx is active with no routes mounted, so any upstream call would fail loudly."""
    for param in PACKAGED_PARAMS:
        result = tasks.list_param_values(param)
        assert result.data, param
        assert result.meta.endpoint == "reference"
        assert result.meta.vintage == "2026-10-22"
        assert result.meta.request == {"param": param}
    assert not respx_mock.calls
    assert "CROPS" in tasks.list_param_values("sector_desc").data
    assert "VA" in tasks.list_param_values("state_alpha").data


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
    record_fields = {(field.alias or name) for name, field in QuickStatsRecord.model_fields.items()}
    assert record_fields <= names
    assert {column.dimension for column in columns()} == {
        'The "WHAT" (or Commodity) dimension',
        'The "WHERE" (or Location) dimension',
        'The "WHEN" (or Time) dimension',
        "The Data Value",
    }


def test_crop_progress_state_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_progress_planted_ia_2024")
    fetched = replay_fixture("api_GET", "corn_progress_planted_ia_2024")
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
    assert fetched.calls.last.request.url.params["statisticcat_desc"] == "PROGRESS"
    assert len(result.data) == 11
    weeks = [row.week_ending or date.min for row in result.data]
    assert weeks == sorted(weeks)
    first, last = result.data[0], result.data[-1]
    assert first.week_ending == date(2024, 3, 31)
    assert first.value == Decimal("0")
    assert last.week_ending == date(2024, 6, 9)
    assert last.value == Decimal("98")  # NASS stops the series short of 100
    assert {row.unit_desc for row in result.data} == {"PCT PLANTED"}
    assert {row.state_alpha for row in result.data} == {"IA"}
    assert last.short_desc == "CORN - PROGRESS, MEASURED IN PCT PLANTED"
    assert isinstance(last.load_time, datetime)


def test_crop_progress_national_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_progress_planted_us_2024")
    replay_fixture("api_GET", "corn_progress_planted_us_2024")
    result = tasks.get_crop_progress("CORN", 2024, stage=enums.ProgressStage.PCT_PLANTED)
    assert result.meta.request["agg_level_desc"] == "NATIONAL"
    assert "state_alpha" not in result.meta.request
    assert {row.state_alpha for row in result.data} == {"US"}
    assert {row.state_name for row in result.data} == {"US TOTAL"}


def test_crop_condition_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_condition_good_ia_2024")
    replay_fixture("api_GET", "corn_condition_good_ia_2024")
    result = tasks.get_crop_condition(
        "CORN", 2024, state=enums.StateAlpha.IA, category=enums.ConditionCategory.PCT_GOOD
    )
    assert result.meta.request["statisticcat_desc"] == "CONDITION"
    assert result.meta.request["unit_desc"] == "PCT GOOD"
    assert len(result.data) == 21
    assert {row.statisticcat_desc for row in result.data} == {"CONDITION"}
    assert all(row.value is not None and 0 <= row.value <= 100 for row in result.data)


def test_projection_keeps_upstream_names_and_values() -> None:
    record = QuickStatsRecord.model_validate(EXAMPLE_RECORD)
    projected = CropProgressRecord.from_record(record)
    assert set(CropProgressRecord.model_fields) <= set(QuickStatsRecord.model_fields)
    for name in CropProgressRecord.model_fields:
        if name == "value":
            assert projected.value == record.value_number
        else:
            assert getattr(projected, name) == getattr(record, name), name


def test_derived_enums_match_their_lists_and_provenance() -> None:
    stages = derived_values("progress_stages")
    categories = derived_values("condition_categories")
    assert [m.value for m in enums.ProgressStage] == stages.values
    assert [m.value for m in enums.ConditionCategory] == categories.values
    assert stages.derived_from is not None
    assert stages.derived_from["statisticcat_desc"] == "PROGRESS"
    assert stages.derived_from["agg_level_desc"] == "NATIONAL"
    assert set(DERIVED_LISTS) == {"progress_stages", "condition_categories"}
    assert enums.ProgressStage.PCT_PLANTED.value == "PCT PLANTED"
    assert [m.value for m in enums.ConditionCategory] == [
        "PCT EXCELLENT", "PCT FAIR", "PCT GOOD", "PCT POOR", "PCT VERY POOR",
    ]  # fmt: skip


def test_county_yield_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_yield_de_2023_county")
    fetched = replay_fixture("api_GET", "corn_yield_de_2023_county")
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
    assert fetched.calls.last.request.url.params["agg_level_desc"] == "COUNTY"
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
    assert kent_all.value == Decimal("194.5")
    assert kent_all.cv_percent == Decimal("2.5")
    assert kent_all.county_code == "001"
    assert kent_all.asd_desc == "CENTRAL"
    assert all(
        row.cv_percent is None
        for row in result.data
        if row.prodn_practice_desc != "ALL PRODUCTION PRACTICES"
    )


def test_county_production_series(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    replay_fixture("get_counts", "corn_production_de_2023_county")
    replay_fixture("api_GET", "corn_production_de_2023_county")
    result = tasks.get_county_production("CORN", 2023, state=enums.StateAlpha.DE)
    assert result.meta.request["statisticcat_desc"] == "PRODUCTION"
    assert {row.unit_desc for row in result.data} == {"BU"}
    sussex_all = next(
        row
        for row in result.data
        if row.county_name == "SUSSEX" and row.prodn_practice_desc == "ALL PRODUCTION PRACTICES"
    )
    assert sussex_all.value == Decimal("18397000")
    assert sussex_all.cv_percent == Decimal("8.7")


def test_county_series_without_state_covers_the_country(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    replay_fixture("get_counts", "corn_yield_de_2023_county")
    replay_fixture("api_GET", "corn_yield_de_2023_county")
    result = tasks.get_county_yield("CORN", 2023)
    assert "state_alpha" not in result.meta.request
    assert result.meta.request["agg_level_desc"] == "COUNTY"


def test_county_projection_keeps_upstream_names_and_values() -> None:
    record = QuickStatsRecord.model_validate({**EXAMPLE_RECORD, "CV (%)": "2.5"})
    projected = CountyEstimateRecord.from_record(record)
    assert set(CountyEstimateRecord.model_fields) <= set(QuickStatsRecord.model_fields)
    for name in CountyEstimateRecord.model_fields:
        if name == "value":
            assert projected.value == record.value_number
        elif name == "cv_percent":
            assert projected.cv_percent == Decimal("2.5")
        else:
            assert getattr(projected, name) == getattr(record, name), name
    assert (
        CountyEstimateRecord.from_record(QuickStatsRecord.model_validate(EXAMPLE_RECORD)).cv_percent
        is None
    )
