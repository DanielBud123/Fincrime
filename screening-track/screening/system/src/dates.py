"""The one date reader.

Every file writes dates differently: ``2026-11-06``, ``19/05/2004`` (always
day first in this bank's data), ``February 19, 2002``, ``19 May 2004``,
``1996`` or ``1962-09``. Everything downstream reads dates through this module
so that partial dates stay partial ("unknown stays unknown").

A date is a :class:`PartialDate` with a year and optional month and day. Its
ISO form is ``"1985"``, ``"1985-03"`` or ``"1985-03-12"``.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from typing import Iterable, Optional

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

MIN_YEAR, MAX_YEAR = 1800, 2100


@dataclass(frozen=True, order=True)
class PartialDate:
    year: int
    month: Optional[int] = None
    day: Optional[int] = None

    def iso(self) -> str:
        if self.month is None:
            return f"{self.year:04d}"
        if self.day is None:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.iso()

    @property
    def is_full(self) -> bool:
        return self.month is not None and self.day is not None


def _make(year, month=None, day=None) -> Optional[PartialDate]:
    try:
        year = int(year)
        month = int(month) if month is not None else None
        day = int(day) if day is not None else None
    except (TypeError, ValueError):
        return None
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    if month is not None and not (1 <= month <= 12):
        return None
    if day is not None:
        if month is None:
            return None
        if not (1 <= day <= calendar.monthrange(year, month)[1]):
            return None
    return PartialDate(year, month, day)


# One combined pattern. Alternatives are tried in this order at each position,
# so the most specific shape wins and a bare year is never read out of a
# longer date. ``(?<![\d/.-])`` guards keep us from starting mid-number.
_DATE_RE = re.compile(
    r"(?<![\d/.-])(?:"
    r"(?P<iso_y>\d{4})-(?P<iso_m>\d{1,2})-(?P<iso_d>\d{1,2})"
    r"|(?P<ym_y>\d{4})-(?P<ym_m>\d{2})"
    r"|(?P<dmy_d>\d{1,2})[/.-](?P<dmy_m>\d{1,2})[/.-](?P<dmy_y>\d{4})"
    r"|(?P<mdy_mon>" + _MONTH_RE + r")\.?\s+(?P<mdy_d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<mdy_y>\d{4})"
    r"|(?P<dmy2_d>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<dmy2_mon>" + _MONTH_RE + r")\.?,?\s+(?P<dmy2_y>\d{4})"
    r"|(?P<my_mon>" + _MONTH_RE + r")\.?,?\s+(?P<my_y>\d{4})"
    r"|(?P<y>(?:18|19|20)\d{2})"
    r")(?![\d/-])(?![.]\d)",
    re.IGNORECASE,
)


def _from_match(m: re.Match) -> Optional[PartialDate]:
    g = m.groupdict()
    if g["iso_y"]:
        return _make(g["iso_y"], g["iso_m"], g["iso_d"])
    if g["ym_y"]:
        return _make(g["ym_y"], g["ym_m"])
    if g["dmy_y"]:
        return _make(g["dmy_y"], g["dmy_m"], g["dmy_d"])
    if g["mdy_y"]:
        return _make(g["mdy_y"], MONTHS[g["mdy_mon"].lower()], g["mdy_d"])
    if g["dmy2_y"]:
        return _make(g["dmy2_y"], MONTHS[g["dmy2_mon"].lower()], g["dmy2_d"])
    if g["my_y"]:
        return _make(g["my_y"], MONTHS[g["my_mon"].lower()])
    if g["y"]:
        return _make(g["y"])
    return None


def parse_date(value) -> Optional[PartialDate]:
    """Read one date value from a structured field. ``None`` when unreadable.

    Accepts a string (or a PartialDate, returned as is). Placeholders such as
    ``"N/A"`` or ``"unknown"`` read as ``None``: unknown stays unknown.
    """
    if value is None:
        return None
    if isinstance(value, PartialDate):
        return value
    s = str(value).strip().strip(".,;")
    if not s:
        return None
    m = _DATE_RE.fullmatch(s)
    if m:
        return _from_match(m)
    # A field holding one date with decoration around it, e.g. "DOB: 1985-03-12".
    found = find_dates(s)
    if len(found) == 1:
        return found[0].date
    return None


def parse_iso(value) -> Optional[str]:
    d = parse_date(value)
    return d.iso() if d else None


def parse_many(values: Iterable) -> list[PartialDate]:
    """Read a list field such as hits.dobs (``["1996", "1997"]``), tolerating a
    single ``"1996; 1997"`` string. Unreadable entries are dropped."""
    if values is None:
        return []
    if isinstance(values, str):
        values = [p for p in re.split(r"[;|]", values)]
    out = []
    for v in values:
        d = parse_date(v)
        if d and d not in out:
            out.append(d)
    return out


@dataclass(frozen=True)
class DateMention:
    date: PartialDate
    start: int
    end: int
    text: str


def find_dates(text: str, min_precision: str = "year") -> list[DateMention]:
    """Every date written in free text, in order of appearance.

    ``min_precision`` is ``"year"`` (default), ``"month"`` or ``"day"`` and
    drops mentions that are less precise than that.
    """
    if not text:
        return []
    out = []
    for m in _DATE_RE.finditer(text):
        d = _from_match(m)
        if d is None:
            continue
        if min_precision == "month" and d.month is None:
            continue
        if min_precision == "day" and not d.is_full:
            continue
        out.append(DateMention(d, m.start(), m.end(), m.group(0)))
    return out


def birth_years_from_age(age: int, at: PartialDate) -> list[int]:
    """Someone aged ``age`` at date ``at`` was born in one of two years.

    "Aged 45 in March 2019" gives 1973 or 1974: the SOP says an age at a date
    gives two possible birth years, and we never pick one.
    """
    return [at.year - age - 1, at.year - age]


def age_bounds_at(dob: PartialDate, at: PartialDate) -> tuple[int, int]:
    """(youngest, oldest) possible age in whole years of someone born on the
    (possibly partial) date ``dob`` on the (possibly partial) date ``at``.
    Used for the under-16 rule: clear only if the oldest possible age < 16."""
    # Oldest: born as early as possible, observed as late as possible.
    early_birth = (dob.year, dob.month or 1, dob.day or 1)
    late_birth = (dob.year, dob.month or 12,
                  dob.day or calendar.monthrange(dob.year, dob.month or 12)[1])
    early_at = (at.year, at.month or 1, at.day or 1)
    late_at = (at.year, at.month or 12,
               at.day or calendar.monthrange(at.year, at.month or 12)[1])

    def age(birth, when):
        years = when[0] - birth[0]
        if (when[1], when[2]) < (birth[1], birth[2]):
            years -= 1
        return years

    return age(late_birth, early_at), age(early_birth, late_at)
