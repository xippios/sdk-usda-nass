"""MCP server for USDA NASS Quick Stats.

Every task in ``tasks.__all__`` is a read-only tool, but those ``tasks.BULK_TASKS``
names, which core skips: the server is passed ``tasks.__all__`` whole (ADR-0019). No
logic lives here (ADR-0001). Entry point: ``xippios-usda-nass-mcp``.
"""

from xippios.core.mcp import build_server, main

from xippios.usda.nass import tasks
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass._version import __version__

INSTRUCTIONS = (
    "USDA NASS Quick Stats via xippios. "
    "Tools are read-only. Where list tools (usda_nass_list_*) exist, "
    "call them first to find valid values, then query."
)

server = build_server(
    SOURCE,
    [getattr(tasks, name) for name in tasks.__all__],
    version=__version__,
    instructions=INSTRUCTIONS,
    caps=getattr(tasks, "MCP_CAPS", None),
)


def run() -> None:
    """Run the server: stdio by default, ``--http`` for streamable HTTP."""
    # Command-line options of the source's own reach core's parser through its hooks
    # (ADR-0014): main(server, add_options=<adds them>, apply_options=<returns the server>).
    main(server)
