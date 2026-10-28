"""Task functions, the public API: the adapters serve ``__all__`` (conventions §2).

``/add-endpoint`` adds them.

``meta.published_at`` stays empty: Quick Stats publishes no release time, and the
per-row ``load_time`` carries no zone. Reading one into it would be a guess; that
belongs to the normalisation layer, not here.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

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
from xippios.usda.nass.errors import RECORD_LIMIT, QueryTooLarge
from xippios.usda.nass.models import (
    AcreageRecord,
    AreaStatistic,
    CountyEstimateRecord,
    CropProgressRecord,
    Filters,
    PriceReceivedRecord,
    QuickStatsRecord,
)
from xippios.usda.nass.params import PACKAGE, PACKAGED_PARAMS, validate_filters

__all__ = [
    "get_acreage",
    "get_acreage_forecasts",
    "get_counts",
    "get_county_production",
    "get_county_yield",
    "get_crop_condition",
    "get_crop_progress",
    "get_data",
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

``list_param_values`` is the reference lookup an agent needs whole to form valid filters:
lists fetched live run past the family's default of 200 rows (``statisticcat_desc`` has
278 values, 5,411 bytes of compact JSON, recorded 2026-10-22), while every packaged list
has fewer than 60. Its cap keeps the default 64 KB, and its note promises no filter, since
the tool has none. Every other tool keeps the default, 200 rows or 64 KB, with core's
note.
"""


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
            counts corn records for Virginia from 2012 on.
    """
    checked = validate_filters(filters)
    response = await api.get_counts(checked)
    return Result(data=response.count, meta=_meta("get_counts", checked, total=response.count))


_BOUNDED_FORMS = (
    "year (one year, e.g. 2022), year__GE with year__LE (e.g. 2020 and 2023), or "
    "year__GE alone (up to the current UTC year)"
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
            bound is not a whole year, or the range holds no year.
    """
    keys = sorted(key for key in filters if _is_year(key))
    if keys == ["year"]:
        first = last = _year(filters, "year")
    elif keys == ["year__GE", "year__LE"]:
        first, last = _year(filters, "year__GE"), _year(filters, "year__LE")
    elif keys == ["year__GE"]:
        first, last = _year(filters, "year__GE"), datetime.now(UTC).year
    else:
        given = ", ".join(keys) if keys else "none"
        raise InvalidRequestError(
            f"split_by_year needs the years bounded in one of three forms: {_BOUNDED_FORMS}; "
            f"year filters given: {given}.",
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
    """
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

    Calls ``get_counts`` first: a count of zero returns an empty result without a second
    call, and a count above 50,000 raises ``QueryTooLarge`` with the count and a hint to
    narrow, before anything is fetched, unless ``split_by_year`` is set. ``meta.total``
    is the count ``get_counts`` reported, ``0`` for the empty result, and the yearly
    counts summed for a split. Each record carries every Quick Stats column; ``value``
    is the published figure as a string (``"510,000"``, or a suppression code such as
    ``"(D)"``) and ``value_number`` the parsed number.

    Args:
        filters: Quick Stats columns, optionally suffixed with an operator, mapped to
            values; the same shape and the same checks as for ``get_counts``: an
            unknown value of a packaged parameter raises ``UnknownCode`` naming the
            list, its fetch date and the closest known values, or pointing at
            ``list_param_values`` (the tool ``usda_nass_list_param_values``) when none
            is close. A query that stays well under the limit names the commodity, the
            statistic, the level and the time, e.g.
            ``{"commodity_desc": "CORN", "statisticcat_desc": "AREA PLANTED",
            "agg_level_desc": "STATE", "state_alpha": "VA", "year": 2012}``.
        split_by_year: ``True`` fetches a query over the 50,000-record limit one year at
            a time; a count within the limit is still fetched in one call. The filters
            must bound the years in one of three forms, checked before any call:
            ``year`` (``2022``), ``year__GE`` with ``year__LE`` (``2020`` and ``2023``),
            or ``year__GE`` alone, up to the current UTC year; another year filter
            (``year__LE`` alone, ``year__GT``, ``year__NE``, ...), a mix or none raises
            ``InvalidRequestError`` naming the three forms. Each year is counted with
            ``year=<y>`` in place of the year filters, then each year holding records
            is fetched; the records come in year order, each year's in upstream's
            order. A year over 50,000 on its own raises ``QueryTooLarge`` naming it,
            before anything is fetched. Cost: two keyed calls per year after the first
            count, paced at 30 a minute, so ten years take up to 21 calls. Quick Stats
            counted ``year__GE`` with ``year__LE`` as ``year__GE`` alone (2026-10-28),
            so for that form the first count, and the one fetch when it is within the
            limit, cover the years from ``year__GE`` on, while a split stops at
            ``year__LE``. ``meta.request`` carries ``split_by_year`` beside the filters.
            ``False``, the default, never splits.
    """
    checked = validate_filters(filters)
    years = _years(checked) if split_by_year else None
    request: dict[str, Any] = {**checked, "split_by_year": True} if split_by_year else checked
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

    Six small, stable lists are answered from data packaged with this version, with no
    upstream call (``meta.endpoint`` is ``"get_param_values"``, the operation they were
    fetched from, and ``meta.retrieved_at`` the time they were fetched): ``source_desc``,
    ``sector_desc``, ``group_desc``, ``agg_level_desc``, ``freq_desc``, ``state_alpha``.
    Every other parameter is fetched live.

    Args:
        param: A Quick Stats column name. Large lists worth fetching live:
            ``"commodity_desc"``, ``"statisticcat_desc"``, ``"short_desc"``,
            ``"county_name"``, ``"year"``. Definitions are in
            ``docs/upstream/param_define.md``.
    """
    if param in PACKAGED_PARAMS:
        packaged = PackagedList.load(PACKAGE, param)
        meta = packaged.meta(SOURCE, request={"param": param})
        return Result(data=[record[param] for record in packaged.records], meta=meta)
    values = await api.get_param_values(param)
    meta = ResultMeta(source=SOURCE, endpoint="get_param_values", request={"param": param})
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
