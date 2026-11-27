"""Packaged Quick Stats parameter lists and column definitions (conventions §3).

Nine parameter lists ship inside the package so the common lookups need no network
call and ``validate_filters`` refuses a value they lack before one, and the column table
from ``docs/upstream/param_define.md`` ships as ``columns.csv``. Files are produced by
``scripts/refresh_reference.py`` (``/refresh-reference-data``), never by hand, and a list
is read with ``PackagedList.load(PACKAGE, name)`` and checked through its declaration,
``codes(name)``; ``reference/README.md`` carries the provenance. ``columns.csv`` is read
by ``load_table``, the package's own since core 0.5.0 left it to its one consumer
(https://github.com/xippios/sdk-core/issues/473).
"""

import csv
import difflib
import functools
import io
from importlib import resources
from typing import Any

import pydantic
from pydantic import Field, TypeAdapter, field_validator
from xippios.core import (
    InvalidRequestError,
    PackagedCodes,
    PackagedList,
    UpstreamModel,
    ValidationError,
    load_json,
)

from xippios.usda.nass._client import SOURCE
from xippios.usda.nass.models import Filters

__all__ = [
    "OPERATORS",
    "PACKAGED_PARAMS",
    "Column",
    "codes",
    "columns",
    "validate_filters",
]

OPERATORS: tuple[str, ...] = ("LE", "LT", "GT", "GE", "LIKE", "NOT_LIKE", "NE")
"""Suffixes a filter key may carry after ``__``, as ``docs/upstream/api.md`` lists them."""

PACKAGE = "xippios.usda.nass"

PACKAGED_PARAMS: tuple[str, ...] = (
    "source_desc",
    "sector_desc",
    "group_desc",
    "agg_level_desc",
    "freq_desc",
    "state_alpha",
    "statisticcat_desc",
    "unit_desc",
    "domain_desc",
)
"""Parameters whose value lists ship inside the package."""


class Column(UpstreamModel):
    """One row of ``reference/columns.csv``: a Quick Stats column as ``param_define.md`` defines it.

    Attributes:
        column: Column name, usable as a filter key.
        dimension: The What, Where, When or Data Value dimension heading it sits under.
        max_length: Maximum length upstream documents for the value.
        definition: Upstream's definition text.
    """

    column: str
    dimension: str
    max_length: int | None = Field(default=None)
    definition: str

    @field_validator("max_length", mode="before")
    @classmethod
    def _empty_is_none(cls, raw: object) -> object:
        return None if raw == "" else raw


def load_csv(package: str, name: str) -> list[dict[str, str]]:
    """Rows of a packaged CSV file as dicts keyed by the header row.

    Copied from xippios-core 0.4.1's ``reference.py``, which 0.5.0 left to this package,
    its one consumer (https://github.com/xippios/sdk-core/issues/473).

    Args:
        package: Import path of the source package, e.g. ``"xippios.usda.nass"``.
        name: File name under ``reference/``, e.g. ``"columns.csv"``.

    Raises:
        FileNotFoundError: The package ships no such file.
    """
    path = resources.files(package).joinpath("reference", name)
    if not path.is_file():
        raise FileNotFoundError(f"reference file {name!r} not found in package {package!r}")
    return [dict(row) for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))]


def load_table[T](package: str, name: str, model: type[T]) -> list[T]:
    """Rows of a packaged CSV or JSON file validated into ``model`` instances.

    Copied from xippios-core 0.4.1's ``reference.py`` with ``load_csv``. The format is
    chosen by extension: ``.csv`` rows are strings coerced by the model, ``.json`` must
    hold a list of objects.

    Args:
        package: Import path of the source package, e.g. ``"xippios.usda.nass"``.
        name: File name under ``reference/``, e.g. ``"columns.csv"``.
        model: The row model, e.g. ``Column``.

    Raises:
        ValidationError: A row does not fit ``model``, naming the package, the file and
            the first failure's location and message, the rows on ``raw``.
    """
    raw: Any = load_csv(package, name) if name.endswith(".csv") else load_json(package, name)
    try:
        return TypeAdapter(list[model]).validate_python(raw)  # type: ignore[valid-type]
    except pydantic.ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        message = f"{package} reference/{name}: {where}: {first['msg']}"
        raise ValidationError(message, raw=raw, source=SOURCE) from None


def columns() -> list[Column]:
    """Every Quick Stats column, from the packaged ``columns.csv``."""
    return load_table(PACKAGE, "columns.csv", Column)


@functools.cache
def _column_names() -> frozenset[str]:
    return frozenset(column.column for column in columns())


@functools.cache
def codes(param: str) -> PackagedCodes:
    """The packaged list of ``param``, declared once per process with core's check (§5).

    Each value stands for itself, so the list has no name field, and its values are
    compared without regard to case, as Quick Stats compares them (``state_alpha=va``
    counts what ``VA`` counts, ``get_counts/corn_va_since_2012_lowercase`` recorded
    2026-10-28).

    Args:
        param: One of ``PACKAGED_PARAMS``, e.g. ``"state_alpha"``.
    """
    return PackagedList.load(PACKAGE, param).codes(param, fold_case=True, source=SOURCE)


_REASON = (
    "Quick Stats ignores case but counts no records for a value it does not know, the "
    "answer a query without data gets, so the package refuses it before the call."
)


def validate_filters(filters: Filters) -> dict[str, str | int]:
    """Check the filters against the packaged column table and lists before calling upstream.

    Quick Stats ignores unknown column names, so a misspelt key would silently query the
    whole database, and counts no records for an unknown value, the answer a query
    without data gets. A key is ``<column>`` or ``<column>__<OPERATOR>``. The value of a
    bare key that names a packaged parameter (``PACKAGED_PARAMS``) must be in its
    packaged list, compared without regard to case as Quick Stats compares it; a key
    with an operator is checked as a key only. Every value is sent as given.

    Args:
        filters: The query parameters as the caller gave them.

    Returns:
        The filters as a plain dict, unchanged.

    Raises:
        InvalidRequestError: Naming every unknown column, with the closest valid names,
            and every unknown operator, then that nothing was sent; or, when the keys are
            known, for a packaged parameter given an integer, since every packaged list
            holds text: core's check names the text codes to pass.
        UnknownCode: When the keys are known, for the first packaged parameter whose
            value its packaged list lacks, naming the list, its fetch date, that nothing
            was sent and the closest known values, or pointing at ``list_param_values``
            (the MCP tool ``usda_nass_list_param_values``) when none is close.
    """
    known = _column_names()
    problems: list[str] = []
    for key in filters:
        column, _, operator = key.partition("__")
        if column not in known:
            close = difflib.get_close_matches(column, sorted(known), n=3)
            hint = f"; did you mean {', '.join(close)}?" if close else ""
            problems.append(f"{key!r} is not a Quick Stats column{hint}")
        elif operator and operator not in OPERATORS:
            allowed = ", ".join(f"__{op}" for op in OPERATORS)
            problems.append(f"{key!r}: unknown operator {operator!r}; use one of {allowed}")
    if problems:
        raise InvalidRequestError(
            "; ".join(problems)
            + ". Nothing was sent. Columns are defined in docs/upstream/param_define.md.",
            source=SOURCE,
        )
    for key, value in filters.items():
        if key in PACKAGED_PARAMS:
            # The caller's spelling is sent; the refusal names the closest known values in
            # their canonical spelling, or points at the list's lookup when none is close.
            codes(key).check(
                key,
                value,
                otherwise=(
                    f"list_param_values({key!r}) lists the known values (over MCP, the tool "
                    "usda_nass_list_param_values)."
                ),
                reason=_REASON,
            )
    return dict(filters)
