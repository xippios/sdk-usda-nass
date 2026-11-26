"""``scripts/refresh_reference.py`` offline: its declaration to core's frame and its own code.

The frame, ``xippios.core.refresh``, fetches every list before it writes one, each request
sent once and counted, writes the packaged files and the provenance rows of
``reference/README.md``, and takes ``--only`` and ``--render-only``; core's own tests hold
each (sdk-core ADR-0062). What stays the package's is its one ``Lists`` of nine ``Listed``,
its fetch, ``columns.csv``, parsed from the HTML column table the snapshot keeps in
``docs/upstream/param_define.md`` before the first request and written after the last on a
full run (conventions §3), and the read timeout of 300 seconds. These tests read the
committed snapshot and files, write under ``tmp_path`` alone and send no request but to a
route of respx; no test runs the frame's fetches, which write into the package itself.
"""

import csv
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import respx
from xippios.core import ClientConfig, PackagedList
from xippios.core.refresh import Listed, Lists
from xippios.core.testing import ReplayFixture

from xippios.usda.nass import api
from xippios.usda.nass._client import client
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS

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


# --- the declaration: one Lists of the nine parameter lists, no enum ---


def test_the_script_declares_the_nine_packaged_lists_in_one_lists() -> None:
    """The nine parameter lists that the package declares it ships, each from
    ``get_param_values`` and none with an enum, so the frame leaves ``enums.py`` alone, and
    the column table's parse and write as the declaration's two hooks (sdk-core ADR-0062;
    https://github.com/xippios/sdk-core/issues/482)."""
    lists = script.LISTS
    assert isinstance(lists, Lists)
    assert (lists.package, lists.client, lists.quota_header) == (PACKAGE, client, None)
    assert tuple(lists.packaged) == PACKAGED_PARAMS
    assert all(isinstance(listed, Listed) for listed in lists.lists)
    assert [listed.name for listed in lists.lists] == list(PACKAGED_PARAMS)
    assert len(lists.lists) == 9
    for listed in lists.lists:
        assert (listed.endpoint, listed.enum) == ("get_param_values", None), listed.name
    assert lists.before == script.COLUMNS_CSV.before
    assert lists.after == script.COLUMNS_CSV.after
    assert not (REFERENCE.parent / "enums.py").exists()


def test_each_origin_is_the_row_reference_readme_holds() -> None:
    """The frame writes the provenance rows from each list's origin, so the origins give
    the rows as committed: the operation and its parameter."""
    readme = (REFERENCE / "README.md").read_text(encoding="utf-8")
    rows = {
        line.split(" | ")[0].removeprefix("| `").removesuffix("`"): line.split(" | ")[1]
        for line in readme.splitlines()
        if line.startswith("| `")
    }
    for listed in script.LISTS.lists:
        assert listed.origin == rows[f"{listed.name}.json"], listed.name


# --- the fetch, through the wrapper ---


@pytest.mark.anyio
async def test_a_parameter_list_is_fetched_at_the_wrappers_retrieved_at(
    replay_fixture: ReplayFixture,
) -> None:
    """One ``get_param_values`` call through the layer-1 wrapper, never the task, which
    would answer from the package; the list is stamped with the answer's time, its values
    records of one field named by the parameter."""
    route = replay_fixture("get_param_values", "sector_desc")
    sector = next(listed for listed in script.LISTS.lists if listed.name == "sector_desc")
    packaged = await sector.fetch()
    assert isinstance(packaged, PackagedList)
    assert (packaged.param, packaged.endpoint) == ("sector_desc", "get_param_values")
    assert {"sector_desc": "CROPS"} in packaged.records
    assert route.call_count == 1


# --- columns.csv: parsed before the first request, written after the last on a full run ---


def test_columns_csv_stops_the_run_before_any_request_when_the_table_does_not_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A snapshot whose table the parser cannot read stops the run in ``before``, which
    the frame calls before its first request."""
    snapshot = tmp_path / "param_define.md"
    snapshot.write_text(
        "| Column or Header Name | Max Length | Definition |\n| --- | --- | --- |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "PARAM_DEFINE", snapshot)
    monkeypatch.setattr(script, "COLUMNS", tmp_path / "columns.csv")
    rebuild = script.ColumnsCsv()
    with pytest.raises(SystemExit, match="no HTML column table"):
        rebuild.before()
    assert not (tmp_path / "columns.csv").exists()


def test_columns_csv_is_written_after_a_full_run_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--only`` keeps every other file as it is, ``columns.csv`` among them."""
    written = tmp_path / "columns.csv"
    monkeypatch.setattr(script, "COLUMNS", written)
    rebuild = script.ColumnsCsv()
    rebuild.before()
    lists = {name: PackagedList.load(PACKAGE, name) for name in PACKAGED_PARAMS}
    rebuild.after({"state_alpha": lists["state_alpha"]})
    assert not written.exists()
    rebuild.after(lists)
    assert written.read_bytes() == COLUMNS.read_bytes()


# --- the read timeout around the frame's run ---


@pytest.mark.anyio
async def test_the_run_waits_300_seconds_for_an_answer_and_restores_the_client(
    replay_fixture: ReplayFixture,
) -> None:
    """Around the frame's run the client waits up to 300 seconds for an answer, where its
    own configuration waits 60: two runs stopped at a list that Quick Stats answered late
    (https://github.com/xippios/sdk-usda-nass/issues/78). Its connect, write and pool
    timeouts and its retry stay the client's, the frame sending each request once. Core
    builds the client's pool, and with it the timeouts every request carries, at the first
    request in an event loop, so the request sent shows the run's. After the block the
    client's configuration is its own again."""
    route = replay_fixture("get_param_values", "sector_desc")
    configured = client.config
    assert configured.read_timeout == 60.0
    inside: list[ClientConfig] = []
    with script.read_timeout(client):
        inside.append(client.config)
        await api.get_param_values("sector_desc")
    assert [(config.read_timeout, config.retry) for config in inside] == [(300.0, configured.retry)]
    assert route.call_count == 1
    assert route.calls.last.request.extensions["timeout"] == {
        "connect": 10.0,
        "read": 300.0,
        "write": 10.0,
        "pool": 10.0,
    }
    assert client.config is configured


# --- the command line, the frame's ---


def test_the_command_line_is_the_frames(capsys: pytest.CaptureFixture[str]) -> None:
    """``--only`` and ``--render-only`` are the frame's, and the script adds no option of
    its own; ``--help`` sends nothing and leaves the client as it was."""
    configured = client.config
    with pytest.raises(SystemExit) as info:
        script.main(["--help"])
    assert info.value.code == 0
    usage = " ".join(capsys.readouterr().out.split())
    assert "--render-only" in usage
    assert "--only LIST [LIST ...]" in usage
    assert client.config is configured


def test_only_refuses_a_list_it_does_not_package_before_any_request(
    respx_mock: respx.MockRouter,
) -> None:
    """The frame checks ``--only`` before its first request and writes nothing: respx is
    active with no route mounted, so a request would fail loudly."""
    before = {path.name: path.read_bytes() for path in REFERENCE.iterdir()}
    with pytest.raises(SystemExit, match="--only: no list state_alfa, commodity_desc in "):
        script.main(["--only", "state_alfa", "unit_desc", "commodity_desc"])
    assert not respx_mock.calls
    assert {path.name: path.read_bytes() for path in REFERENCE.iterdir()} == before
