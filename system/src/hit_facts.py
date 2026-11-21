"""Step 4: the hit's picture.

Names: ``name`` plus ``aliases``. Date of birth, in this order (principle 5):
the ``dobs`` field; else a sentence in the first paragraph of ``profile_notes``
(an age at a date gives two possible birth years); only when neither gives
one, web search results for the name, and only a result that describes the
same kind of listing in a country tied to the hit. Countries: ``countries``,
``nationality``, ``citizenship``, the last part of each address,
``place_of_birth``. Dated reports are exactly the lines
"According to …; <date>: …". Death: the ``deceased_date`` field. For companies
only the ``dobs`` field is a date.

The design rule: a wrong fact about the hit can clear it, so every reader
here returns a fact only when it is certain, and says so when the hit holds
something it could not read. An age with two candidate dates, two ages in one
paragraph, an approximate or ranged birth year, a country value that does not
map: each makes that part of the picture incomplete, and the rules refuse to
clear on an incomplete picture.
"""
from __future__ import annotations

import re
from typing import Optional

from countries import codes_in_text, display, field_codes
from dates import PartialDate, birth_years_from_age, find_dates, parse_date, parse_exact, parse_many
from load import Data, as_list, clean, entity_kind
from names import has_latin_parts, query_key
from schema import HitFacts

# Listing phrase per category (POLICY.md principle 5). The SOP says these are
# worded the same in the unseen set, so they are matched exactly.
LISTING_PHRASE = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_PHRASE = "named on a watchlist"

# "According to <source>; <full date>: ..." and nothing else.
REPORT_LINE_RE = re.compile(r"^[ \t]*According to\s+(?:.+?);[ \t]*([^;:\n]{4,40}?)[ \t]*:(?!//)",
                            re.IGNORECASE | re.MULTILINE)

MIN_AGE, MAX_AGE = 12, 100

_BORN_RE = re.compile(r"\bborn\b|\bdate of birth\b|\bbirth ?date\b|\bd\.?o\.?b\b\.?|(?<=\()b\.", re.IGNORECASE)
# A birth year that is approximate, a range or one of several is not a date of birth we can use.
_VAGUE_RE = re.compile(r"\b(between|or|and|either|circa|around|about|approximately|approx|roughly|some time|"
                       r"sometime|early|late|mid)\b|\bc\.|\bca\.|~", re.IGNORECASE)
# The sentence is about someone else when one of these comes just before the age or the birth.
_RELATIVE_RE = re.compile(
    r"\b(son|daughter|wife|husband|brother|sister|father|mother|child|children|spouse|nephew|niece|cousin|"
    r"partner|uncle|aunt|parent|sibling|associate|co-?defendant|accomplice|victim|friend|colleague)s?\b"
    r"[^.;\n]{0,40}$", re.IGNORECASE)

_N = r"(\d{1,3})"
_NOT_A_NUMBER_PART = r"(?![\d/%:])(?![.,]\d)"
AGE_RES = [
    # "aged 45", "at the age of 33", "reached the age of 38"
    re.compile(r"\b(?:aged|age of|age)\s+(?:(?:about|around|approximately|just|only)\s+)?" + _N + r"\b"
               r"(?!\s*(?:[-–]|to\b|or\b|and\b)\s*\d)" + _NOT_A_NUMBER_PART, re.IGNORECASE),
    # "the age of Tomasz Drozd was 38"
    re.compile(r"\bage of\s+(?:[^\W\d_][\w'’.-]*\s+){1,5}?was\s+" + _N + r"\b" + _NOT_A_NUMBER_PART, re.IGNORECASE),
    # "30-year-old", "33 year old"
    re.compile(r"\b" + _N + r"[\s-]?years?[\s-]old\b", re.IGNORECASE),
    # "Age: 55"
    re.compile(r"\bage\s*:\s*" + _N + r"\b" + _NOT_A_NUMBER_PART, re.IGNORECASE),
    # "John Smith, 45, a ..." / "Raković, 29, was ...": a word before the comma, never a number
    # ("PKR 11,000,000"), and a lower-case word after the age, never an address ("45, Main Street").
    re.compile(r"(?<![\w,.])[^\W\d_][\w'’.-]*,\s*(?:a\s+|an\s+)?" + _N + r",(?=\s+[a-z])"),
    # "Garcia, a 40 named on a watchlist"
    re.compile(r"(?<![\w,.])[^\W\d_][\w'’.-]*,\s*(?:a|an)\s+" + _N + r"\b(?=\s+(?:named|listed|who|was|is|and|from|in)\b)"),
    # "he was 46.", "who was 36 and worked", "Thomas Walsh was 25 when taken into custody", "the subject
    # was 48": a person before "was" (a pronoun, a person word or a capitalised name, never "the fine
    # was 50") and a word after the number that makes it an age.
    # A capitalised word counts as a name only when another word precedes it, so a sentence
    # that opens "Bail was 50 ..." is not read; "50,000" is never an age.
    re.compile(r"(?:\b(?i:who|he|she|they|subject|individual|man|woman|accused|defendant|suspect)|(?<=[\w.,]\s)[A-ZÀ-Þ][\w'’.-]*)"
               r"\s+(?i:was|were|is|are)\s+(?i:then\s+|only\s+|just\s+|about\s+)?" + _N + r"\b(?![.,]\d)"
               r"(?=\s*(?:[.,;:)]|$|(?i:years?\s+old|at|when|and|in|on|during|as|while)\b))"),
    # "Mark Phillips, at 24, was taken into custody"
    re.compile(r"(?<![\w,.])[^\W\d_][\w'’.-]*,\s*at\s+" + _N + r",(?=\s+[a-z])"),
    re.compile(r"\bturned\s+" + _N + r"\b(?=\s*(?:[.,;:)]|$|in\b|on\b|during\b|that\b|this\b|last\b))", re.IGNORECASE),
    # "now 61 (2024)", "currently aged 61"
    re.compile(r"\b(?:now|currently)\s+(?:aged\s+)?" + _N + r"\b(?![.,]\d)(?=\s*(?:[.,;:)(]|$|years?\s+old\b))", re.IGNORECASE),
    re.compile(r"\b" + _N + r"\s+years\s+of\s+age\b", re.IGNORECASE),
]
# Wording that states an age even when we cannot read the number.
_AGE_CUE_RE = re.compile(
    r"\b(aged\s+\w+|\w+[- ]years?[- ]old|years of age|at the age\b|the age of\b|age\s*:|"
    r"in (?:his|her|their) (?:early[- ]|mid[- ]?|late[- ])?(?:teens|twenties|thirties|forties|fifties|sixties|"
    r"seventies|eighties|nineties|\d0s)|turned\s+\w+|\d+(?:st|nd|rd|th) birthday|at \d{2},|"
    r"(?:was|is) \d{2}\b(?!\s*(?:%|percent|million|billion|thousand|[a-z]*metres?|miles?|km\b)))", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?;])\s+|\n+")


def hit_entity_type(hit: dict) -> Optional[str]:
    """'person', 'company', or None when the type is missing or unknown."""
    return entity_kind(hit.get("entity_type"))


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


def hit_country_values(hit: dict) -> list[str]:
    values = as_list(hit.get("countries")) + as_list(hit.get("nationality")) + as_list(hit.get("citizenship"))
    values += as_list(hit.get("addresses"))
    pob = clean(hit.get("place_of_birth"))
    if pob:
        values += [p for p in re.split(r"\s*;\s*", pob) if p]
    return values


def hit_countries(hit: dict) -> list[str]:
    return field_codes(hit_country_values(hit))[0]


def hit_category(hit: dict) -> Optional[str]:
    cat = clean(hit.get("primary_category")) or (as_list(hit.get("categories")) or [None])[0]
    return cat.strip().lower() if cat else None


def listing_phrase(hit: dict) -> str:
    return LISTING_PHRASE.get(hit_category(hit) or "", OTHER_PHRASE)


def first_paragraph(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.split(r"\n\s*\n", text.strip(), maxsplit=1)[0]


def is_birth_sentence_paragraph(paragraph: str) -> bool:
    """The SOP reads a date of birth from "a sentence in the first paragraph".

    That is a line of prose about the person. A provider's record dump
    ("Name: …" / "DOB: 6/20/1955" on separate lines) or a dated report line
    ("According to …; <date>: …") is not such a sentence: whatever birth-like
    value sits inside it is not relied on, in either direction. Reading more
    than the SOP names is how a confident wrong fact gets made.
    """
    p = (paragraph or "").strip()
    if not p or "\n" in p or len(p) > 400:
        return False
    if re.match(r"according to\b", p, re.IGNORECASE):
        return False
    if re.match(r"[A-Za-z][A-Za-z ./]{0,24}:\s", p):      # "Name: …", "DOB: …"
        return False
    return True


def report_dates(hit: dict) -> list[PartialDate]:
    """Dates of the hit's dated reports: only lines "According to …; <full date>: …"."""
    out = []
    for m in REPORT_LINE_RE.finditer(hit.get("profile_notes") or ""):
        d = parse_exact(m.group(1), "hit")
        if d and d.is_full:
            out.append(d)
    return out


def earliest_report_date(hit: dict) -> Optional[PartialDate]:
    dates_ = report_dates(hit)
    return min(dates_, key=PartialDate.sort_key) if dates_ else None


def _sentence_bounds(text: str, pos: int) -> tuple[int, int]:
    start, end = 0, len(text)
    for m in _SENTENCE_END_RE.finditer(text):
        if m.end() <= pos:
            start = m.end()
        elif m.start() >= pos:
            end = m.start()
            break
    return start, end


def read_birth_facts(text: Optional[str]) -> tuple[list[PartialDate], bool]:
    """(birth dates stated in the text, whether it states one we could not read).

    Read: "born on 4 July 1962", "born in 1966", and one age tied to one year
    ("aged 45 in March 2019" -> 1973 or 1974). Not read, and reported as
    unread: approximate or ranged years, two different ages, an age with two
    candidate years, an age written in words.
    """
    if not text or not text.strip():
        return [], False
    dobs: list[PartialDate] = []
    unread = False

    for m in _BORN_RE.finditer(text):
        s_start, s_end = _sentence_bounds(text, m.start())
        if _RELATIVE_RE.search(text[max(s_start, m.start() - 48):m.start()]):
            continue
        tail = text[m.end():m.end() + 60].split("\n")[0]
        if not re.search(r"\d", tail):
            continue                                  # "born in Cairo": no date is claimed
        found = find_dates(tail, source="hit")
        gap = tail[:found[0].start] if found else tail
        if re.search(r"[.!?;]\s+(?!\d)", tail[:found[0].start + 1] if found else tail):
            continue                                  # the date belongs to the next sentence
        if not found or re.search(r"\d", gap) or _VAGUE_RE.search(gap) \
                or re.match(r"\s*(?:or|and|to|[-–/])\s*\d", tail[found[0].end:found[0].end + 12], re.IGNORECASE):
            unread = True
            continue
        if found[0].date not in dobs:
            dobs.append(found[0].date)

    ages = []
    for rx in AGE_RES:
        for m in rx.finditer(text):
            s_start, s_end = _sentence_bounds(text, m.start())
            if _RELATIVE_RE.search(text[max(s_start, m.start() - 48):m.start()]):
                continue
            ages.append((int(m.group(1)), s_start, s_end))
    values = {a[0] for a in ages}
    if len(values) > 1:
        unread = True
    elif len(values) == 1:
        age, s_start, s_end = ages[0]
        years = {d.date.year for d in find_dates(text[s_start:s_end], source="hit", bare_years="context")}
        if not years:
            years = {d.date.year for d in find_dates(text, source="hit", bare_years="context")}
        if MIN_AGE <= age <= MAX_AGE and len(years) == 1:
            for y in birth_years_from_age(age, PartialDate(years.pop())):
                if PartialDate(y) not in dobs:
                    dobs.append(PartialDate(y))
        else:
            unread = True
    if not dobs and not unread and _AGE_CUE_RE.search(text):
        unread = True
    return dobs, unread


def dobs_from_text(text: Optional[str]) -> list[PartialDate]:
    """Birth dates stated in a piece of text, or [] when nothing is certain."""
    return read_birth_facts(text)[0]


def search_results_for(data: Data, hit: dict) -> list[dict]:
    seen, out = set(), []
    for n in hit_names(hit):
        key = query_key(n)
        if not key:
            continue
        for r in data.search_by_query.get(key, []):
            if r["result_id"] not in seen:
                seen.add(r["result_id"])
                out.append(r)
    return out


def result_is_about_hit(result: dict, hit: dict, hit_codes: list[str]) -> bool:
    """A result is about the hit only if it describes the same kind of listing
    in a country tied to the hit (principle 5). The country must be written in
    the result's own title or snippet."""
    text = f"{result.get('title') or ''} {result.get('snippet') or ''}"
    if listing_phrase(hit) not in text.lower():
        return False
    if not hit_codes:
        return False
    if not set(codes_in_text(text)) & set(hit_codes):
        return False
    # The result must name the hit: every word of one of the hit's names (initials
    # aside) is in the result. A relative who shares the surname, the listing and
    # the country is a different person.
    said = set(query_key(text).split())
    for name in hit_names(hit):
        words = [w for w in query_key(name).split() if len(w) > 1]
        if words and all(w in said for w in words):
            return True
    return False


def build_hit_facts(data: Data, hit: dict) -> HitFacts:
    etype = hit_entity_type(hit)
    names = hit_names(hit)
    codes, unread_countries = field_codes(hit_country_values(hit))
    country_gaps = [f"a country value on the hit could not be read ({u})" for u in unread_countries]

    dob_gaps: list[str] = []
    dobs, unread_dobs = parse_many(hit.get("dobs"))
    for u in unread_dobs:
        dob_gaps.append(f"a date of birth listed on the hit could not be read ({u})")
    origin, dob_sources = ("field" if dobs else None), []

    if not dobs and not unread_dobs and etype != "company":
        paragraph = first_paragraph(hit.get("profile_notes"))
        found, unread = read_birth_facts(paragraph) if is_birth_sentence_paragraph(paragraph) else ([], False)
        if found:
            dobs, origin = found, "notes"
        if unread:
            dob_gaps.append("the hit's profile notes state an age or birth date that could not be read with certainty")
        if not found and not unread:
            for r in search_results_for(data, hit):
                if not result_is_about_hit(r, hit, codes):
                    continue
                got, unread_r = read_birth_facts(f"{r.get('title') or ''}. {r.get('snippet') or ''}")
                if got:
                    for d in got:
                        if d not in dobs:
                            dobs.append(d)
                    dob_sources.append(r["result_id"])
                if unread_r:
                    dob_gaps.append(f"search result {r['result_id']} states an age or birth date that could not be read")
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
        names_comparable=any(has_latin_parts(n) for n in names),
        dobs_complete=not dob_gaps, dob_gaps=dob_gaps,
        countries_complete=not country_gaps, country_gaps=country_gaps,
    )
