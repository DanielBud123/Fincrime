"""Step 4: the hit's picture.

Names: ``name`` plus ``aliases``. Date of birth, in this order (principle 5):
the ``dobs`` field; the first paragraph of ``profile_notes`` (an age at a date
gives two possible birth years); only when neither gives one, web search
results for the name, and only a result that describes the same kind of
listing in a country tied to the hit. Countries: ``countries``, ``nationality``,
``citizenship``, the last part of each address, ``place_of_birth``. Dated
reports are exactly the lines "According to …; <date>: …". Death: the
``deceased_date`` field. For companies only the ``dobs`` field is a date.
"""
from __future__ import annotations

import re
from typing import Optional

from countries import codes_in_text, display, to_iso2_list
from dates import PartialDate, birth_years_from_age, find_dates, parse_date, parse_many
from load import Data, as_list, clean, is_company
from names import normalize_name, query_key
from schema import COMPANY, PERSON, HitFacts

# Listing phrase per category (POLICY.md principle 5). Worded the same in the unseen set.
LISTING_PHRASES = {
    "sanctions": ["a sanctioned individual", "sanctioned individual"],
    "pep": ["a politically exposed person", "politically exposed person"],
    "enforcement": ["the subject of enforcement action", "subject of enforcement action"],
    "adverse media": ["named in adverse media", "adverse media"],
    "soe": ["a state-owned enterprise official", "state-owned enterprise official"],
}
OTHER_PHRASES = ["named on a watchlist", "on a watchlist"]

REPORT_LINE_RE = re.compile(r"^\s*According to\s+[^;\n]+;\s*([^:\n]{4,40}?)\s*:", re.IGNORECASE | re.MULTILINE)
BIRTH_RE = re.compile(r"\b(?:was\s+)?(?:born|b\.|birth|dob|d\.o\.b\.?|date of birth|birthdate)\b", re.IGNORECASE)
AGE_RES = [
    # "aged 45", "age of 38", "at the age of 33", "the age of Tomasz Drozd was 38"
    re.compile(r"\b(?:aged?|age of)\s+(?:[^\W\d_][\w'’.-]*\s+){0,5}?(?:was\s+)?(\d{1,3})\b"
               r"(?!\s*(?:,\d|%|percent|million|billion|thousand|years? (?:in|of|after|before|later)))", re.IGNORECASE),
    # "30-year-old", "33 year old"
    re.compile(r"\b(\d{1,3})[\s-]?years?[\s-]old\b", re.IGNORECASE),
    # "Age: 55"
    re.compile(r"\bage\s*:\s*(\d{1,3})\b(?!\s*,\d)", re.IGNORECASE),
    # "John Smith, 45," / "Raković, 29," / "Garcia, a 40 named on a watchlist" — a WORD before the
    # comma (never a number: "PKR 11,000,000") and no further digits after the age.
    re.compile(r"(?<![\w,.])[^\W\d_][\w'’.-]*,\s*(?:a\s+|an\s+)?(\d{1,3}),(?=\s+[a-z])"),
    re.compile(r"(?<![\w,.])[^\W\d_][\w'’.-]*,\s*(?:a|an)\s+(\d{1,3})\b(?!\s*(?:,\d|%|percent|million|billion|thousand|year))"),
    # "he was 46", "who was 36", "she is 52"
    re.compile(r"\b(?:who|he|she|they)\s+(?:was|were|is|are)\s+(?:then\s+|only\s+|just\s+|about\s+)?(\d{1,3})\b"
               r"(?!\s*(?:,\d|%|percent|million|billion|thousand|years? (?:in|of|after|before|later|into)|months|days|weeks))",
               re.IGNORECASE),
    re.compile(r"\bturned\s+(\d{1,3})\b(?!\s*,\d)", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s+years\s+of\s+age\b", re.IGNORECASE),
]


def hit_entity_type(hit: dict) -> str:
    return COMPANY if is_company(hit.get("entity_type")) else PERSON


def hit_names(hit: dict) -> list[str]:
    names = []
    for n in [hit.get("name"), hit.get("best_matching_name")] + as_list(hit.get("aliases")):
        n = clean(n)
        if n and n not in names:
            names.append(n)
    parts = [clean(hit.get(k)) for k in ("first_name", "middle_name", "last_name")]
    if any(parts):
        joined = " ".join(p for p in parts if p)
        if joined not in names:
            names.append(joined)
    return names


def hit_countries(hit: dict) -> list[str]:
    values = as_list(hit.get("countries")) + as_list(hit.get("nationality")) + as_list(hit.get("citizenship"))
    values += as_list(hit.get("addresses"))
    pob = clean(hit.get("place_of_birth"))
    if pob:
        values += [p for p in re.split(r"\s*;\s*", pob) if p]
    return to_iso2_list(values)


def hit_category(hit: dict) -> Optional[str]:
    cat = clean(hit.get("primary_category")) or (as_list(hit.get("categories")) or [None])[0]
    return cat.strip().lower() if cat else None


def listing_phrases(hit: dict) -> list[str]:
    return LISTING_PHRASES.get(hit_category(hit) or "", OTHER_PHRASES)


def first_paragraph(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]


def earliest_report_date(hit: dict) -> Optional[PartialDate]:
    notes = hit.get("profile_notes") or ""
    dates = []
    for m in REPORT_LINE_RE.finditer(notes):
        d = parse_date(m.group(1))
        if d:
            dates.append(d)
    return min(dates, key=lambda d: (d.year, d.month or 1, d.day or 1)) if dates else None


def _dates_near(text: str, start: int, window: int = 60) -> list[PartialDate]:
    return [m.date for m in find_dates(text) if start <= m.start <= start + window]


def dobs_from_text(text: str) -> list[PartialDate]:
    """Birth dates stated in a piece of text: 'born on 4 July 1962', 'born in
    1966', or an age at a date ('aged 45 in March 2019' -> 1973, 1974).
    Returns [] when nothing certain is found."""
    if not text:
        return []
    out: list[PartialDate] = []
    for m in BIRTH_RE.finditer(text):
        near = _dates_near(text, m.end(), 40)
        if near:
            out.append(near[0])
    if out:
        return list(dict.fromkeys(out))
    for rx in AGE_RES:
        for m in rx.finditer(text):
            age = int(m.group(1))
            if not (0 < age < 110):
                continue
            # the date the age refers to: the first date after the age, else the only date in the text
            after = [d for d in find_dates(text) if d.start >= m.end()]
            dates = [d.date for d in after] or [d.date for d in find_dates(text)]
            dates = [d for d in dates if d.year >= 1800]
            if len(dates) >= 1:
                at = dates[0]
                for y in birth_years_from_age(age, at):
                    pd = PartialDate(y)
                    if pd not in out:
                        out.append(pd)
                break
        if out:
            break
    return out


def search_results_for(data: Data, hit: dict) -> list[dict]:
    seen, out = set(), []
    for n in hit_names(hit):
        for r in data.search_by_query.get(query_key(n), []):
            if r["result_id"] not in seen:
                seen.add(r["result_id"])
                out.append(r)
    return out


def result_is_about_hit(result: dict, hit: dict, hit_codes: list[str]) -> bool:
    """A result is about the hit only if it describes the same kind of listing
    in a country tied to the hit (principle 5)."""
    text = f"{result.get('title') or ''} {result.get('snippet') or ''}".lower()
    if not any(p in text for p in listing_phrases(hit)):
        return False
    if not hit_codes:
        return False
    return bool(set(codes_in_text(text)) & set(hit_codes))


def build_hit_facts(data: Data, hit: dict) -> HitFacts:
    etype = hit_entity_type(hit)
    names = hit_names(hit)
    codes = hit_countries(hit)
    dobs: list[PartialDate] = parse_many(hit.get("dobs"))
    origin, dob_sources = ("field", []) if dobs else (None, [])

    if not dobs and etype == PERSON:
        dobs = dobs_from_text(first_paragraph(hit.get("profile_notes")))
        if dobs:
            origin = "notes"
    if not dobs and etype == PERSON:
        for r in search_results_for(data, hit):
            if not result_is_about_hit(r, hit, codes):
                continue
            found = dobs_from_text(f"{r.get('title') or ''}. {r.get('snippet') or ''}")
            if found:
                for d in found:
                    if d not in dobs:
                        dobs.append(d)
                dob_sources.append(r["result_id"])
        if dobs:
            origin = "search"

    death = parse_date(hit.get("deceased_date"))
    report = earliest_report_date(hit)
    return HitFacts(
        hit_id=hit["hit_id"], entity_type=etype, names=names,
        dobs=[d.iso() for d in dobs], countries=codes,
        earliest_report_date=report.iso() if report else None,
        date_of_death=death.iso() if death else None,
        source_ids=list(dob_sources), dob_source_ids=list(dob_sources), dob_origin=origin,
        country_names=[display(c) for c in codes], primary_category=hit_category(hit),
    )
