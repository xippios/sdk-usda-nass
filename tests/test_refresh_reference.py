"""``scripts/refresh_reference.py`` offline: its column table parser, its run and its render.

``columns.csv`` is rebuilt from the HTML column table the snapshot keeps in
``docs/upstream/param_define.md`` (conventions §3). A run sends each request once and
counts it, fetches every list before it writes one, and with ``--only`` fetches the lists
it names alone. These tests read the committed snapshot and files, write under
``tmp_path`` alone and send no request: the fetchers are replaced, or a route of respx
answers.
"""

import csv
import importlib.util
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx
from xippios.core import PackagedList, RetryPolicy, UpstreamError

from xippios.usda.nass import api
from xippios.usda.nass._client import BASE_URL, client
from xippios.usda.nass.params import DERIVED_LISTS, PACKAGED_PARAMS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_reference.py"
REFERENCE = ROOT / "src" / "xippios" / "usda" / "nass" / "reference"
COLUMNS = REFERENCE / "columns.csv"
ENUMS = ROOT / "src" / "xippios" / "usda" / "nass" / "enums.py"


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
    monkeypatch.setattr(script, "render", refused)
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
    """The packaged files copied under ``tmp_path``, the script pointed at them, and its
    render replaced: a test reads what a run writes, and nothing in the package moves."""
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
    a failed run is run again whole, and enums.py is not rendered."""
    before = files(reference_copy)
    fetched: list[str] = []

    def fetch_param(param: str) -> PackagedList:
        fetched.append(param)
        if len(fetched) == 3:
            raise UpstreamError("503 from upstream", status=503, body="", source="usda-nass")
        return packaged_list(param, ["A NEW VALUE"])

    def rendered() -> None:
        raise AssertionError("enums.py rendered after a failed fetch")

    monkeypatch.setattr(script, "fetch_param", fetch_param)
    monkeypatch.setattr(script, "render", rendered)
    with pytest.raises(UpstreamError):
        script.refresh()
    assert fetched == list(PACKAGED_PARAMS[:3])
    assert files(reference_copy) == before


def test_refresh_writes_every_list_once_all_are_fetched(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The nine packaged parameters and the two derived lists, each written once every
    fetch is done, then enums.py rendered and columns.csv rebuilt from the snapshot."""
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
    monkeypatch.setattr(script, "render", lambda: order.append("render"))
    (reference_copy / "columns.csv").unlink()
    script.refresh()
    names = [*PACKAGED_PARAMS, *DERIVED_LISTS]
    assert order == [*names, *(f"write {name}" for name in names), "render"]
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


def test_only_fetches_the_named_lists_and_keeps_every_other_file(
    reference_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--only state_alpha progress_stages`` writes those two files and renders
    enums.py; the other packaged files and columns.csv keep their bytes."""
    before = files(reference_copy)
    rendered: list[bool] = []
    monkeypatch.setattr(script, "fetch_param", lambda param: packaged_list(param, ["ZZ"]))
    monkeypatch.setattr(
        script, "fetch_derived", lambda name, filters, year: packaged_list(name, ["PCT ZZ"])
    )
    monkeypatch.setattr(script, "render", lambda: rendered.append(True))
    script.refresh(["state_alpha", "progress_stages"])
    after = files(reference_copy)
    changed = {name for name in after if after[name] != before[name]}
    assert changed == {"state_alpha.json", "progress_stages.json"}
    assert rendered == [True]
    assert PackagedList.model_validate_json(after["state_alpha.json"]).records == [
        {"state_alpha": "ZZ"}
    ]


def test_only_and_render_only_exclude_each_other() -> None:
    with pytest.raises(SystemExit) as info:
        script.main(["--render-only", "--only", "state_alpha"])
    assert info.value.code == 2


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


def test_render_writes_enums_py_as_committed() -> None:
    """``--render-only``'s text, formatted as the script formats it, is ``enums.py`` byte
    for byte: core's default names every class but the two the script names, the progress
    stages and condition categories (https://github.com/xippios/sdk-core/issues/95). The
    text goes through ruff on stdin with the repository's configuration; nothing is
    written."""
    text = script.module()
    for command in (["format"], ["check", "--fix", "--quiet", "--exit-zero"]):
        text = subprocess.run(
            [sys.executable, "-m", "ruff", *command, "--stdin-filename", str(ENUMS), "-"],
            input=text,
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=True,
        ).stdout
    assert text == ENUMS.read_text(encoding="utf-8")
    assert script.CLASS_NAMES == {
        "progress_stages": "ProgressStage",
        "condition_categories": "ConditionCategory",
    }
