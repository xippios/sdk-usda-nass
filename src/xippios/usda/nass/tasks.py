"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them. Core builds the server from this module, which declares what
the server holds beside its tools: ``MCP_INSTRUCTIONS``, ``MCP_CAPS`` and the two option
hooks (conventions §8, sdk-core ADR-0063, decision 7).

``meta.published_at`` stays empty: Quick Stats publishes no release time, and the
per-row ``load_time`` carries no zone. Reading one into it would be a guess; that
belongs to the normalisation layer, not here.

``get_data(split_by_year=True)`` splits one call into at most ``SPLIT.value`` years, a
core ``Ceiling`` (sdk-core ADR-0054): ``SPLIT_CEILING`` (20) in Python and over HTTP; the
MCP server starts with ``MCP_SPLIT_YEARS`` (11), and its ``--split-years`` sets another
ceiling from 1 to 20 through the ceiling's option hooks (``mcp_add_options``,
``mcp_apply_options``). The entry point ``xippios-usda-nass-mcp`` sets the MCP ceiling,
since core's ``main`` applies the option, and so does a host that serves
``xippios.usda.nass.mcp.build()`` and applies its hooks with the tool set's
``option_defaults()``; a host that serves ``xippios.usda.nass.mcp.server`` without them
keeps 20. The ceiling is process-wide: a Python or HTTP call made in the MCP server's
process meets the MCP ceiling too.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from xippios.core import (
    Ceiling,
    InvalidRequestError,
    PackagedList,
    Result,
    ResultCap,
    ResultMeta,
    fetch_counted,
    fetch_periods,
    sync,
)
from xippios.core import QueryTooLarge as CoreQueryTooLarge

from xippios.usda.nass import api
from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.errors import (
    MCP_SPLIT_YEARS,
    NARROW,
    RECORD_LIMIT,
    SPLIT_CEILING,
    QueryTooLarge,
)
from xippios.usda.nass.models import Filters, QuickStatsRecord
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS, validate_filters

__all__ = ["count_data", "get_data", "list_param_values"]

# A task named here is Python-only: no tool, no route; the adapters skip it (sdk-core ADR-0040,
# decision 4).
BULK_TASKS: frozenset[str] = frozenset()

MCP_INSTRUCTIONS = (
    "USDA NASS Quick Stats via xippios. "
    "Tools are read-only. "
    "Where list tools (usda_nass_list_*) exist, call them first to find valid values, "
    "then query."
)
"""The read server's instructions for agents, which core's tool set reads from here."""

MCP_CAPS: Mapping[str, ResultCap] = {
    "list_param_values": ResultCap(
        max_rows=1000,
        note=(
            "a value past the cap is still accepted as a filter value by "
            "usda_nass_count_data and usda_nass_get_data"
        ),
        paged=True,
    ),
}
"""MCP result caps of their own, by task function name (conventions §8, sdk-core ADR-0038).

``list_param_values`` is the reference lookup an agent needs whole to form valid filters,
and its lists run past the family's default of 200 rows. Of the nine packaged lists
(fetched 2026-10-28), ``statisticcat_desc`` has 278 values, ``unit_desc`` 373 and
``domain_desc`` 616 (22,194 bytes of compact JSON, the largest), the other six fewer than
60; lists fetched live run longer too (``commodity_desc`` has 467 values, 6,773 bytes,
recorded 2026-10-28). Its cap keeps the default 64 KB.

Its cap is paged (sdk-core ADR-0047): the tool takes core's ``offset``, the rows already
shown, the task runs again and the note of a cut answer ends with the call for the next
rows. A second run sends upstream nothing, since nine lists are packaged and the client
keeps every other for a day (ADR-0061, decision 9). ``get_data`` stays unpaged: a
continuation would send its count and its data again, and its answer can pass the cache's
bound. Every other tool keeps the default, 200 rows or 64 KB, with core's note.
"""

SPLIT = Ceiling(
    SPLIT_CEILING,
    unit="years",
    mcp=MCP_SPLIT_YEARS,
    option="--split-years",
    help=(
        f"usda_nass_get_data with split_by_year, up to two keyed calls a year, so "
        f"{MCP_SPLIT_YEARS} years take at most {2 * MCP_SPLIT_YEARS + 1} calls"
    ),
    source=SOURCE,
)
"""The most years one ``get_data(split_by_year=True)`` call splits into (conventions §4).

``SPLIT_CEILING`` (20) in Python and over HTTP, ``SPLIT.value`` the ceiling in force: the
entry point ``xippios-usda-nass-mcp`` starts the MCP server with ``MCP_SPLIT_YEARS`` (11),
and its ``--split-years`` sets another from 1 to 20 through the tool set's two hooks below
(sdk-core ADR-0054). The setting is process-wide, so every split in the process meets the
same ceiling, from Python, over HTTP or over MCP: one MCP server per process.
"""

mcp_add_options = SPLIT.add_options
"""Add ``--split-years YEARS`` to the MCP server's command line, a hook of core's ``main``."""

mcp_apply_options = SPLIT.apply_options
"""Set the split ceiling from ``--split-years``, a hook of core's ``main`` under its signature,
``mcp_apply_options(namespace) -> None``; a value outside 1 to 20 raises
``InvalidRequestError``, which ``main`` turns into exit status 2."""


def _meta(
    endpoint: str,
    request: dict[str, Any],
    retrieved: Sequence[datetime],
    *,
    total: int | None = None,
) -> ResultMeta:
    """The envelope, retrieved at the oldest of the call's answers (conventions §4).

    ``retrieved`` holds the ``retrieved_at`` of each answer the call read; empty for none,
    where core stamps the time the result is built.
    """
    if not retrieved:
        return ResultMeta(source=SOURCE, endpoint=endpoint, request=request, total=total)
    return ResultMeta(
        source=SOURCE,
        endpoint=endpoint,
        request=request,
        total=total,
        retrieved_at=min(retrieved),
    )


async def count_data_async(filters: Filters) -> Result[int]:
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
    answer = await api.get_counts(checked)
    count = answer.payload.count
    return Result(data=count, meta=_meta("get_counts", checked, [answer.retrieved_at], total=count))


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
            f"split_by_year: {key}={value!r} is not a year. Nothing was sent. Give a whole "
            "year, e.g. 2022.",
            source=SOURCE,
        ) from None


def _years(filters: Mapping[str, str | int]) -> range:
    """The years ``split_by_year`` queries one by one, read from the year filters.

    Raises:
        InvalidRequestError: The year filters are none of the three bounded forms, a
            bound is not a whole year, a ``year__GE`` or ``year__LE`` is past the current
            UTC year, or the range holds no year; before any request, so each refusal
            says that nothing was sent.
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
            f"year filters given: {given}. Nothing was sent.",
            source=SOURCE,
        )
    for key in ("year__LE", "year__GE"):
        if key in keys and (bound := _year(filters, key)) > now:
            raise InvalidRequestError(
                f"split_by_year: {key}={bound} is past the current UTC year, {now}. Nothing "
                f"was sent. The range must end by {now}.",
                source=SOURCE,
            )
    if first > last:
        raise InvalidRequestError(
            f"split_by_year: the years run from {first} to {last}, a range without a year. "
            "Nothing was sent.",
            source=SOURCE,
        )
    return range(first, last + 1)


def _refuse_after_the_count(years: range) -> None:
    """Refuse a split of ``year__GE`` alone over the ceiling, after its count of the range.

    Core's ``SPLIT.check`` says that nothing was sent, which holds before any request of the
    call, as for a two-sided range; ``year__GE`` alone is counted first and split only over
    the limit, so its refusal is worded here, without that sentence (sdk-core ADR-0054,
    amendment 2026-11-22).

    Raises:
        InvalidRequestError: ``years`` holds more than ``SPLIT.value`` years.
    """
    ceiling = SPLIT.value
    if len(years) <= ceiling:
        return
    first, last = years[0], years[-1]
    bound = f"split_by_year covers at most {ceiling} years per call"
    if ceiling < SPLIT.most:
        bound += (
            f", the ceiling set for this process (the MCP server starts with {SPLIT.mcp} by "
            f"default; {SPLIT.option} raises it, up to {SPLIT.most})"
        )
    raise InvalidRequestError(
        f"{bound}; the years run from {first} to {last}, {len(years)} years. Give a "
        f"shorter range, e.g. year__GE={last - ceiling + 1} with year__LE={last}.",
        source=SOURCE,
    )


async def _split_by_year(
    filters: dict[str, str | int], years: range, request: dict[str, Any], *, counted: bool
) -> Result[list[QuickStatsRecord]]:
    """Count every year of ``years``, then fetch the years that hold records, in year order.

    Each year's query is ``filters`` with ``year=<y>`` in place of the year filters. Both
    passes go through core's ``fetch_periods``: every year is counted before the first
    fetch, so a year over the limit raises ``QueryTooLarge`` naming it before anything is
    fetched; a year counting 0 is not fetched. A request after the first that fails
    raises its error, its message naming the years answered before it, and returns
    nothing. ``meta.total`` is the yearly counts summed, and ``meta.retrieved_at`` the
    oldest answer's time.

    Args:
        filters: The checked filters, their year filters among them.
        years: The years to split into, from ``_years``.
        request: What ``meta.request`` records.
        counted: ``True`` where the range was counted first, ``year__GE`` alone over the
            limit, so its refusal over the ceiling comes after that count; ``False`` for a
            two-sided range, refused by core's check before any request.

    Raises:
        InvalidRequestError: ``years`` holds more than ``SPLIT.value`` years, the most one
            call splits into (conventions §4); raised before the first yearly count.
            Below ``SPLIT_CEILING`` the refusal calls it the ceiling set for this process
            and names the MCP server's default and ``--split-years``.
        QueryTooLarge: A year alone is over the limit.
    """
    if counted:
        _refuse_after_the_count(years)
    else:
        first, last = years[0], years[-1]
        start = last - min(len(years), SPLIT.value) + 1
        SPLIT.check(
            len(years),
            asked=f"split_by_year from {first} to {last}",
            advice=f"Give a shorter range, e.g. year__GE={start} with year__LE={last}.",
        )
    rest = {key: value for key, value in filters.items() if not _is_year(key)}
    retrieved: list[datetime] = []

    def chunk(year: int) -> dict[str, str | int]:
        return {**rest, "year": year}

    async def count(year: int) -> int:
        answer = await api.get_counts(chunk(year))
        retrieved.append(answer.retrieved_at)
        if answer.payload.count > RECORD_LIMIT:
            raise QueryTooLarge(answer.payload.count, year=year)
        return answer.payload.count

    async def fetch(year: int) -> list[QuickStatsRecord]:
        answer = await api.api_get(chunk(year))
        retrieved.append(answer.retrieved_at)
        return answer.payload.data

    counts = await fetch_periods(years, count)
    fetched = await fetch_periods([year for year, number in counts if number], fetch)
    data = [record for _, records in fetched for record in records]
    total = sum(number for _, number in counts)
    return Result(data=data, meta=_meta("api_GET", request, retrieved, total=total))


async def get_data_async(
    filters: Filters, *, split_by_year: bool = False
) -> Result[list[QuickStatsRecord]]:
    """Fetch published Quick Stats estimates for a set of filters, up to 50,000 records a call.

    Counts the records first: a count of 0 returns an empty result without a second call,
    and a count above 50,000 raises ``QueryTooLarge`` with the count and a hint before
    anything is fetched. For one ``year``, a zero may be a year without records or one not
    yet published: Quick Stats names no release. ``meta.total`` is the count ``count_data``
    reported, the yearly counts summed for a split. Each record carries every Quick Stats
    column; ``value`` is the published figure as a string (``"510,000"``, or a suppression
    code such as ``"(D)"``) and ``value_number`` the parsed number. ``split_by_year`` fetches
    a range that one call cannot serve year by year, as its argument says.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values; the same shape and the same checks as for ``count_data``: an
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
            them, splitting one call into at most 20 years in Python and over HTTP and 11
            by default on the MCP server, whose ``--split-years`` sets 1 to 20. The filters
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
            order, each year's in upstream's order. A request after the first that fails
            raises its error naming the years answered before it, and the call returns
            nothing. A year counting 0 is skipped: it has no records, or none published
            yet, which Quick Stats does not tell apart; ``meta.vintage`` stays ``None``,
            since Quick Stats names no release. Cost: up to two keyed calls per year, plus
            the first count for ``year__GE`` alone, paced at 30 a minute, so 11 years take
            up to 23 calls and 20 years up to 41, about 80 seconds. ``meta.request``
            carries ``split_by_year`` beside the filters. ``False``, the default, never
            splits.
    """
    checked = validate_filters(filters)
    years = _years(checked) if split_by_year else None
    request: dict[str, Any] = {**checked, "split_by_year": True} if split_by_year else checked
    if years is not None and "year__LE" in checked:
        # Two-sided: Quick Stats keeps one bound on year per query and would count the
        # range as year__GE alone (recorded 2026-10-28), so it is split without that count.
        return await _split_by_year(checked, years, request, counted=False)
    retrieved: list[datetime] = []

    async def count() -> int:
        answer = await api.get_counts(checked)
        retrieved.append(answer.retrieved_at)
        return answer.payload.count

    async def fetch() -> list[QuickStatsRecord]:
        answer = await api.api_get(checked)
        retrieved.append(answer.retrieved_at)
        return answer.payload.data

    try:
        data, total = await fetch_counted(
            count, fetch, limit=RECORD_LIMIT, empty=[], narrow=NARROW, source=SOURCE
        )
    except CoreQueryTooLarge as refused:
        if refused.count is None:  # upstream's HTTP 413 from the data request, as raised
            raise
        if years is None:
            raise QueryTooLarge(refused.count) from None
        if "year" in checked:  # one year, already counted: alone over the limit
            raise QueryTooLarge(refused.count, year=years[0]) from None
        return await _split_by_year(checked, years, request, counted=True)
    return Result(data=data, meta=_meta("api_GET", request, retrieved, total=total))


async def list_param_values_async(param: str) -> Result[list[str]]:
    """List every value a Quick Stats filter parameter can take, to form valid queries.

    Nine lists are answered from data packaged with this version, with no upstream call
    (``meta.endpoint`` is ``"get_param_values"``, the operation they were fetched from,
    and ``meta.retrieved_at`` the time they were fetched): ``source_desc``,
    ``sector_desc``, ``group_desc``, ``agg_level_desc``, ``freq_desc``, ``state_alpha``,
    ``statisticcat_desc``, ``unit_desc``, ``domain_desc``. Every other parameter is
    fetched live and kept for a day in this process, so a repeated lookup sends
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
    answer = await api.get_param_values(param)
    meta = ResultMeta(
        source=SOURCE,
        endpoint="get_param_values",
        request={"param": param},
        retrieved_at=answer.retrieved_at,
    )
    return Result(data=answer.payload, meta=meta)


count_data = sync(count_data_async)
get_data = sync(get_data_async)
list_param_values = sync(list_param_values_async)
