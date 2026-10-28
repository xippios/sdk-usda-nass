"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``meta.published_at`` stays empty: Quick Stats publishes no release time, and the
per-row ``load_time`` carries no zone. Reading one into it would be a guess; that
belongs to the normalisation layer, not here.

``get_data(split_by_year=True)`` splits one call into at most ``split_ceiling()`` years:
``SPLIT_CEILING`` (20) in Python and over HTTP; the MCP server starts with
``MCP_SPLIT_YEARS`` (5), and its ``--split-years`` sets another ceiling from 1 to 20
through core's option hooks (``mcp_add_options``, ``mcp_apply_options``; ADR-0014). The
entry point ``xippios-usda-nass-mcp`` sets the MCP ceiling, since core's ``main`` applies
the option, so a host that imports ``xippios.usda.nass.mcp.server`` and serves it another
way keeps 20. The ceiling is process-wide: a Python or HTTP call made in the MCP server's
process meets the MCP ceiling too.
"""

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from xippios.core import (
    InvalidRequestError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    UpstreamModel,
    parse_decimal,
    sync,
)

from xippios.usda.nass import api
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.enums import ConditionCategory, FreqDesc, ProgressStage, StateAlpha
from xippios.usda.nass.errors import MCP_SPLIT_YEARS, RECORD_LIMIT, SPLIT_CEILING, QueryTooLarge
from xippios.usda.nass.models import (
    AcreageRecord,
    AreaStatistic,
    CountyEstimateRecord,
    CropProgressRecord,
    Filters,
    GrainStocksRecord,
    PriceReceivedRecord,
    QuickStatsRecord,
)
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS, validate_filters

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

__all__ = [
    "get_acreage",
    "get_acreage_forecasts",
    "get_counts",
    "get_county_production",
    "get_county_yield",
    "get_crop_condition",
    "get_crop_progress",
    "get_data",
    "get_grain_stocks",
    "get_prices_received",
    "list_param_values",
]

# A task named here is Python-only: no tool, no route; the adapters skip it (ADR-0019 decision 4).
BULK_TASKS: frozenset[str] = frozenset()

MCP_CAPS: Mapping[str, ResultCap] = {
    "list_param_values": ResultCap(
        max_rows=1000,
        note=(
            "usda_nass_list_param_values takes no filter to reach the rest; a value past "
            "the cap is still accepted as a filter value by usda_nass_get_counts and "
            "usda_nass_get_data"
        ),
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, ADR-0016).

``list_param_values`` is the reference lookup an agent needs whole to form valid filters,
and its lists run past the family's default of 200 rows. Of the nine packaged lists
(fetched 2026-10-28), ``statisticcat_desc`` has 278 values, ``unit_desc`` 373 and
``domain_desc`` 616 (22,194 bytes of compact JSON, the largest), the other six fewer than
60; lists fetched live run longer too (``commodity_desc`` has 467 values, 6,773 bytes,
recorded 2026-10-28). Its cap keeps the default 64 KB, and its note promises no filter,
since the tool has none. Every other tool keeps the default, 200 rows or 64 KB, with
core's note.
"""


_split_ceiling = SPLIT_CEILING
"""The split ceiling in force, process-wide: ``split_ceiling`` reads it,
``set_split_ceiling`` sets it."""


def split_ceiling() -> int:
    """The most years one ``get_data(split_by_year=True)`` call splits into, e.g. ``20``.

    ``SPLIT_CEILING`` (20) unless ``set_split_ceiling`` set another, as the entry point
    ``xippios-usda-nass-mcp`` does when it starts the MCP server: ``MCP_SPLIT_YEARS`` (5),
    or its ``--split-years``. The setting is process-wide, so every split in the process
    meets the same ceiling, from Python, over HTTP or over MCP: one MCP server per
    process.
    """
    return _split_ceiling


def set_split_ceiling(years: int) -> None:
    """Set the most years one ``get_data(split_by_year=True)`` call splits into, process-wide.

    A split of more years is refused before its first yearly count, naming the ceiling;
    below ``SPLIT_CEILING`` the refusal calls it the ceiling set for this process and says
    that the MCP server starts with 5 by default and that ``--split-years`` raises it, up
    to 20. No ceiling goes above ``SPLIT_CEILING``. The entry point
    ``xippios-usda-nass-mcp`` calls this once when it starts the MCP server
    (``mcp_apply_options``, which core's ``main`` applies); the setting is process-wide,
    so it holds for the Python API and an HTTP router in the same process too: one MCP
    server per process.

    Args:
        years: A whole number of years from 1 to 20 (``SPLIT_CEILING``), e.g. ``5`` (the
            MCP server's default), ``10``, ``20`` (the Python API's).

    Raises:
        InvalidRequestError: ``years`` is not a whole number from 1 to 20 (``True`` is
            not ``1``); the ceiling stays as it was.
    """
    global _split_ceiling
    whole = isinstance(years, int) and not isinstance(years, bool)
    if not whole or not 1 <= years <= SPLIT_CEILING:
        raise InvalidRequestError(
            "the split ceiling, --split-years on the MCP server, must be a whole number of "
            f"years from 1 to {SPLIT_CEILING}, got {years!r}.",
            source=SOURCE,
        )
    _split_ceiling = years


def mcp_add_options(parser: argparse.ArgumentParser) -> None:
    """Add ``--split-years`` to the MCP server's command line, a hook of core's ``main``.

    ``--split-years YEARS`` is the most years one ``usda_nass_get_data`` call with
    ``split_by_year`` splits into, a whole number from 1 to ``SPLIT_CEILING`` (20),
    ``MCP_SPLIT_YEARS`` (5) when not given; ``mcp_apply_options`` sets it. The ceiling is
    process-wide: one MCP server per process.

    Args:
        parser: Core's parser (``xippios.core.mcp.build_parser``), which then accepts
            e.g. ``xippios-usda-nass-mcp --split-years 10``.
    """
    parser.add_argument(
        "--split-years",
        type=int,
        default=MCP_SPLIT_YEARS,
        metavar="YEARS",
        help=(
            "most years one usda_nass_get_data call with split_by_year splits into, 1 to "
            f"{SPLIT_CEILING} (default {MCP_SPLIT_YEARS}); up to two keyed calls a year, so "
            f"{MCP_SPLIT_YEARS} years take at most {2 * MCP_SPLIT_YEARS + 1} calls"
        ),
    )


def mcp_apply_options(namespace: argparse.Namespace, server: "MCPServer") -> "MCPServer":
    """Set the split ceiling from ``--split-years``, a hook of core's ``main``.

    Calls ``set_split_ceiling(namespace.split_years)`` and returns ``server`` unchanged.
    The ceiling is process-wide: one MCP server per process. A value outside 1 to 20
    raises ``InvalidRequestError``, which core's ``main`` turns into the parser's error:
    the message on stderr, exit status 2, nothing served.

    Args:
        namespace: The parsed command line with ``split_years`` from
            ``mcp_add_options``, e.g. ``argparse.Namespace(split_years=5)``.
        server: The server ``mcp.py`` built, returned as it is.

    Returns:
        ``server`` itself.
    """
    set_split_ceiling(namespace.split_years)
    return server


def _meta(endpoint: str, request: dict[str, Any], *, total: int | None = None) -> ResultMeta:
    return ResultMeta(source=SOURCE, endpoint=endpoint, request=request, total=total)


def _project[M: UpstreamModel](model: type[M], record: QuickStatsRecord) -> M:
    overrides: dict[str, Any] = {}
    if "cv_percent" in model.model_fields:
        overrides["cv_percent"] = parse_decimal(record.cv_percent)
    return model.project(record, **overrides)


async def _slice[M: UpstreamModel](
    filters: dict[str, str | int], model: type[M], order: Callable[[M], Any]
) -> Result[list[M]]:
    """Fetch a task-shaped slice without the count check: its filters keep it small.

    An over-limit answer still raises ``QueryTooLarge`` from the wrapper. Without the
    count, ``meta.total`` stays ``None``.
    """
    checked = validate_filters(filters)
    response = await api.api_get(checked)
    rows = sorted((_project(model, record) for record in response.data), key=order)
    return Result(data=rows, meta=_meta("api_GET", checked))


def _level(state: StateAlpha | None, filters: dict[str, str | int]) -> dict[str, str | int]:
    filters["agg_level_desc"] = "NATIONAL" if state is None else "STATE"
    if state is not None:
        filters["state_alpha"] = state.value
    return filters


async def get_counts_async(filters: Filters) -> Result[int]:
    """Count the Quick Stats records a set of filters would return, before fetching them.

    ``api_GET`` returns at most 50,000 records; check the count first and narrow the
    filters when it is higher. ``data`` is the count, and ``meta.total`` carries the
    same number.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values. Keys are checked against the column table before anything is sent;
            an unknown column or operator raises ``InvalidRequestError`` naming it. A
            parameter ``list_param_values`` answers from packaged data (``state_alpha``,
            ``sector_desc``, ``agg_level_desc``, ...), given without an operator, takes a
            value of its list only, in any case, since Quick Stats ignores case
            (``"va"`` counts what ``"VA"`` counts), and is sent as given; another raises
            ``UnknownCode`` before anything is sent, naming the list, its fetch date and
            the closest known values, or pointing at ``list_param_values`` (the tool
            ``usda_nass_list_param_values``) when none is close.
            Columns are the What, Where and When dimensions, for example
            ``commodity_desc`` (``"CORN"``), ``statisticcat_desc`` (``"AREA PLANTED"``),
            ``agg_level_desc`` (``"STATE"``, ``"COUNTY"``), ``state_alpha`` (``"VA"``),
            ``year`` (``2012``), ``freq_desc`` (``"ANNUAL"``). Operators are suffixes:
            ``__LE``, ``__LT``, ``__GT``, ``__GE``, ``__LIKE``, ``__NOT_LIKE``, ``__NE``,
            so ``{"commodity_desc": "CORN", "year__GE": 2012, "state_alpha": "VA"}``
            counts corn records for Virginia from 2012 on. Quick Stats keeps one bound on
            ``year`` per query (recorded 2026-10-28): it counts ``year__GE`` with
            ``year__LE`` as ``year__GE`` alone, in either order, and drops ``year__GE``
            beside ``year__LT``; ``get_data`` with ``split_by_year`` fetches a two-sided
            year range year by year and splits an over-limit ``year__GE`` range.
    """
    checked = validate_filters(filters)
    response = await api.get_counts(checked)
    return Result(data=response.count, meta=_meta("get_counts", checked, total=response.count))


_BOUNDED_FORMS = (
    "year (one year, e.g. 2022), year__GE with year__LE (e.g. 2020 and 2023, neither past "
    "the current UTC year), or year__GE alone (up to the current UTC year)"
)


def _is_year(key: str) -> bool:
    return key.partition("__")[0] == "year"


def _year(filters: Mapping[str, str | int], key: str) -> int:
    value = filters[key]
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvalidRequestError(
            f"split_by_year: {key}={value!r} is not a year; give a whole year, e.g. 2022.",
            source=SOURCE,
        ) from None


def _years(filters: Mapping[str, str | int]) -> range:
    """The years ``split_by_year`` queries one by one, read from the year filters.

    Raises:
        InvalidRequestError: The year filters are none of the three bounded forms, a
            bound is not a whole year, a ``year__GE`` or ``year__LE`` is past the current
            UTC year, or the range holds no year.
    """
    now = datetime.now(UTC).year
    keys = sorted(key for key in filters if _is_year(key))
    if keys == ["year"]:
        first = last = _year(filters, "year")
    elif keys == ["year__GE", "year__LE"]:
        first, last = _year(filters, "year__GE"), _year(filters, "year__LE")
    elif keys == ["year__GE"]:
        first, last = _year(filters, "year__GE"), now
    else:
        given = ", ".join(keys) if keys else "none"
        raise InvalidRequestError(
            f"split_by_year needs the years bounded in one of three forms: {_BOUNDED_FORMS}; "
            f"year filters given: {given}.",
            source=SOURCE,
        )
    for key in ("year__LE", "year__GE"):
        if key in keys and (bound := _year(filters, key)) > now:
            raise InvalidRequestError(
                f"split_by_year: {key}={bound} is past the current UTC year, {now}; the "
                f"range must end by {now}.",
                source=SOURCE,
            )
    if first > last:
        raise InvalidRequestError(
            f"split_by_year: the years run from {first} to {last}, a range without a year.",
            source=SOURCE,
        )
    return range(first, last + 1)


async def _split_by_year(
    filters: dict[str, str | int], years: range, request: dict[str, Any]
) -> Result[list[QuickStatsRecord]]:
    """Count every year of ``years``, then fetch the years that hold records, in year order.

    Each year's query is ``filters`` with ``year=<y>`` in place of the year filters.
    Every year is counted before the first fetch, so a year over the limit raises
    ``QueryTooLarge`` naming it before anything is fetched; a year counting 0 is not
    fetched. ``meta.total`` is the yearly counts summed.

    Raises:
        InvalidRequestError: ``years`` holds more than ``split_ceiling()`` years, the most
            one call splits into (conventions §4); raised before the first yearly count.
            Below ``SPLIT_CEILING`` the refusal calls it the ceiling set for this process
            and names the MCP server's default and ``--split-years``.
        QueryTooLarge: A year alone is over the limit.
    """
    ceiling = split_ceiling()
    if len(years) > ceiling:
        first, last = years[0], years[-1]
        bound = f"split_by_year covers at most {ceiling} years per call"
        if ceiling < SPLIT_CEILING:
            bound += (
                ", the ceiling set for this process (the MCP server starts with "
                f"{MCP_SPLIT_YEARS} by default; --split-years raises it, up to {SPLIT_CEILING})"
            )
        raise InvalidRequestError(
            f"{bound}; the years run from {first} to {last}, {len(years)} years. Give a "
            f"shorter range, e.g. year__GE={last - ceiling + 1} with year__LE={last}.",
            source=SOURCE,
        )
    rest = {key: value for key, value in filters.items() if not _is_year(key)}
    chunks: list[tuple[dict[str, str | int], int]] = []
    for year in years:
        chunk: dict[str, str | int] = {**rest, "year": year}
        count = (await api.get_counts(chunk)).count
        if count > RECORD_LIMIT:
            raise QueryTooLarge(count, year=year)
        chunks.append((chunk, count))
    data: list[QuickStatsRecord] = []
    for chunk, count in chunks:
        if count:
            data.extend((await api.api_get(chunk)).data)
    total = sum(count for _, count in chunks)
    return Result(data=data, meta=_meta("api_GET", request, total=total))


async def get_data_async(
    filters: Filters, *, split_by_year: bool = False
) -> Result[list[QuickStatsRecord]]:
    """Fetch published Quick Stats estimates for a set of filters, up to 50,000 records a call.

    Without ``split_by_year``, calls ``get_counts`` first: a count of zero returns an empty
    result without a second call, and a count above 50,000 raises ``QueryTooLarge`` with
    the count and a hint (narrower filters, or ``split_by_year``) before anything is
    fetched. With ``split_by_year``, a two-sided year range is fetched year by year, each
    year counted first and no count of the range sent; ``year__GE`` alone is counted
    first and split by year only when that count is above 50,000; ``year`` is counted
    first, and above 50,000 still raises ``QueryTooLarge``. ``meta.total`` is the count
    ``get_counts`` reported, ``0`` for the empty result, and the yearly counts summed for
    a split. Each record carries every Quick Stats column;
    ``value`` is the published figure as a string (``"510,000"``, or a suppression code
    such as ``"(D)"``) and ``value_number`` the parsed number.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values; the same shape and the same checks as for ``get_counts``: an
            unknown value of a packaged parameter raises ``UnknownCode`` naming the
            list, its fetch date and the closest known values, or pointing at
            ``list_param_values`` (the tool ``usda_nass_list_param_values``) when none
            is close. A query that stays well under the limit names the commodity, the
            statistic, the level and the time, e.g.
            ``{"commodity_desc": "CORN", "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE", "state_alpha": "VA", "year": 2012}``. Quick Stats
            keeps one bound on ``year`` per query (recorded 2026-10-28): it counts
            ``year__GE`` with ``year__LE`` as ``year__GE`` alone, in either order, and
            drops ``year__GE`` beside ``year__LT``, so a two-sided year range is served
            only by ``split_by_year``.
        split_by_year: ``True`` fetches the years one at a time where one call cannot serve
            them, splitting one call into at most 20 years in Python and over HTTP and 5 by
            default on the MCP server, whose ``--split-years`` sets 1 to 20. The filters
            bound the years in one of three forms, checked before any call: ``year``
            (``2022``), ``year__GE`` with ``year__LE`` (``2020`` and ``2023``), or
            ``year__GE`` alone, up to the current UTC year. Another year filter
            (``year__LE`` alone, ``year__GT``, ``year__NE``, ...), a mix or none raises
            ``InvalidRequestError`` naming the three forms, and a ``year__GE`` or
            ``year__LE`` past the current UTC year raises it naming that year. ``year`` is
            counted and fetched once, as without the flag; over the limit it raises
            ``QueryTooLarge`` naming the year. ``year__GE`` with ``year__LE`` is always
            split, without a count of the range, which Quick Stats would count as
            ``year__GE`` alone; more years than the ceiling raise ``InvalidRequestError``
            naming it before any call. ``year__GE`` alone is counted first and fetched once
            when the count is within the limit, however far back it starts; over the limit
            it is split, and more years than the ceiling raise ``InvalidRequestError``
            naming it after that count, before the split. A split counts each year with
            ``year=<y>`` in place of the year filters, every year before the first fetch, so
            a year over 50,000 on its own raises ``QueryTooLarge`` naming it before anything
            is fetched; it then fetches each year holding records, the records in year
            order, each year's in upstream's order. A year counting 0 is skipped: it has no
            records, or none published yet, which Quick Stats does not tell apart;
            ``meta.vintage`` stays ``None``, since Quick Stats names no release. Cost: up to
            two keyed calls per year, plus the first count for ``year__GE`` alone, paced at
            30 a minute, so 5 years take up to 11 calls and 20 years up to 41, about 80
            seconds. ``meta.request`` carries ``split_by_year`` beside the filters.
            ``False``, the default, never splits.
    """
    checked = validate_filters(filters)
    years = _years(checked) if split_by_year else None
    request: dict[str, Any] = {**checked, "split_by_year": True} if split_by_year else checked
    if years is not None and "year__LE" in checked:
        # Two-sided: Quick Stats keeps one bound on year per query and would count the
        # range as year__GE alone (recorded 2026-10-28), so it is split without that count.
        return await _split_by_year(checked, years, request)
    count = (await api.get_counts(checked)).count
    if count == 0:
        return Result(data=[], meta=_meta("api_GET", request, total=0))
    if count > RECORD_LIMIT:
        if years is None:
            raise QueryTooLarge(count)
        if "year" in checked:  # one year, already counted: alone over the limit
            raise QueryTooLarge(count, year=years[0])
        return await _split_by_year(checked, years, request)
    response = await api.api_get(checked)
    return Result(data=response.data, meta=_meta("api_GET", request, total=count))


async def list_param_values_async(param: str) -> Result[list[str]]:
    """List every value a Quick Stats filter parameter can take, to form valid queries.

    Nine lists are answered from data packaged with this version, with no upstream call
    (``meta.endpoint`` is ``"get_param_values"``, the operation they were fetched from,
    and ``meta.retrieved_at`` the time they were fetched): ``source_desc``,
    ``sector_desc``, ``group_desc``, ``agg_level_desc``, ``freq_desc``, ``state_alpha``,
    ``statisticcat_desc``, ``unit_desc``, ``domain_desc``. Every other parameter is
    fetched live and cached for 24 hours in this process, so a repeated lookup sends
    nothing; ``meta.retrieved_at`` is the time the cached answer was fetched.

    Args:
        param: A Quick Stats column name, e.g. ``"statisticcat_desc"`` or ``"unit_desc"``
            (packaged), or ``"commodity_desc"``, ``"short_desc"``, ``"county_name"``,
            ``"year"`` (fetched live). Definitions are in
            ``docs/upstream/param_define.md``.
    """
    if param in PACKAGED_PARAMS:
        packaged = PackagedList.load(PACKAGE, param)
        meta = packaged.meta(SOURCE, request={"param": param})
        return Result(data=[record[param] for record in packaged.records], meta=meta)
    values, retrieved_at = await api.get_param_values(param)
    meta = ResultMeta(
        source=SOURCE,
        endpoint="get_param_values",
        request={"param": param},
        retrieved_at=retrieved_at,
    )
    return Result(data=values, meta=meta)


async def _weekly_series(
    statisticcat_desc: str,
    commodity: str,
    year: int,
    state: StateAlpha | None,
    unit_desc: ProgressStage | ConditionCategory | None,
) -> Result[list[CropProgressRecord]]:
    filters = _level(
        state,
        {
            "commodity_desc": commodity,
            "statisticcat_desc": statisticcat_desc,
            "freq_desc": "WEEKLY",
            "year": year,
        },
    )
    if unit_desc is not None:
        filters["unit_desc"] = unit_desc.value
    return await _slice(
        filters,
        CropProgressRecord,
        lambda row: (row.week_ending or date.min, row.unit_desc, row.short_desc),
    )


async def get_crop_progress_async(
    commodity: str,
    year: int,
    *,
    state: StateAlpha | None = None,
    stage: ProgressStage | None = None,
) -> Result[list[CropProgressRecord]]:
    """Weekly crop progress: the percentage planted, emerged, silking, harvested and so on.

    One row per week and stage, from the NASS Crop Progress survey (``statisticcat_desc``
    ``PROGRESS``, ``freq_desc`` ``WEEKLY``), sorted by week. Stages differ by crop;
    ``unit_desc`` names each one and ``value`` is the percentage.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``,
            ``"WINTER WHEAT"``, ``"COTTON"``; ``list_param_values("commodity_desc")``
            lists them.
        year: Crop year, e.g. ``2024``.
        state: Two-letter state code for the state series; ``None`` returns the
            national ``US TOTAL`` series.
        stage: A single stage, e.g. ``ProgressStage.PCT_PLANTED``,
            ``ProgressStage.PCT_SILKING``, ``ProgressStage.PCT_HARVESTED``; the enum
            lists every stage any crop uses, and ``None`` returns every stage of this
            crop.
    """
    return await _weekly_series("PROGRESS", commodity, year, state, stage)


async def get_crop_condition_async(
    commodity: str,
    year: int,
    *,
    state: StateAlpha | None = None,
    category: ConditionCategory | None = None,
) -> Result[list[CropProgressRecord]]:
    """Weekly crop condition: the percentage of a crop rated very poor through excellent.

    One row per week and category, from the NASS Crop Progress survey
    (``statisticcat_desc`` ``CONDITION``, ``freq_desc`` ``WEEKLY``), sorted by week.
    ``unit_desc`` names the category and ``value`` is the percentage.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``,
            ``"WINTER WHEAT"``.
        year: Crop year, e.g. ``2024``.
        state: Two-letter state code for the state series; ``None`` returns the
            national ``US TOTAL`` series.
        category: One of ``ConditionCategory.PCT_VERY_POOR``, ``PCT_POOR``, ``PCT_FAIR``,
            ``PCT_GOOD``, ``PCT_EXCELLENT``; ``None`` returns all five.
    """
    return await _weekly_series("CONDITION", commodity, year, state, category)


async def _county_series(
    statisticcat_desc: str, commodity: str, year: int, state: StateAlpha | None
) -> Result[list[CountyEstimateRecord]]:
    filters: dict[str, str | int] = {
        "commodity_desc": commodity,
        "statisticcat_desc": statisticcat_desc,
        "agg_level_desc": "COUNTY",
        "freq_desc": "ANNUAL",
        "reference_period_desc": "YEAR",
        "year": year,
    }
    if state is not None:
        filters["state_alpha"] = state.value
    return await _slice(
        filters,
        CountyEstimateRecord,
        lambda row: (
            row.state_alpha,
            row.county_name,
            row.util_practice_desc,
            row.prodn_practice_desc,
            row.unit_desc,
        ),
    )


async def get_county_yield_async(
    commodity: str, year: int, *, state: StateAlpha | None = None
) -> Result[list[CountyEstimateRecord]]:
    """County yields of a crop for a year, one row per county, utilisation and practice.

    Annual final estimates (``statisticcat_desc`` ``YIELD``, ``reference_period_desc``
    ``YEAR``) at ``agg_level_desc`` ``COUNTY``, sorted by state, county, utilisation and
    practice. ``unit_desc`` names the unit, ``"BU / ACRE"`` for grain and ``"TONS / ACRE"``
    for silage; ``value`` is the yield.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``, ``"WHEAT"``.
        year: Crop year, e.g. ``2023``. County estimates for a year appear the following
            spring.
        state: Two-letter state code to restrict to one state; ``None`` returns every
            county in the country, which stays under the 50,000-record limit for one crop
            and year.
    """
    return await _county_series("YIELD", commodity, year, state)


async def get_county_production_async(
    commodity: str, year: int, *, state: StateAlpha | None = None
) -> Result[list[CountyEstimateRecord]]:
    """County production of a crop for a year, one row per county, utilisation and practice.

    Annual final estimates (``statisticcat_desc`` ``PRODUCTION``, ``reference_period_desc``
    ``YEAR``) at ``agg_level_desc`` ``COUNTY``, sorted by state, county, utilisation and
    practice. ``unit_desc`` names the unit, ``"BU"`` for grain and ``"TONS"`` for silage;
    ``value`` is the quantity.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``, ``"WHEAT"``.
        year: Crop year, e.g. ``2023``.
        state: Two-letter state code to restrict to one state; ``None`` returns every
            county in the country.
    """
    return await _county_series("PRODUCTION", commodity, year, state)


def _acreage_filters(
    commodity: str, year: int, statistic: AreaStatistic, state: StateAlpha | None
) -> dict[str, str | int]:
    return _level(
        state,
        {
            "commodity_desc": commodity,
            "statisticcat_desc": statistic.value,
            "unit_desc": "ACRES",
            "domain_desc": "TOTAL",
            "prodn_practice_desc": "ALL PRODUCTION PRACTICES",
            "freq_desc": "ANNUAL",
            "year": year,
        },
    )


async def get_acreage_async(
    commodity: str,
    year: int,
    statistic: AreaStatistic,
    *,
    state: StateAlpha | None = None,
) -> Result[list[AcreageRecord]]:
    """Planted or harvested acreage of a crop for a year, state or national, in acres.

    Annual final totals (``unit_desc`` ``ACRES``, ``domain_desc`` ``TOTAL``,
    ``prodn_practice_desc`` ``ALL PRODUCTION PRACTICES``, ``reference_period_desc``
    ``YEAR``), so breakdowns by size group, irrigation or biotech type and the in-season
    forecasts are left out; ``get_acreage_forecasts`` serves the latter. Harvested
    acreage comes per utilisation (grain, silage); planted acreage as one figure.
    Sorted by state, utilisation and source.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``, ``"WHEAT"``.
        year: Crop year, e.g. ``2023``.
        statistic: ``AreaStatistic.AREA_PLANTED`` or ``AreaStatistic.AREA_HARVESTED``.
        state: Two-letter state code for the state figure; ``None`` returns the national
            ``US TOTAL`` figure.
    """
    filters = _acreage_filters(commodity, year, statistic, state)
    filters["reference_period_desc"] = "YEAR"
    return await _slice(
        filters,
        AcreageRecord,
        lambda row: (row.state_alpha, row.util_practice_desc, row.source_desc),
    )


async def get_acreage_forecasts_async(
    commodity: str,
    year: int,
    statistic: AreaStatistic,
    *,
    state: StateAlpha | None = None,
) -> Result[list[AcreageRecord]]:
    """The in-season acreage reports for a crop and year, in acres, oldest first.

    Every report except the final figure: the March prospective plantings, the June
    acreage report and the monthly forecasts, each row naming its
    ``reference_period_desc`` (``YEAR - JUN ACREAGE``, ``YEAR - AUG FORECAST``, ...).
    Same fixed filters as ``get_acreage`` otherwise, so the series is comparable with
    the final figure. Sorted by ``load_time``, then utilisation.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``, ``"WHEAT"``.
        year: Crop year, e.g. ``2023``.
        statistic: ``AreaStatistic.AREA_PLANTED`` or ``AreaStatistic.AREA_HARVESTED``.
        state: Two-letter state code for the state series; ``None`` returns the national
            series.
    """
    filters = _acreage_filters(commodity, year, statistic, state)
    filters["reference_period_desc__NE"] = "YEAR"
    return await _slice(
        filters,
        AcreageRecord,
        lambda row: (row.load_time, row.util_practice_desc, row.source_desc),
    )


async def get_prices_received_async(
    commodity: str,
    year: int,
    *,
    state: StateAlpha | None = None,
    frequency: FreqDesc | None = None,
) -> Result[list[PriceReceivedRecord]]:
    """Prices farmers received for a commodity in a year, monthly and marketing-year.

    ``statisticcat_desc`` ``PRICE RECEIVED`` at ``domain_desc`` ``TOTAL``, state or
    national, sorted by frequency and period: the marketing-year average first, then
    the months. The national series also carries the price as a percentage of parity
    (``unit_desc`` ``"PCT OF PARITY"``) next to the dollar price; the column tells them
    apart.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``, ``"MILK"``,
            ``"CATTLE"``.
        year: Calendar year of the months, e.g. ``2023``.
        state: Two-letter state code for the state series; ``None`` returns the
            national series.
        frequency: ``FreqDesc.MONTHLY`` or ``FreqDesc.ANNUAL`` to keep one; ``None``
            returns both.
    """
    filters = _level(
        state,
        {
            "commodity_desc": commodity,
            "statisticcat_desc": "PRICE RECEIVED",
            "domain_desc": "TOTAL",
            "year": year,
        },
    )
    if frequency is not None:
        filters["freq_desc"] = frequency.value
    return await _slice(
        filters,
        PriceReceivedRecord,
        lambda row: (row.freq_desc, row.begin_code, row.unit_desc),
    )


async def get_grain_stocks_async(
    commodity: str, year: int, *, state: StateAlpha | None = None
) -> Result[list[GrainStocksRecord]]:
    """Quarterly grain stocks of a commodity in a year, on farm, off farm and in total, in bushels.

    The NASS Grain Stocks estimates (``statisticcat_desc`` ``STOCKS``, ``unit_desc``
    ``BU``, ``domain_desc`` ``TOTAL``, ``freq_desc`` ``POINT IN TIME``, ``source_desc``
    ``SURVEY``), state or national, every stocks day of the year together: one row per
    day, position and class, sorted by day (``begin_code``, then
    ``reference_period_desc``), then ``util_practice_desc``, then ``class_desc``.
    ``reference_period_desc`` names the day, ``FIRST OF MAR``, ``FIRST OF JUN``,
    ``FIRST OF SEP`` or ``FIRST OF DEC``, and ``begin_code`` its month (``03`` ... ``12``).
    ``util_practice_desc`` tells the position as upstream spells it for the commodity:
    for corn ``GRAIN`` (the total), ``ON FARM, GRAIN`` and ``OFF FARM, GRAIN``; for
    soybeans and wheat ``ALL UTILIZATION PRACTICES`` (the total), ``ON FARM`` and
    ``OFF FARM``. ``class_desc`` is ``ALL CLASSES``; wheat's durum comes as rows of its
    own, ``class_desc`` ``SPRING, DURUM``, where NASS publishes it, as in the national
    estimates. ``value`` is the quantity in bushels as published and ``value_number`` its
    parsed form.

    Args:
        commodity: Upstream ``commodity_desc``, e.g. ``"CORN"``, ``"SOYBEANS"``,
            ``"WHEAT"``; ``list_param_values("commodity_desc")`` lists them.
        year: Year of the stocks days, e.g. ``2024`` for the stocks on 1 March, 1 June,
            1 September and 1 December 2024.
        state: Two-letter state code for the state estimates, e.g. ``"IA"``, ``"ND"``;
            ``None`` returns the national ``US TOTAL`` estimates.
    """
    filters = _level(
        state,
        {
            "commodity_desc": commodity,
            "statisticcat_desc": "STOCKS",
            "unit_desc": "BU",
            "domain_desc": "TOTAL",
            "freq_desc": "POINT IN TIME",
            "source_desc": "SURVEY",
            "year": year,
        },
    )
    return await _slice(
        filters,
        GrainStocksRecord,
        lambda row: (
            row.begin_code,
            row.reference_period_desc,
            row.util_practice_desc,
            row.class_desc,
        ),
    )


get_counts = sync(get_counts_async)
get_data = sync(get_data_async)
list_param_values = sync(list_param_values_async)
get_crop_progress = sync(get_crop_progress_async)
get_crop_condition = sync(get_crop_condition_async)
get_county_yield = sync(get_county_yield_async)
get_county_production = sync(get_county_production_async)
get_acreage = sync(get_acreage_async)
get_acreage_forecasts = sync(get_acreage_forecasts_async)
get_prices_received = sync(get_prices_received_async)
get_grain_stocks = sync(get_grain_stocks_async)
