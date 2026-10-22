"""The adapters expose exactly the tasks and nothing else (ADR-0001)."""

import pytest
from xippios.core.mcp import tool_name

from xippios.usda.nass import tasks
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.http import router
from xippios.usda.nass.mcp import server

pytestmark = pytest.mark.anyio


async def test_mcp_tools_are_the_tasks() -> None:
    expected = {tool_name(SOURCE, getattr(tasks, name)) for name in tasks.__all__}
    assert {tool.name for tool in await server.list_tools()} == expected


async def test_http_routes_are_the_tasks() -> None:
    expected = {f"/{SOURCE}/{name}" for name in tasks.__all__}
    assert {getattr(route, "path", None) for route in router.routes} == expected
