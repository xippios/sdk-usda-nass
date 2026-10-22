"""MCP server for USDA NASS Quick Stats.

Every task in ``tasks.__all__`` is a read-only tool. No logic lives here (ADR-0001).
Entry point: ``xippios-usda-nass-mcp``.
"""

from xippios.core.mcp import build_server, main

from xippios.usda.nass import tasks
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass._version import __version__

INSTRUCTIONS = (
    "USDA NASS Quick Stats via xippios. "
    "Tools are read-only. Call the list tools first to find valid codes, then query."
)

server = build_server(
    SOURCE,
    [getattr(tasks, name) for name in tasks.__all__],
    version=__version__,
    instructions=INSTRUCTIONS,
)


def run() -> None:
    """Run the server: stdio by default, ``--http`` for streamable HTTP."""
    main(server)
