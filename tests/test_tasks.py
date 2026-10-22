"""Structural checks every task must satisfy. Per-task tests with recorded fixtures go below."""

import inspect
from collections.abc import Callable

import pytest
import respx

from xippios.usda.nass import __version__, tasks

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
