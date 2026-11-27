"""Live smoke tests, one per task, and the nightly comparison of the packaged lists.

Skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10); ``/add-endpoint`` adds the smoke
tests. Core's ``test_packaged_list_is_current`` runs once for each entry of ``LIVE_LISTS``,
the nine packaged parameter lists, by the star import below (sdk-core ADR-0055). The run's
requests stand in the line that core's plugin prints at its end, ``requests sent by the
live run``, with each host and its count.
"""

from functools import partial

import pytest
from xippios.core.testing.live import *  # noqa: F403

from xippios.usda.nass import api, params, tasks
from xippios.usda.nass.params import PACKAGED_PARAMS

pytestmark = [pytest.mark.live, pytest.mark.anyio]

LIVE_LISTS = {
    param: (params.codes(param), partial(api.get_param_values, param)) for param in PACKAGED_PARAMS
}
"""The nine packaged parameter lists, each compared with the list upstream serves now by one
keyed ``get_param_values`` call through the wrapper the refresh script fetches it with
(https://github.com/xippios/sdk-usda-nass/issues/58)."""

NO_LIVE_LIST: dict[str, str] = {}
"""No packaged list goes uncompared: the package ships the nine parameter lists alone."""


async def test_get_counts_live() -> None:
    result = await tasks.get_counts_async(
        {"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}
    )
    assert result.data > 0
    assert result.meta.request["commodity_desc"] == "CORN"


async def test_get_data_live() -> None:
    result = await tasks.get_data_async(
        {
            "commodity_desc": "CORN",
            "year": 2012,
            "state_alpha": "VA",
            "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE",
        }
    )
    assert result.data
    commodity = result.data[0].commodity_desc  # bound first, so a failure prints no record
    assert commodity == "CORN"
    figure = result.data[0].value_number
    assert figure is not None


async def test_list_param_values_live() -> None:
    """A parameter the package does not ship, so the call reaches upstream."""
    assert "commodity_desc" not in PACKAGED_PARAMS
    result = await tasks.list_param_values_async("commodity_desc")
    assert result.meta.endpoint == "get_param_values"
    count = len(result.data)  # bound first, so a failure prints a number, not the list
    assert count > 100
    has_corn = "CORN" in result.data
    assert has_corn
