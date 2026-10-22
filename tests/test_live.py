"""Live smoke tests: skipped unless XIPPIOS_LIVE_TESTS=1 (conventions §10).

Every task function gets one live smoke test here, next to the reachability check.
"""

import pytest

from xippios.usda.nass import tasks
from xippios.usda.nass._client import client

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_upstream_answers() -> None:
    response = await client.request("GET", "/", raise_on_error=False)
    assert response.status_code < 500


async def test_get_counts_live() -> None:
    result = await tasks.get_counts_async(
        {"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}
    )
    assert result.data > 0
    assert result.meta.request["commodity_desc"] == "CORN"
