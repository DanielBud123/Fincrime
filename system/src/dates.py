"""The one date reader.

Every file writes dates differently: ``2026-11-06``, ``19/05/2004``,
``February 19, 2002``, ``19 May 2004``, ``1996`` or ``1962-09``. Everything
downstream reads dates through this module so that partial dates stay partial
("unknown stays unknown").

A date is a :class:`PartialDate` with a year and optional month and day. Its
ISO form is ``"1985"``, ``"1985-03"`` or ``"1985-03-12"``.

Numeric dates (``19/05/2004``) are ambiguous between day-first and month-first.
The order is detected per source from the data itself (:func:`detect_numeric_order`):
a source showing only day-first evidence is read day-first, only month-first
evidence month-first, and a source showing both keeps just the year of any
date whose two leading numbers are both 12 or less.
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

# "default" = structured fields (customers, KYC rows, alerts, hit fields);
# "text" = the bank's own notes; "hit" = watchlist profile text and search
# snippets, written "as the provider wrote them": never assumed to share the
# bank's convention, so always read as "mixed".
_ORDER = {"default": "dmy", "text": "dmy", "hit": "mixed"}
_NUMERIC_RE = re.compile(r"(?<![\d/.-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?![\d/-])")


def set_numeric_order(order: str, source: str = "default") -> None:
    if order not in ("dmy", "mdy", "mixed"):
        raise ValueError(order)
    _ORDER[source] = order


def numeric_order(source: str = "default") -> str:
    return _ORDER.get(source, _ORDER["default"])


def detect_numeric_order(values: Iterable) -> str:
    """'dmy', 'mdy' or 'mixed' from the numeric dates in ``values``. With no
    evidence either way the bank's own convention (day first) is kept."""
    dmy = mdy = False
    for v in values:
        if not v:
            continue
        for m in _NUMERIC_RE.finditer(str(v)):
            a, b = int(m.group(1)), int(m.group(2))
            if a > 12 >= b:
                dmy = True
            elif b > 12 >= a:
                mdy = True
        if dmy and mdy:
            return "mixed"
    return "mdy" if mdy else "dmy"


@dataclass(frozen=True)
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

    def sort_key(self) -> tuple[int, int, int]:
        return (self.year, self.month or 0, self.day or 0)


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
# longer date. A bare year followed by "s" is a decade ("the 1960s"), not a year.
_DATE_RE = re.compile(
    r"(?<![\d/.-])(?:"
    r"(?P<iso_y>\d{4})(?P<iso_sep>[-/.])(?P<iso_m>\d{1,2})(?P=iso_sep)(?P<iso_d>\d{1,2})"   # year first: 1998-11-05, 1998/11/05
    r"|(?P<ym_y>\d{4})-(?P<ym_m>\d{2})"
    r"|(?P<num_a>\d{1,2})[/.-](?P<num_b>\d{1,2})[/.-](?P<num_y>\d{4})"
    r"|(?P<mdy_mon>" + _MONTH_RE + r")\.?\s+(?P<mdy_d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<mdy_y>\d{4})"
    r"|(?P<dmy2_d>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<dmy2_mon>" + _MONTH_RE + r")\.?,?\s+(?P<dmy2_y>\d{4})"
    r"|(?P<my_mon>" + _MONTH_RE + r")\.?,?\s+(?P<my_y>\d{4})"
    r"|(?P<y>(?:18|19|20)\d{2})(?!'?s\b)"
    r")(?![\d/-])(?![.]\d)",
    re.IGNORECASE,
)

# A bare year counts in free text only when the words before it make it a time.
_YEAR_CONTEXT_RE = re.compile(
    r"(?:\b(?:in|during|since|of|year|by|from|until|till|through|throughout|within|to|around|circa|about|"
    r"early|late|mid|before|after|and|or|born|between|for|dated)\s+|[(\u2013\u2014-]\s*|\bc\.\s*)$", re.IGNORECASE)
# "A 1996 media profile", "the 2014 report": a year used as an adjective before a noun.
_YEAR_ARTICLE_RE = re.compile(r"\b(?:a|an|the)\s+$", re.IGNORECASE)


def _numeric(a: int, b: int, year, order: str) -> Optional[PartialDate]:
    if order == "dmy":
        return _make(year, b, a)
    if order == "mdy":
        return _make(year, a, b)
    # mixed: only a date that can be read one way keeps its day and month
    if a > 12 >= b:
        return _make(year, b, a)
    if b > 12 >= a:
        return _make(year, a, b)
    if a == b:
        return _make(year, a, b)
    return _make(year)


def _from_match(m: re.Match, order: str) -> Optional[PartialDate]:
    g = m.groupdict()
    if g["iso_y"]:
        return _make(g["iso_y"], g["iso_m"], g["iso_d"])
    if g["ym_y"]:
        return _make(g["ym_y"], g["ym_m"])
    if g["num_y"]:
        return _numeric(int(g["num_a"]), int(g["num_b"]), g["num_y"], order)
    if g["mdy_y"]:
        return _make(g["mdy_y"], MONTHS[g["mdy_mon"].lower()], g["mdy_d"])
    if g["dmy2_y"]:
        return _make(g["dmy2_y"], MONTHS[g["dmy2_mon"].lower()], g["dmy2_d"])
    if g["my_y"]:
        return _make(g["my_y"], MONTHS[g["my_mon"].lower()])
    if g["y"]:
        return _make(g["y"])
    return None


def parse_exact(value, source: str = "default") -> Optional[PartialDate]:
    """Read a string that is a date and nothing else. No fallback."""
    if value is None:
        return None
    if isinstance(value, PartialDate):
        return value
    s = str(value).strip().strip(".,;")
    if not s:
        return None
    m = _DATE_RE.fullmatch(s)
    return _from_match(m, numeric_order(source)) if m else None


def parse_date(value, source: str = "default") -> Optional[PartialDate]:
    """Read one date value from a structured field. ``None`` when unreadable.

    Placeholders such as ``"N/A"`` or ``"unknown"`` read as ``None``: unknown
    stays unknown. A field holding one date with decoration around it
    (``"DOB: 1985-03-12"``) is read; a field holding several dates is not.
    """
    d = parse_exact(value, source)
    if d is not None or value is None or isinstance(value, PartialDate):
        return d
    found = find_dates(str(value), source=source)
    if len(found) == 1:
        return found[0].date
    return None


def parse_iso(value, source: str = "default") -> Optional[str]:
    d = parse_date(value, source)
    return d.iso() if d else None


def parse_many(values: Iterable, source: str = "default") -> tuple[list[PartialDate], list[str]]:
    """Read a list field such as hits.dobs (``["1996", "1997"]``), tolerating a
    single ``"1996; 1997"`` string. Returns (dates, entries that could not be read)."""
    if values is None:
        return [], []
    if isinstance(values, str):
        values = re.split(r"[;|]", values)
    out, unread = [], []
    for v in values:
        if v is None or not str(v).strip():
            continue
        d = parse_date(v, source)
        if d is None:
            unread.append(str(v))
        elif d not in out:
            out.append(d)
    return out, unread


@dataclass(frozen=True)
class DateMention:
    date: PartialDate
    start: int
    end: int
    text: str


def find_dates(text: str, min_precision: str = "year", source: str = "text",
               bare_years: str = "any") -> list[DateMention]:
    """Every date written in free text, in order of appearance.

    ``min_precision``: ``"year"`` (default), ``"month"`` or ``"day"``.
    ``bare_years``: ``"any"`` keeps every 4-digit year; ``"context"`` keeps a
    bare year only when the words before it make it a time ("in 2004",
    "since 1998"), so that "USD 2000" or "Flight 1995" is not a date.
    """
    if not text:
        return []
    order = numeric_order(source)
    out = []
    for m in _DATE_RE.finditer(text):
        d = _from_match(m, order)
        if d is None:
            continue
        if min_precision == "month" and d.month is None:
            continue
        if min_precision == "day" and not d.is_full:
            continue
        if d.month is None and m.group("y") and bare_years == "context":
            before = text[max(0, m.start() - 16):m.start()]
            as_adjective = _YEAR_ARTICLE_RE.search(before) and re.match(r"\s+[a-z]", text[m.end():m.end() + 3])
            if not _YEAR_CONTEXT_RE.search(before) and not as_adjective:
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
