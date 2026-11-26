"""Replay tests on recorded fixtures, at least one per task (conventions §10).

``/add-endpoint`` and ``/record-fixture`` add them.
"""

import argparse
import json
import re
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from xippios.core import (
    Answer,
    InvalidRequestError,
    MemoryCache,
    NotFoundError,
    PackagedCodes,
    PackagedList,
    UnknownCode,
    ValidationError,
    load_json,
)
from xippios.core.client import cache_key
from xippios.core.http import status_for
from xippios.core.mcp import build_parser, main
from xippios.core.redaction import scrub_url
from xippios.core.testing import (
    REDACTED,
    ReplayFixture,
    assert_time_between,
    load_fixture,
    mcp_call,
    mcp_call_text,
    recorded_query,
    sent_query,
    sent_urls,
)

from xippios.usda.nass import api, tasks
from xippios.usda.nass._client import BASE_URL, config
from xippios.usda.nass.errors import MCP_SPLIT_YEARS, SPLIT_CEILING, QueryTooLarge
from xippios.usda.nass.mcp import run, server
from xippios.usda.nass.models import ApiGetResponse, GetCountsResponse, QuickStatsRecord
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS, columns

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
    assert (await api.get_counts({"not_a_column": "x"})).payload.count == 57873464


def test_unknown_filter_keys_are_rejected_before_any_call(respx_mock: respx.MockRouter) -> None:
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_counts({"comodity_desc": "CORN", "year__GTE": 2012, "state_alpha": "XX"})
    assert not isinstance(info.value, UnknownCode)  # the keys are checked before the values
    message = str(info.value)
    assert "'comodity_desc' is not a Quick Stats column" in message
    assert "did you mean commodity_desc" in message
    assert "'year__GTE': unknown operator 'GTE'" in message
    assert "__GE" in message
    # The refusal comes before any request and says so (conventions §5, sdk-core ADR-0045).
    assert message.endswith(
        ". Nothing was sent. Columns are defined in docs/upstream/param_define.md."
    )
    assert not respx_mock.calls


def test_every_documented_operator_passes_validation(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    # One recorded count answers each operator's query: the test asserts that the key
    # is sent and the count read, as upstream counts alike (conventions §10, kind 3).
    replay_fixture("get_counts", "corn_va_since_2012")
    for key in ["year__LE", "year__LT", "year__GT", "year__GE", "commodity_desc__LIKE",
                "commodity_desc__NOT_LIKE", "state_alpha__NE", "Value"]:  # fmt: skip
        assert tasks.get_counts({key: "x"}).data == 22345


def test_query_too_large_is_an_invalid_request_for_http_too() -> None:
    """The package's ``QueryTooLarge`` is core's, kept as a subclass for ``year``, so a
    caller catches either (https://github.com/xippios/sdk-core/issues/317)."""
    from xippios.core import QueryTooLarge as CoreQueryTooLarge

    assert issubclass(QueryTooLarge, CoreQueryTooLarge)
    assert issubclass(QueryTooLarge, InvalidRequestError)
    assert status_for(QueryTooLarge(70_000)) == 422
    refused = QueryTooLarge(70_000, year=2021)
    assert (refused.count, refused.limit, refused.year, refused.request) == (
        70_000, 50_000, 2021, None,
    )  # fmt: skip


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


def test_the_package_ships_no_enum_of_its_lists() -> None:
    """A filter takes upstream's text, which ``validate_filters`` checks against the
    packaged list without regard to case, so no enum of a list ships beside it: the
    eleven generated in ``xippios.usda.nass.enums`` left in 0.4.0, since nothing in the
    package read them once the slices left
    (https://github.com/xippios/sdk-usda-nass/issues/89)."""
    import importlib.util

    assert importlib.util.find_spec("xippios.usda.nass.enums") is None


@pytest.mark.anyio
async def test_upstream_counts_no_records_for_an_unknown_packaged_value(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The refusal's premise, recorded at layer 1 on 2026-10-28: Quick Stats answers a
    ``state_alpha`` it does not know with HTTP 200 and a count of 0, the answer a query
    without data gets."""
    route = replay_fixture("get_counts", "unknown_state_alpha")
    assert (await api.get_counts({"state_alpha": "XX"})).payload.count == 0
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
        " Nothing was sent."
    )
    assert (
        "list_param_values('state_alpha') lists the known values (over MCP, the tool "
        "usda_nass_list_param_values)."
    ) in str(info.value)
    # Core's closing sentence names no maintainers' command, which an agent cannot run
    # (https://github.com/xippios/sdk-core/issues/111).
    assert str(info.value).endswith("If upstream added it since, the packaged list is out of date.")
    assert "/refresh-reference-data" not in str(info.value)
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
    as upstream writes them, whatever the case given, each once, as core words it from
    ``closest`` (https://github.com/xippios/sdk-core/issues/111)."""
    with pytest.raises(UnknownCode) as info:
        tasks.get_data({"commodity_desc": "CORN", param: value})
    assert info.value.closest[0][0] == known
    named = ", ".join(str(code) for code, _ in info.value.closest)
    assert f"Did you mean {named}?" in str(info.value)
    assert "list_param_values" not in str(info.value)
    assert f"packaged {param} list (fetched {fetched_as_written(param):%Y-%m-%d})" in str(
        info.value
    )
    assert not respx_mock.calls


@pytest.mark.parametrize("task", [tasks.get_counts, tasks.get_data])
def test_an_integer_for_a_packaged_list_of_text_is_refused_before_any_call(
    respx_mock: respx.MockRouter, task: Callable[..., object]
) -> None:
    """Every packaged list holds text, so core's check refuses an integer for one with
    ``InvalidRequestError``, naming the text to pass, where the package's own check
    refused it as an unknown value (https://github.com/xippios/sdk-core/issues/313)."""
    with pytest.raises(InvalidRequestError) as info:
        task({"commodity_desc": "CORN", "state_alpha": 51})
    assert not isinstance(info.value, UnknownCode)
    assert "state_alpha" in str(info.value)
    assert "Nothing was sent." in str(info.value)
    assert not respx_mock.calls


def test_each_packaged_list_is_declared_once_with_cores_check() -> None:
    """``params.codes`` declares a packaged list once per process, its values compared
    without regard to case, as Quick Stats compares them."""
    from xippios.usda.nass import params

    declared = params.codes("state_alpha")
    assert isinstance(declared, PackagedCodes)
    assert declared is params.codes("state_alpha")
    assert declared.check("state_alpha", "va") == "va"


def test_every_packaged_parameter_is_checked(respx_mock: respx.MockRouter) -> None:
    for param in PACKAGED_PARAMS:
        with pytest.raises(UnknownCode) as info:
            tasks.get_counts({param: "NOT A VALUE"})
        assert (info.value.param, info.value.fetched) == (param, fetched_as_written(param))
    assert not respx_mock.calls


def test_operator_keys_of_packaged_parameters_are_sent_as_given(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    # get_counts/no_match, a count of 0 recorded for year=1800, answers the operator
    # keys: the test asserts only what was sent and the empty count
    # (conventions §10, kind 3).
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
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
    replay_fixture("get_counts", "corn_va_since_2012")
    fetched = replay_fixture("api_get", "corn_va_2012_area_planted")
    result = tasks.get_data(SMALL_FILTERS)
    assert fetched.called
    assert result.meta.endpoint == "api_GET"
    assert result.meta.request == SMALL_FILTERS
    assert len(result.data) == 2
    # The count get_counts reported, as recorded for EXAMPLE_FILTERS: upstream's statement,
    # never len(data) (conventions §4, sdk-core ADR-0034).
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
    # get_counts/unknown_column, the whole database's count, answers the corn query,
    # over the limit alike (conventions §10, kind 3).
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
    # Core words the refusal and names the request upstream refused (conventions §5).
    assert info.value.request == "GET /api/api_GET/"
    assert str(info.value).startswith(
        "upstream refused GET /api/api_GET/ as too large; it serves at most 50,000 records "
        "per call."
    )


@pytest.mark.anyio
async def test_api_get_maps_no_match_to_not_found(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    # api_get/no_match answers the query without its state, an answer that upstream
    # gives alike to every query that matches nothing (conventions §10, kind 3).
    replay_fixture("api_get", "no_match")
    with pytest.raises(NotFoundError, match="invalid query"):
        await api.api_get({"commodity_desc": "CORN", "year": 1800})


@pytest.mark.anyio
async def test_the_wrappers_return_cores_answer_with_its_time(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``api_get`` and ``get_counts`` read through ``get_answer`` and return core's
    ``Answer``, the parsed payload with the time it arrived (sdk-core ADR-0037;
    https://github.com/xippios/sdk-core/issues/479)."""
    replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    before = datetime.now(UTC)
    counted = await api.get_counts(EXAMPLE_FILTERS)
    fetched = await api.api_get(SMALL_FILTERS)
    after = datetime.now(UTC)
    assert isinstance(counted, Answer)
    assert isinstance(counted.payload, GetCountsResponse)
    assert counted.payload.count == 22345
    assert isinstance(fetched, Answer)
    assert isinstance(fetched.payload, ApiGetResponse)
    assert len(fetched.payload.data) == 2
    for answer in (counted, fetched):
        assert_time_between(answer.retrieved_at, before, after)
    assert counted.retrieved_at <= fetched.retrieved_at


def test_a_task_is_retrieved_at_the_oldest_of_its_answers(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """``get_data`` reads a count and then the data, and its ``meta.retrieved_at`` is the
    count's time, the older, as conventions §4 has a task date what it assembles; a count
    alone is retrieved at its own answer's time."""
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
    replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    before = datetime.now(UTC)
    counted = tasks.get_counts(EXAMPLE_FILTERS)
    between = datetime.now(UTC)
    result = tasks.get_data(SMALL_FILTERS)
    after = datetime.now(UTC)
    assert_time_between(counted.meta.retrieved_at, before, between)
    assert_time_between(result.meta.retrieved_at, between, after)


def test_value_number_handles_suppression_codes() -> None:
    """``EXAMPLE_RECORD`` with a suppression code is an input of the test, not an answer
    from Quick Stats."""
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
    """Layer 1 is unaffected by packaging: the wrapper asks upstream, through the cache,
    and returns core's ``Answer`` of the values (https://github.com/xippios/sdk-core/issues/123)."""
    route = replay_fixture("get_param_values", "sector_desc")
    before = datetime.now(UTC)
    answer = await api.get_param_values("sector_desc")
    after = datetime.now(UTC)
    assert isinstance(answer, Answer)
    assert answer.payload == [
        "ANIMALS & PRODUCTS", "CROPS", "DEMOGRAPHICS", "ECONOMICS", "ENVIRONMENTAL",
    ]  # fmt: skip
    assert sent_query(route)["param"] == "sector_desc"
    assert_time_between(answer.retrieved_at, before, after)
    assert not hasattr(api, "ParamValues"), "core's Answer replaces the package's own pair"


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
    answer, not a clock reading of its own (sdk-core ADR-0037, decision 5; conventions §4).

    The plugin empties every ``MemoryCache`` around each test (sdk-core ADR-0035), so the
    hit is proved inside this one. The first call, a miss, carries the time its answer
    arrived, the one reading of the clock that the cache stores with it, so the miss and
    the hit report one time (https://github.com/xippios/sdk-core/issues/79).
    """
    assert isinstance(config.cache, MemoryCache)
    # One prefix, the list lookups', kept for a day; no other path is kept (sdk-core ADR-0040).
    assert config.cache.lifetimes == {"/api/get_param_values/": 24 * 60 * 60}
    route = replay_fixture("get_param_values", "commodity_desc")
    before = datetime.now(UTC)
    first = tasks.list_param_values("commodity_desc")
    after = datetime.now(UTC)
    second = tasks.list_param_values("commodity_desc")
    assert route.call_count == 1
    assert second.data == first.data
    assert len(second.data) > 200
    stored = stored_at("commodity_desc")
    assert second.meta.retrieved_at == stored == first.meta.retrieved_at
    assert_time_between(stored, before, after)
    assert second.meta == first.meta
    assert second.meta.published_at is None


def test_a_live_list_that_does_not_parse_is_not_cached(
    respx_mock: respx.MockRouter, fixtures_dir: Path
) -> None:
    """NOT RECORDED: the recorded ``commodity_desc`` answer, changed in memory so that
    the parameter's list is a text, a form upstream was not seen to send (conventions
    §10, kind 4). The lookup raises ``ValidationError`` and the cache keeps nothing, so the
    next lookup asks upstream again rather than answering the failure for a day: core's
    cache stores an answer only once ``get_answer`` parsed it
    (https://github.com/xippios/sdk-core/issues/122)."""
    recorded = load_fixture(fixtures_dir / "get_param_values" / "commodity_desc.json")
    body = json.loads(recorded.response.body)
    body["commodity_desc"] = "CORN"
    route = respx_mock.get(f"{BASE_URL}/get_param_values/").mock(
        return_value=httpx.Response(recorded.response.status, json=body)
    )
    for _ in range(2):
        with pytest.raises(ValidationError, match="get_param_values"):
            tasks.list_param_values("commodity_desc")
    assert route.call_count == 2
    assert isinstance(config.cache, MemoryCache)
    assert len(config.cache) == 0


def test_counts_are_never_cached(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    route = replay_fixture("get_counts", "corn_va_since_2012")
    first = tasks.get_counts(EXAMPLE_FILTERS)
    second = tasks.get_counts(EXAMPLE_FILTERS)
    assert route.call_count == 2
    assert (first.data, second.data) == (22345, 22345)
    assert isinstance(config.cache, MemoryCache)
    assert len(config.cache) == 0


def test_data_is_never_cached(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
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
    with no upstream call: the tool's own cap, ``tasks.MCP_CAPS`` (sdk-core ADR-0038), lets
    every one through, so no note is added."""
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


@pytest.mark.anyio
async def test_list_param_values_over_mcp_continues_by_offset_without_a_request(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    """The list tool's cap is paged: it takes core's ``offset``, the values already shown,
    and its task runs again, answered from the package or the client's cache, so a
    continuation sends upstream nothing (https://github.com/xippios/sdk-usda-nass/issues/55;
    sdk-core ADR-0047). ``get_data`` takes no ``offset``, since its continuation would send
    its count and its data again."""
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools["usda_nass_list_param_values"].input_schema["properties"]) == {
        "param",
        "offset",
    }
    assert "offset" not in tools["usda_nass_get_data"].input_schema["properties"]
    assert tasks.MCP_CAPS["list_param_values"].paged
    route = replay_fixture("get_param_values", "commodity_desc")
    whole = await mcp_call(server, "usda_nass_list_param_values", {"param": "commodity_desc"})
    rest = await mcp_call(
        server, "usda_nass_list_param_values", {"param": "commodity_desc", "offset": 400}
    )
    assert rest["data"] == whole["data"][400:]
    assert route.call_count == 1, "the continuation is answered from the cache"
    domains = [
        record["domain_desc"] for record in PackagedList.load(PACKAGE, "domain_desc").records
    ]
    packaged = await mcp_call(
        server, "usda_nass_list_param_values", {"param": "domain_desc", "offset": 600}
    )
    assert packaged["data"] == domains[600:]
    assert route.call_count == 1


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


def test_the_package_ships_the_nine_lists_and_the_column_table() -> None:
    """``reference/`` holds a file for each of the nine parameters that upstream lists by
    ``get_param_values``, ``columns.csv`` and its README, and no list of the package's own
    (https://github.com/xippios/sdk-core/issues/474): the progress stages and condition
    categories, which it derived from one year of data, left in 0.4.0, and the packaged
    ``unit_desc`` holds their values, among them the four named here."""
    from importlib.resources import files

    from xippios.usda.nass import params

    shipped = sorted(entry.name for entry in files(PACKAGE).joinpath("reference").iterdir())
    lists = [f"{param}.json" for param in PACKAGED_PARAMS]
    assert shipped == sorted(["README.md", "columns.csv", *lists])
    assert not hasattr(params, "DERIVED_LISTS")
    units = set(tasks.list_param_values("unit_desc").data)
    assert {"PCT PLANTED", "PCT HARVESTED", "PCT EXCELLENT", "PCT VERY POOR"} <= units


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


def test_get_data_keeps_the_count_and_leaves_published_at_empty(
    replay_fixture: Callable[[str, str], respx.Route],
) -> None:
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
    counted = replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    result = tasks.get_data(SMALL_FILTERS)
    assert counted.called
    assert result.meta.total == 22345
    assert result.meta.published_at is None


@pytest.mark.anyio
async def test_mcp_tool_call_end_to_end(replay_fixture: Callable[[str, str], respx.Route]) -> None:
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
    replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    payload = await mcp_call(server, "usda_nass_get_data", {"filters": SMALL_FILTERS})
    assert len(payload["data"]) == 2
    first = payload["data"][0]
    assert (first["value"], first["value_number"], first["week_ending"]) == (
        "510,000",
        510000,
        None,
    )
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
    # get_counts/corn_va_since_2012, recorded for EXAMPLE_FILTERS, answers the count of
    # SMALL_FILTERS too, a count within the limit that upstream gives alike for the narrower
    # query (conventions §10, kind 3).
    replay_fixture("get_counts", "corn_va_since_2012")
    replay_fixture("api_get", "corn_va_2012_area_planted")
    response = client.post("/usda-nass/get_data", json={"filters": SMALL_FILTERS})
    assert response.status_code == 200, response.text
    assert response.json()["data"][0]["value_number"] == 510000
    # A decimal without fractional digits is a JSON integer (https://github.com/xippios/sdk-core/issues/478).
    assert '"value_number":510000' in response.text
    assert '"value_number":510000.0' not in response.text
    listed = client.get("/usda-nass/list_param_values", params={"param": "sector_desc"})
    assert listed.status_code == 200, listed.text
    assert "CROPS" in listed.json()["data"]
    rejected = client.post("/usda-nass/get_counts", json={"filters": {"comodity_desc": "CORN"}})
    assert rejected.status_code == 422
    assert rejected.json()["title"] == "InvalidRequestError"
    unknown = client.post("/usda-nass/get_counts", json={"filters": {"state_alpha": "XX"}})
    assert unknown.status_code == 422
    assert unknown.json()["title"] == "UnknownCode"
    assert "packaged state_alpha list" in unknown.json()["detail"]


def test_the_package_contract_for_a_host() -> None:
    """``mcp.build()`` carries what ``tasks.py`` declares for the server: the caps, the
    instructions and the ``--split-years`` hooks, which core's tool set reads from the
    module (conventions §8; sdk-core ADR-0063, decision 7). Core's family check holds the
    rest of the contract, the tasks served and ``ENV_VARS`` among it (decision 8)."""
    from xippios.usda.nass import mcp as entry

    tools = entry.build()
    assert dict(tools.caps) == dict(tasks.MCP_CAPS)
    assert tools.instructions == tasks.MCP_INSTRUCTIONS
    assert not hasattr(entry, "INSTRUCTIONS")
    assert tools.read_only
    assert not tools.loopback_only
    assert tools.option_defaults().split_years == MCP_SPLIT_YEARS


@pytest.mark.anyio
async def test_the_package_serves_its_three_tasks_and_no_slice_of_them() -> None:
    """The package wraps the three operations of Quick Stats and adds no task that fixes
    filters for the caller (https://github.com/xippios/sdk-core/issues/474): the slices
    over ``api_GET`` left in 0.4.0 with their projections and value sets, and the query of
    each is one ``get_data`` call with the same filters. The package, its MCP server and
    its router serve the same three tasks, and ``models`` holds the records of the three
    operations alone."""
    import xippios.usda.nass as package
    from xippios.usda.nass import models
    from xippios.usda.nass.http import router

    assert tasks.__all__ == ["get_counts", "get_data", "list_param_values"]
    assert package.__all__ == ["__version__", *tasks.__all__]
    defined = {name.removesuffix("_async") for name in dir(tasks) if name.endswith("_async")}
    assert defined == set(tasks.__all__)
    tools = {tool.name for tool in await server.list_tools()}
    assert tools == {f"usda_nass_{name}" for name in tasks.__all__}
    assert {getattr(route, "path", None) for route in router.routes} == {
        f"/usda-nass/{name}" for name in tasks.__all__
    }
    classes = {
        name
        for name, value in vars(models).items()
        if isinstance(value, type) and value.__module__ == models.__name__
    }
    assert classes == {"ApiGetResponse", "GetCountsResponse", "QuickStatsRecord", "_Published"}
    assert models.__all__ == ["ApiGetResponse", "Filters", "GetCountsResponse", "QuickStatsRecord"]


@pytest.mark.usefixtures("restore_split_ceiling")
def test_a_host_applies_the_options_as_the_entry_point_does() -> None:
    """A host applies the defaults of the tool set's hooks, under core's signature, the
    parsed options alone, so its server splits into 11 years at most, as
    ``xippios-usda-nass-mcp`` does (sdk-core ADR-0063, decision 7)."""
    from xippios.usda.nass import mcp as entry

    tools = entry.build()
    assert tools.apply_options is not None
    tools.apply_options(tools.option_defaults())
    assert tasks.SPLIT.value == MCP_SPLIT_YEARS


# --- get_data(split_by_year=True) (https://github.com/xippios/sdk-usda-nass/pull/27) ---

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
    "HTTP, 11 by default on the MCP server (--split-years)."
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
    sdk-core ADR-0040, decision 5). The slices answer the Iowa queries of their year, as
    upstream answers alike within one operation (conventions §10, kind 3).
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
    the years from 2025 to the current one, whose counts are not recorded: recorded
    counts served at other filters of their operation (conventions §10, kind 3)."""
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
    assert str(info.value) == (
        "query would return 85,535 records; upstream serves at most 50,000 per call. "
        f"{THROUGH_THE_LIMIT}"
    )
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
    assert str(QueryTooLarge(None)).startswith("upstream refused the query as too large")
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
    ``get_counts/unknown_column``, stands in for a 2021 over the limit on its own, a
    recorded count served at another year of its operation (conventions §10, kind 3)."""
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
    assert str(info.value) == (
        "query would return 57,873,464 records; upstream serves at most 50,000 per call. "
        "Year 2021 alone is over the limit, so split_by_year cannot fetch it. Narrow the "
        "filters, for example by state_alpha, agg_level_desc or statisticcat_desc. The series "
        "stopped at 2021 after 1 period answered, 2020, and returns nothing."
    )  # core's fetch_periods names the years answered before the refusal
    assert (count_2020.call_count, count_2021.call_count) == (1, 1)
    # No count of the range, and nothing fetched before every year is counted, though 2020 fits.
    assert sent_in_order(respx_mock) == [("/api/get_counts/", "2020"), ("/api/get_counts/", "2021")]
    assert not fetched.called


def test_split_of_one_year_over_the_limit_refuses_after_the_first_count(
    replay_fixture: ReplayFixture,
) -> None:
    # get_counts/unknown_column, the whole database's count, answers the count of
    # 2021, over the limit alike (conventions §10, kind 3).
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
    """The ``year`` form keeps no future-year refusal: with the flag, next year is counted
    as without it (https://github.com/xippios/sdk-usda-nass/pull/27). A count of 0
    (``get_counts/no_match``, recorded for ``year=1800``) answers it at ``url=``, an empty
    answer at another year (conventions §10, kind 3): no fetch."""
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
    assert str(info.value).endswith(
        f"given: {', '.join(sorted(years)) or 'none'}. Nothing was sent."
    )
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
    with pytest.raises(InvalidRequestError, match=text) as info:
        tasks.get_data({"commodity_desc": "CORN", **years}, split_by_year=True)
    assert "Nothing was sent." in str(info.value)
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
    the range must end by the current UTC year (https://github.com/xippios/sdk-usda-nass/pull/27).
    Offsets from the current year, read at call time."""
    now = datetime.now(UTC).year
    years: dict[str, str | int] = {"year__GE": now + first}
    if last is not None:
        years["year__LE"] = now + last
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data({"commodity_desc": "CORN", **years}, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value) == (
        f"split_by_year: {named}={years[named]} is past the current UTC year, {now}. Nothing "
        f"was sent. The range must end by {now}."
    )
    assert status_for(info.value) == 422
    assert not respx_mock.calls


def test_split_bounds_year_ge_alone_at_the_current_utc_year(
    replay_fixture: ReplayFixture,
) -> None:
    """``get_counts/no_match`` (a count of 0, recorded for year=1800) answers every year, so
    the range runs to the current year without a fetch, and
    ``get_counts/corn_county_2020_2021`` stands in for the first count: recorded counts
    served at other years of their operation (conventions §10, kind 3)."""
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
    """The refusal of ``year__GE`` alone over the ceiling, which the package words after
    its count, so without core's ``Nothing was sent.``."""
    return (
        f"split_by_year covers at most 20 years per call; the years run from {first} to "
        f"{last}, {last - first + 1} years. Give a shorter range, e.g. year__GE={last - 19} "
        f"with year__LE={last}."
    )


def test_split_refuses_a_two_sided_range_of_more_than_twenty_years_before_any_call(
    respx_mock: respx.MockRouter,
) -> None:
    """The ceiling of conventions §4, the most years one call splits into: a two-sided
    range always splits, so 21 years, one too many, are refused before any call, in the
    words of core's ``Ceiling`` (https://github.com/xippios/sdk-core/issues/315)."""
    filters: dict[str, str | int] = {"commodity_desc": "CORN", "year__GE": 2000, "year__LE": 2020}
    with pytest.raises(InvalidRequestError) as info:
        tasks.get_data(filters, split_by_year=True)
    assert not isinstance(info.value, QueryTooLarge | UnknownCode)
    assert str(info.value) == (
        "split_by_year from 2000 to 2020 is 21 years; one call fetches at most 20 years. "
        "Nothing was sent. Give a shorter range, e.g. year__GE=2001 with year__LE=2020."
    )
    assert status_for(info.value) == 422
    assert not respx_mock.calls


def test_split_fetches_a_fitting_year_ge_range_whole_however_far_back(
    replay_fixture: ReplayFixture,
) -> None:
    """The ceiling binds a split, not the filters: ``year__GE`` 25 years back with a count
    within the limit is fetched whole. ``get_counts/corn_va_since_2012`` (22,345) stands
    in for the count, and ``api_get/corn_va_2012_area_planted`` replays a slice: recorded
    answers served at another year of their operation (conventions §10, kind 3)."""
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
    ``get_counts/corn_county_2020_2021`` (85,535) stands in for the count, a recorded
    count served at another year (conventions §10, kind 3)."""
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
    # get_counts/no_match, a count of 0 recorded for year=1800, answers every year, as
    # upstream answers a year without records (conventions §10, kind 3).
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
    count of 0) for every year, and nothing fetched: recorded counts served at other
    years (conventions §10, kind 3)."""
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
    # Each count, and each slice it fetches, is served for the filters given, a count
    # within the limit that upstream gives alike for them (conventions §10, kind 3).
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
    counted = (await api.get_counts(IA_FILTERS)).payload.count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).payload.count
    yearly = [
        (await api.get_counts({"state_alpha": "IA", "year": year})).payload.count
        for year in IA_COUNTS
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
    counted = (await api.get_counts(filters)).payload.count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).payload.count
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
    counted = (await api.get_counts(filters)).payload.count
    since = (await api.get_counts({"state_alpha": "IA", "year__GE": 2023})).payload.count
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


# --- the MCP server's --split-years (https://github.com/xippios/sdk-usda-nass/pull/27) ---

SPLIT_REFUSAL = (
    "the series ceiling, --split-years on the MCP server, must be a whole number of years "
    "from 1 to 20, got {!r}."
)
"""Core's ``Ceiling`` words the refusal of a ceiling outside 1 to 20 (sdk-core ADR-0054)."""


@pytest.fixture
def restore_split_ceiling() -> Iterator[None]:
    """The split ceiling is process-wide: a test that sets it leaves the Python API's,
    ``SPLIT_CEILING``, for the tests after it."""
    yield
    tasks.SPLIT.set(SPLIT_CEILING)


def test_the_split_ceilings_and_the_option(plain_terminal: None) -> None:
    """20 years for the Python API and the HTTP router, the ceiling in force while no MCP
    server applied its options; ``--split-years`` on core's parser, 11 by default, the most
    years whose split stays within the about two dozen requests that conventions §8 allow
    one tool call, 22 for a two-sided range and 23 for ``year__GE`` alone. The ceiling is
    core's ``Ceiling``, whose two hooks the module declares, where the package's own
    ``split_ceiling`` and ``set_split_ceiling`` stood
    (https://github.com/xippios/sdk-core/issues/315)."""
    from xippios.core import Ceiling

    assert (SPLIT_CEILING, MCP_SPLIT_YEARS) == (20, 11)
    assert isinstance(tasks.SPLIT, Ceiling)
    assert (tasks.SPLIT.most, tasks.SPLIT.mcp, tasks.SPLIT.option) == (20, 11, "--split-years")
    assert tasks.mcp_add_options == tasks.SPLIT.add_options
    assert tasks.mcp_apply_options == tasks.SPLIT.apply_options
    assert not hasattr(tasks, "split_ceiling")
    assert not hasattr(tasks, "set_split_ceiling")
    assert tasks.SPLIT.value == 20
    parser = build_parser(server.name, add_options=tasks.mcp_add_options)
    assert parser.parse_args([]).split_years == 11
    assert parser.parse_args(["--split-years", "3"]).split_years == 3
    assert parser.parse_args(["--split-years", "25"]).split_years == 25, (
        "the range is checked when the option is applied, then exit status 2"
    )
    assert (
        "--split-years YEARS most years one tool call fetches, 1 to 20 (default 11); "
        "usda_nass_get_data with split_by_year, up to two keyed calls a year, so 11 years "
        "take at most 23 calls"
    ) in " ".join(parser.format_help().split())


@pytest.mark.usefixtures("restore_split_ceiling")
@pytest.mark.parametrize("years", [1, 5, 20])
def test_the_split_ceiling_takes_1_to_20(years: int) -> None:
    tasks.SPLIT.set(years)
    assert tasks.SPLIT.value == years


@pytest.mark.usefixtures("restore_split_ceiling")
@pytest.mark.parametrize("years", [0, 21, -5, True, "5", 5.0, None])
def test_the_split_ceiling_refuses_anything_else(years: object) -> None:
    """Never above 20, never below 1, never a bool, a text or a float; the ceiling in
    force stays."""
    tasks.SPLIT.set(10)
    with pytest.raises(InvalidRequestError) as info:
        tasks.SPLIT.set(years)  # type: ignore[arg-type]
    assert str(info.value) == SPLIT_REFUSAL.format(years)
    assert tasks.SPLIT.value == 10


@pytest.mark.usefixtures("restore_split_ceiling")
def test_the_hooks_apply_the_option_through_cores_parser() -> None:
    """``--split-years 3`` applies 3, no option applies the default 11, and 25 is refused
    with the ceiling unchanged; ``mcp_apply_options`` takes the parsed options alone and
    returns nothing, core's signature (sdk-core ADR-0063, decision 7)."""
    parser = build_parser(server.name, add_options=tasks.mcp_add_options)
    for argv, expected in ((["--split-years", "3"], 3), ([], 11)):
        tasks.mcp_apply_options(parser.parse_args(argv))
        assert tasks.SPLIT.value == expected
    with pytest.raises(InvalidRequestError) as info:
        tasks.mcp_apply_options(parser.parse_args(["--split-years", "25"]))
    assert str(info.value) == SPLIT_REFUSAL.format(25)
    assert tasks.SPLIT.value == 11


@pytest.mark.usefixtures("restore_split_ceiling", "plain_terminal")
def test_the_entry_point_applies_split_years_or_exits_with_status_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mcp.run`` hands the tool set to core's ``main``, which builds the server it runs:
    without the option the MCP server starts with 11, ``--split-years 3`` sets 3 before
    the server runs, on stdio; 25 or 0 ends the process with exit status 2 and the refusal
    on stderr, before anything is served, the ceiling unchanged. ``MCPServer.run`` is
    replaced on the class, so nothing is served. The direct call to ``main`` lets mypy
    check the entry against its signature."""
    from mcp.server.mcpserver import MCPServer

    from xippios.usda.nass.mcp import build

    served: list[dict[str, object]] = []
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: served.append(kwargs))
    monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp"])
    run()
    assert tasks.SPLIT.value == 11
    monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp", "--split-years", "3"])
    run()
    assert tasks.SPLIT.value == 3
    assert served == [{"transport": "stdio"}, {"transport": "stdio"}]
    for value in ("25", "0"):
        monkeypatch.setattr(sys, "argv", ["xippios-usda-nass-mcp", "--split-years", value])
        with pytest.raises(SystemExit) as exit_info:
            run()
        assert exit_info.value.code == 2
        assert capsys.readouterr().err.endswith(f"error: {SPLIT_REFUSAL.format(int(value))}\n")
    with pytest.raises(SystemExit) as direct:
        main(build, argv=["--split-years", "21"])
    assert direct.value.code == 2
    assert capsys.readouterr().err.endswith(f"error: {SPLIT_REFUSAL.format(21)}\n")
    assert len(served) == 2, "nothing served after a refusal"
    assert tasks.SPLIT.value == 3


@pytest.mark.anyio
@pytest.mark.usefixtures("restore_split_ceiling")
async def test_the_mcp_server_refuses_a_split_beyond_its_ceiling_before_any_call(
    replay_fixture: ReplayFixture, respx_mock: respx.MockRouter
) -> None:
    """With the MCP server's default, 11, a two-sided range of twelve years is refused
    before any call (respx is active with no route mounted), in core's words naming the
    ceiling set for this process; the ceiling is process-wide, so a Python call meets it
    too. Eleven years pass: ``get_counts/no_match`` (a count of 0) answers each year, a
    recorded count served at other years (conventions §10, kind 3), and nothing is fetched."""
    tasks.mcp_apply_options(argparse.Namespace(split_years=MCP_SPLIT_YEARS))
    six: dict[str, str | int] = {"commodity_desc": "CORN", "year__GE": 2009, "year__LE": 2020}
    refusal = (
        "split_by_year from 2009 to 2020 is 12 years; one call fetches at most 11 years, the "
        "ceiling set for this process (the MCP server starts with 11 by default; "
        "--split-years raises it, up to 20). Nothing was sent. Give a shorter range, e.g. "
        "year__GE=2010 with year__LE=2020."
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
        {"filters": {**six, "year__GE": 2010}, "split_by_year": True},
    )
    assert (payload["data"], payload["meta"]["total"]) == ([], 0)
    sent = [httpx.URL(url).params.get("year") for url in sent_urls(yearly)]
    assert sent == [str(year) for year in range(2010, 2021)]
    assert not fetched.called


# --- the terminal that argparse's text is compared in ---

PLAIN = {"PYTHON_COLORS": "0", "COLUMNS": "100"}
"""No colors, which Python 3.14's argparse adds under ``FORCE_COLOR``, and a width that
keeps the usage line whole (https://github.com/xippios/sdk-usda-nass/issues/73)."""


@pytest.fixture
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin ``PLAIN`` for a test that compares argparse's text, whatever terminal the suite
    runs in; argparse reads both when it prints."""
    for name, value in PLAIN.items():
        monkeypatch.setenv(name, value)


# --- get_data of one year: a count of 0 may be a year not yet published ---


UNPUBLISHED_COUNT = (
    "For one ``year``, a zero may be a year without records or one not yet published: "
    "Quick Stats names no release."
)
"""What ``get_data`` says of a count of 0 for one ``year``, which returns an empty result
without the flag and in ``split_by_year``'s ``year`` form, as a year that Quick Stats has
not published counts (https://github.com/xippios/sdk-usda-nass/pull/27)."""


@pytest.mark.anyio
async def test_get_data_says_a_zero_for_one_year_may_be_a_year_not_yet_published() -> None:
    """``get_data`` fetches one period when its filters name one ``year``: its lead, the
    paragraph before ``Args``, and its MCP tool's description name both readings of a
    count of 0 (conventions §4; https://github.com/xippios/sdk-usda-nass/issues/42)."""
    import inspect

    doc = inspect.getdoc(tasks.get_data) or ""
    lead = doc.partition("\n\nArgs:")[0]
    assert UNPUBLISHED_COUNT in " ".join(lead.split())
    tools = {tool.name: tool for tool in await server.list_tools()}
    description = tools["usda_nass_get_data"].description or ""
    assert UNPUBLISHED_COUNT in " ".join(description.split())
