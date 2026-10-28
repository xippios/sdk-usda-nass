"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import respx
from xippios.core import (
    InvalidRequestError,
    NotFoundError,
    PackagedList,
    UnknownCode,
    UpstreamModel,
    load_json,
)
from xippios.core.http import status_for
from xippios.core.testing import assert_projection, mcp_call, mcp_call_text, sent_query

from xippios.usda.nass import api, enums, tasks
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
    """A packaged file's ``fetched``, read from its text: a bare date is 00:00 UTC that day."""
    when = datetime.fromisoformat(load_json(PACKAGE, f"{name}.json")["fetched"])
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def test_enums_match_the_packaged_lists() -> None:
    for param in PACKAGED_PARAMS:
        cls = getattr(enums, "".join(part.capitalize() for part in param.split("_")))
        packaged = PackagedList.load(PACKAGE, param)
        values = [record[param] for record in packaged.records]
        assert [member.value for member in cls] == values, param
    assert enums.StateAlpha.VA.value == "VA"
    assert enums.SectorDesc.ANIMALS_AND_PRODUCTS.value == "ANIMALS & PRODUCTS"
    assert enums.AggLevelDesc.REGION_MULTI_STATE.value == "REGION : MULTI-STATE"


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
    """Layer 1 is unaffected by packaging: the wrapper always calls upstream."""
    route = replay_fixture("get_param_values", "sector_desc")
    values = await api.get_param_values("sector_desc")
    assert values == ["ANIMALS & PRODUCTS", "CROPS", "DEMOGRAPHICS", "ECONOMICS", "ENVIRONMENTAL"]
    assert sent_query(route)["param"] == "sector_desc"


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


@pytest.mark.anyio
async def test_list_param_values_over_mcp_is_whole_past_the_default_cap(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """278 values, past the default cap of 200 rows: the tool's own cap, ``tasks.MCP_CAPS``
    (ADR-0016), lets every one through, so no note is added."""
    replay_fixture("get_param_values", "statisticcat_desc")
    payload = await mcp_call(server, "usda_nass_list_param_values", {"param": "statisticcat_desc"})
    assert len(payload["data"]) == 278
    assert "note" not in payload
    assert tasks.MCP_CAPS["list_param_values"].max_rows == 1000


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
        packaged = PackagedList.load(PACKAGE, param)
        result = tasks.list_param_values(param)
        assert result.data == [record[param] for record in packaged.records], param
        assert result.meta.endpoint == "get_param_values"
        assert result.meta.retrieved_at == fetched_as_written(param)
        assert result.meta.vintage is None
        assert result.meta.published_at is None
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
