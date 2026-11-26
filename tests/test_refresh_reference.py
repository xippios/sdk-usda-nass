"""``scripts/refresh_reference.py`` offline: its column table parser and its run.

``columns.csv`` is rebuilt from the HTML column table the snapshot keeps in
``docs/upstream/param_define.md`` (conventions §3). A run sends each request once, waits
up to 300 seconds for its answer and counts it, fetches every list before it writes one,
and with ``--only`` fetches the lists it names alone. These tests read the committed
snapshot and files, write under ``tmp_path`` alone and send no request: the fetchers are
replaced, or a route of respx answers.
"""

import csv
import importlib.util
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx
from xippios.core import (
    ClientConfig,
    PackagedList,
    RetryPolicy,
    TransportError,
    UpstreamError,
)
from xippios.core.testing import ReplayFixture

from xippios.usda.nass import api
from xippios.usda.nass._client import BASE_URL, client
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
REFERENCE = ROOT / "src" / "xippios" / "usda" / "nass" / "reference"
COLUMNS = REFERENCE / "columns.csv"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_reference", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def test_columns_from_snapshot_equals_the_committed_columns_csv() -> None:
    rows = script.columns_from_snapshot()
    with COLUMNS.open(newline="", encoding="utf-8") as handle:
        assert rows == list(csv.DictReader(handle))
    assert script.columns_csv(rows).encode("utf-8") == COLUMNS.read_bytes()


def test_refresh_stops_before_any_write_when_the_table_does_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "param_define.md"
    snapshot.write_text(
        "| Column or Header Name | Max Length | Definition |\n| --- | --- | --- |\n",
        encoding="utf-8",
    )

    def refused(*args: object) -> None:
        raise AssertionError("refresh wrote or fetched before the column table parsed")

    monkeypatch.setattr(script, "PARAM_DEFINE", snapshot)
    monkeypatch.setattr(script, "sync", refused)
    monkeypatch.setattr(script, "write", refused)
    monkeypatch.setattr(script, "COLUMNS", tmp_path / "columns.csv")
    with pytest.raises(SystemExit, match="no HTML column table"):
        script.refresh()
    assert not (tmp_path / "columns.csv").exists()


# --- the run's fetches: one attempt each, counted, all before the first write ---


def packaged_list(name: str, values: list[str]) -> PackagedList:
    """A list as a fetch returns it, for the tests that replace the fetchers."""
    return PackagedList(
        param="unit_desc" if name in DERIVED_LISTS else name,
        endpoint="api_GET" if name in DERIVED_LISTS else "get_param_values",
        fetched=datetime(2026, 11, 20, 9, 0, 0, tzinfo=UTC),
        records=[{"unit_desc" if name in DERIVED_LISTS else name: value} for value in values],
    )


@pytest.fixture
def reference_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The packaged files copied under ``tmp_path``, and the script's ``REFERENCE`` and
    ``COLUMNS`` pointed at the copy: a test reads what a run writes there, and nothing in
    the package moves. A test that keeps a run from fetching replaces the fetchers
    itself."""
    reference = tmp_path / "reference"
    shutil.copytree(REFERENCE, reference)
    monkeypatch.setattr(script, "REFERENCE", reference)
    monkeypatch.setattr(script, "COLUMNS", reference / "columns.csv")
    return reference


def files(reference: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(reference.iterdir())}


def test_refresh_fetches_every_list_before_it_writes_one(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch that fails after others succeeded leaves every packaged file as it was, so
    a failed run is run again whole."""
    before = files(reference_copy)
    fetched: list[str] = []

    def fetch_param(param: str) -> PackagedList:
        fetched.append(param)
        if len(fetched) == 3:
            raise UpstreamError("503 from upstream", status=503, body="", source="usda-nass")
        return packaged_list(param, ["A NEW VALUE"])

    monkeypatch.setattr(script, "fetch_param", fetch_param)
    with pytest.raises(UpstreamError):
        script.refresh()
    assert fetched == list(PACKAGED_PARAMS[:3])
    assert files(reference_copy) == before


def test_refresh_writes_every_list_once_all_are_fetched(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nine packaged parameters and the two derived lists, each written once every
    fetch is done, then columns.csv rebuilt from the snapshot."""
    order: list[str] = []

    def fetch_param(param: str) -> PackagedList:
        order.append(param)
        return packaged_list(param, ["X"])

    def fetch_derived(name: str, filters: object, year: int) -> PackagedList:
        order.append(name)
        return packaged_list(name, ["PCT X"])

    def write(name: str, packaged: PackagedList) -> None:
        order.append(f"write {name}")

    monkeypatch.setattr(script, "fetch_param", fetch_param)
    monkeypatch.setattr(script, "fetch_derived", fetch_derived)
    monkeypatch.setattr(script, "write", write)
    (reference_copy / "columns.csv").unlink()
    script.refresh()
    names = [*PACKAGED_PARAMS, *DERIVED_LISTS]
    assert order == [*names, *(f"write {name}" for name in names)]
    assert (reference_copy / "columns.csv").read_bytes() == COLUMNS.read_bytes()


def test_only_refuses_a_list_it_does_not_package_before_any_request(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: object) -> PackagedList:
        raise AssertionError("a request sent before --only was checked")

    monkeypatch.setattr(script, "fetch_param", refused)
    monkeypatch.setattr(script, "fetch_derived", refused)
    with pytest.raises(SystemExit, match="--only: no list state_alfa, commodity_desc in "):
        script.refresh(["state_alfa", "unit_desc", "commodity_desc"])


def test_only_refuses_to_keep_a_list_that_is_not_packaged_before_any_request(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--only`` keeps every other list's file, so each must be packaged: with
    ``sector_desc.json`` absent, ``--only state_alpha`` stops before its keyed request and
    writes nothing, where it fetched, wrote ``state_alpha.json`` and then stopped in the
    render (finding 3 of the review of https://github.com/xippios/sdk-usda-nass/pull/72)."""
    (reference_copy / "sector_desc.json").unlink()
    before = files(reference_copy)

    def refused(*args: object) -> PackagedList:
        raise AssertionError("a request sent before the kept lists were checked")

    monkeypatch.setattr(script, "fetch_param", refused)
    monkeypatch.setattr(script, "fetch_derived", refused)
    with pytest.raises(SystemExit, match=r"^sector_desc is not packaged yet: run without --only$"):
        script.refresh(["state_alpha"])
    assert files(reference_copy) == before


def test_only_fetches_the_named_lists_and_keeps_every_other_file(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--only state_alpha progress_stages`` writes those two files alone; the other
    packaged files and columns.csv keep their bytes."""
    before = files(reference_copy)
    monkeypatch.setattr(script, "fetch_param", lambda param: packaged_list(param, ["ZZ"]))
    monkeypatch.setattr(
        script, "fetch_derived", lambda name, filters, year: packaged_list(name, ["PCT ZZ"])
    )
    script.refresh(["state_alpha", "progress_stages"])
    after = files(reference_copy)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"state_alpha.json", "progress_stages.json"}
    assert PackagedList.model_validate_json(after["state_alpha.json"]).records == [
        {"state_alpha": "ZZ"}
    ]


def test_the_script_renders_no_module_and_takes_only(capsys: pytest.CaptureFixture[str]) -> None:
    """The script writes the packaged lists and ``columns.csv`` alone: the package ships
    no module of enums to render, so ``--render-only`` left with the render, and ``--only``
    is the one option (https://github.com/xippios/sdk-usda-nass/issues/89)."""
    with pytest.raises(SystemExit) as info:
        script.main(["--help"])
    assert info.value.code == 0
    usage = capsys.readouterr().out
    assert "--only LIST [LIST ...]" in usage
    assert "--render-only" not in usage
    assert not hasattr(script, "render")


@pytest.mark.anyio
async def test_metered_sends_each_request_once_and_reports_the_count(
    respx_mock: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    """NOT RECORDED: a bare 503, a body of no shape upstream was seen to send, to show
    that the run leaves it to core (conventions §10). Inside ``metered`` the client sends
    it once, where its retry policy would send it again, and the count is printed after
    the block, a failed run's too; Quick Stats reports no quota left, so none is read.
    The client's configuration is restored after the block."""
    route = respx_mock.get(f"{BASE_URL}/get_param_values/").mock(return_value=httpx.Response(503))
    configured = client.config
    assert configured.retry.max_attempts > 1
    meters: list[object] = []
    retries: list[RetryPolicy] = []

    async def run() -> None:
        with script.metered(client) as meter:
            meters.append(meter)
            retries.append(client.config.retry)
            await api.get_param_values("commodity_desc")

    with pytest.raises(UpstreamError):
        await run()
    assert retries == [RetryPolicy(max_attempts=1)]
    assert route.call_count == 1
    assert [meter.sent for meter in meters] == [1]  # type: ignore[attr-defined]
    assert client.config is configured
    assert script.QUOTA_HEADER is None
    assert capsys.readouterr().out == "requests sent: 1; quota left: not reported\n"


@pytest.mark.anyio
async def test_metered_waits_300_seconds_for_an_answer_and_restores_the_client(
    replay_fixture: ReplayFixture,
) -> None:
    """Inside ``metered`` the client waits up to 300 seconds for an answer, where its own
    configuration waits 60: two runs stopped at a list that Quick Stats answered late
    (https://github.com/xippios/sdk-usda-nass/issues/78). Its connect, write and pool
    timeouts stay the client's, and it sends each request once. Core builds the client's
    pool, and with it the timeouts every request carries, at the first request in an
    event loop, so the request sent shows the run's. After the block the client's
    configuration is its own again."""
    route = replay_fixture("get_param_values", "sector_desc")
    configured = client.config
    assert configured.timeouts.read == 60.0
    inside: list[ClientConfig] = []
    with script.metered(client):
        inside.append(client.config)
        await api.get_param_values("sector_desc")
    timeouts = replace(configured.timeouts, read=300.0)
    assert [(config.timeouts, config.retry) for config in inside] == [
        (timeouts, RetryPolicy(max_attempts=1))
    ]
    assert route.call_count == 1
    assert route.calls.last.request.extensions["timeout"] == {
        **configured.timeouts.to_httpx().as_dict(),
        "read": 300.0,
    }
    assert client.config is configured


@pytest.mark.anyio
async def test_metered_sends_a_list_not_answered_in_time_once_and_restores_the_client(
    respx_mock: respx.MockRouter,
) -> None:
    """NOT RECORDED: no answer at all; the route raises ``httpx.ReadTimeout``, as httpx
    does once the read timeout passes, since a wait that ends without an answer leaves
    nothing to record (conventions §10). The request carries the run's 300 seconds and
    is sent once, where the client's retry policy would send a timed-out GET again; the
    run fails with core's ``TransportError``, and the client's configuration is its own
    again after the block."""
    sent: list[dict[str, float]] = []

    def unanswered(request: httpx.Request) -> httpx.Response:
        sent.append(request.extensions["timeout"])
        raise httpx.ReadTimeout("no answer within the read timeout", request=request)

    route = respx_mock.get(f"{BASE_URL}/get_param_values/").mock(side_effect=unanswered)
    configured = client.config
    assert configured.retry.retry_transport_errors
    assert configured.retry.max_attempts > 1
    with pytest.raises(TransportError), script.metered(client):
        await api.get_param_values("agg_level_desc")
    assert route.call_count == 1
    assert [timeout["read"] for timeout in sent] == [300.0]
    assert client.config is configured
