"""Structural checks every task must satisfy. Per-task tests with recorded fixtures go below."""

import inspect
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

import pytest
import respx
from xippios.core import NotFoundError

from xippios.usda.nass import __version__, api, tasks
from xippios.usda.nass.errors import QueryTooLarge
from xippios.usda.nass.models import QuickStatsRecord
from xippios.usda.nass.params import PACKAGED_PARAMS, columns

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


def test_unknown_columns_are_ignored_upstream(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """Characterisation: Quick Stats drops unknown columns and counts the whole database."""
    replay_fixture("get_counts", "unknown_column")
    assert tasks.get_counts({"not_a_column": "x"}).data == 57873464


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
        tasks.get_data({"not_a_column": "x"})
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
