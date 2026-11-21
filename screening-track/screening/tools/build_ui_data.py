#!/usr/bin/env python3
"""Build ui/data.js for the read-only analyst screen (ui/index.html).

    python tools/build_ui_data.py                       # from the screening folder
    python tools/build_ui_data.py --decisions output/dev.jsonl \
        --diagnostics output/dev.diagnostics.jsonl --data dev --out ui/data.js

Browsers block file:// fetches, so the screen cannot read the JSONL files
itself. This script embeds them into one JavaScript file,
``window.SCREENING_DATA = {...}``, that ui/index.html loads with a plain
<script> tag. After that the page opens by double-clicking it.

What goes in:

- ``decisions``    output/dev.jsonl, line for line, in file order
- ``diagnostics``  output/dev.diagnostics.jsonl, keyed by hit id
- ``alerts``, ``hits``  only the fields the screen shows
- ``derived``      per hit: the "rules checked" list for each resolved person,
                   and the free-text records (notes, profile notes, search
                   results) behind its facts, with the extracted value located
- ``llm_review``   output/dev.llm_review.jsonl keyed by hit id, when it exists

The raw customers table is never read or embedded.

Read-only by design: it reads the output and data files and writes only the
``--out`` file. It never runs the system. To locate extracted values in text
it reuses the system's own readers (dates, countries, places, hit_facts) by
importing them, with bytecode writing switched off so nothing is created under
system/. If a reader cannot be imported, a simpler built-in one is used and
the build says so.

Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True          # importing system/src must not write __pycache__ there

ROOT = Path(__file__).resolve().parent.parent

# The SOP's listing phrase per category (POLICY.md principle 5): a search
# result is about the hit only if it carries this phrase and a hit country.
LISTING_PHRASE = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_PHRASE = "named on a watchlist"

RECORD_ID_RE = re.compile(r"\b(?:NOTE|SR)-[0-9A-Fa-f]{6}\b")
CLIP_LIMIT = 520                        # longest text shown for one source record


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{n}: not valid JSON ({e}). The file may be mid-rewrite; run again.")
    return rows


def fingerprint(path: Path) -> dict:
    data = path.read_bytes()
    return {
        "file": path.name,
        "lines": sum(1 for line in data.splitlines() if line.strip()),
        "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "sha1": hashlib.sha1(data).hexdigest()[:12],
    }


def as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v not in (None, "")]
    return [value]


# ---------------------------------------------------------------------------
# the system's own readers, imported read-only (optional)
# ---------------------------------------------------------------------------

class Readers:
    dates = None
    countries = None
    places = None
    hit_facts = None
    problems: list[str] = []


def load_readers(system_src: Path) -> None:
    if not system_src.is_dir():
        Readers.problems.append(f"{system_src} not found")
        return
    sys.path.insert(0, str(system_src))
    for name in ("dates", "countries", "places", "hit_facts"):
        try:
            setattr(Readers, name, __import__(name))
        except Exception as e:  # a module mid-edit must not stop the build
            Readers.problems.append(f"system/src/{name}.py could not be imported ({type(e).__name__}: {e})")


# ---------------------------------------------------------------------------
# spans: where an extracted value sits in a text
# ---------------------------------------------------------------------------

def merge_spans(spans, text: str = "", join_gap: bool = False) -> list[list[int]]:
    """Sorted, non-overlapping spans. With ``join_gap`` two spans separated
    only by spaces or hyphens become one (the words of a name)."""
    out: list[list[int]] = []
    for s, e in sorted({(int(s), int(e)) for s, e in spans if e > s}):
        if out and (s <= out[-1][1] or (join_gap and re.fullmatch(r"[\s\-]*", text[out[-1][1]:s]))):
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def find_all(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    out, low, n = [], text.lower(), needle.lower()
    i = low.find(n)
    while i >= 0:
        out.append((i, i + len(n)))
        i = low.find(n, i + len(n))
    return out


_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"]
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|" \
       r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_FALLBACK_DATE_RE = re.compile(
    r"(?<![\d/.-])(?:"
    r"(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})"
    r"|(?P<na>\d{1,2})[/.-](?P<nb>\d{1,2})[/.-](?P<ny>\d{4})"
    r"|(?P<m1>" + _MON + r")\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y1>\d{4})"
    r"|(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m2>" + _MON + r")\.?,?\s+(?P<y2>\d{4})"
    r"|(?P<m3>" + _MON + r")\.?,?\s+(?P<y3>\d{4})"
    r"|(?P<y>(?:18|19|20)\d{2})"
    r")(?![\d/-])", re.IGNORECASE)


def _iso(y, m=None, d=None) -> str:
    return f"{int(y):04d}" + (f"-{int(m):02d}" if m else "") + (f"-{int(d):02d}" if m and d else "")


def _month(word: str) -> int:
    return next(i + 1 for i, name in enumerate(_MONTHS) if name.startswith(word.lower()[:3]))


def _fallback_dates(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in _FALLBACK_DATE_RE.finditer(text):
        g = m.groupdict()
        if g["iy"]:
            isos = [_iso(g["iy"], g["im"], g["id"])]
        elif g["ny"]:                       # numeric: keep both readings, the caller compares
            isos = [_iso(g["ny"], g["nb"], g["na"]), _iso(g["ny"], g["na"], g["nb"])]
        elif g["y1"]:
            isos = [_iso(g["y1"], _month(g["m1"]), g["d1"])]
        elif g["y2"]:
            isos = [_iso(g["y2"], _month(g["m2"]), g["d2"])]
        elif g["y3"]:
            isos = [_iso(g["y3"], _month(g["m3"]))]
        else:
            isos = [_iso(g["y"])]
        out.extend((iso, m.start(), m.end()) for iso in isos)
    return out


def date_mentions(text: str, source: str) -> list[tuple[str, int, int]]:
    """[(iso, start, end)] for every date written in ``text``. A numeric date
    (03/04/1970) is returned under both readings: this is used only to find
    where an already-extracted value sits, never to extract one."""
    d = Readers.dates
    if d is None:
        return _fallback_dates(text)
    out: list[tuple[str, int, int]] = []
    saved = d.numeric_order(source)
    try:
        for order in ("dmy", "mdy"):
            d.set_numeric_order(order, source)
            for m in d.find_dates(text, source=source):
                item = (m.date.iso(), m.start, m.end)
                if item not in out:
                    out.append(item)
    except Exception:
        return _fallback_dates(text)
    finally:
        d.set_numeric_order(saved, source)
    return out


def date_spans(text: str, iso: str, source: str = "text") -> list[list[int]]:
    return merge_spans((s, e) for value, s, e in date_mentions(text, source) if value == iso)


def name_spans(text: str, name: str) -> list[list[int]]:
    whole = find_all(text, name.strip())
    if whole:
        return merge_spans(whole)
    spans = []
    for word in re.split(r"[\s\-]+", name):
        word = word.strip(".,'’")
        if len(word) < 2:
            continue
        spans += [m.span() for m in re.finditer(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.IGNORECASE)]
    return merge_spans(spans, text, join_gap=True)


def country_spans(text: str, code: str, names: dict[str, str]) -> list[list[int]]:
    spans: list[tuple[int, int]] = []
    if Readers.countries is not None:
        try:
            for found, written in Readers.countries.find_in_text(text):
                if found == code and written:
                    spans += find_all(text, written)
        except Exception:
            pass
    if not spans and Readers.places is not None:      # a city the system maps to this country
        try:
            p = Readers.places
            for m in p._PLACE_RE.finditer(p._fold_keep(text)):
                if code in p._PLACES[m.group(1)] and text[m.start()].isupper():
                    spans.append(m.span())
        except Exception:
            pass
    if not spans and names.get(code):
        spans += find_all(text, names[code])
    return merge_spans(spans)


_FALLBACK_BORN_RE = re.compile(r"\bborn\b|\bdate of birth\b|\bbirth ?date\b|\bd\.?o\.?b\b\.?", re.IGNORECASE)
_FALLBACK_AGE_RES = [
    re.compile(r"\b(?:aged|age of|age)\s+(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})[\s-]?years?[\s-]old\b", re.IGNORECASE),
    re.compile(r",\s*(?:a\s+|an\s+|at\s+)?(\d{1,3}),"),
    re.compile(r"\b(?:was|were|is|turned)\s+(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s+years\s+of\s+age\b", re.IGNORECASE),
]


def birth_spans(text: str, dobs: list[str]) -> list[list[int]]:
    """The words that give a hit's birth date: the date after a birth word,
    or an age together with the date it is tied to (aged 45 in March 2019 ->
    1973 or 1974). A span is returned only when it reproduces the value the
    system extracted."""
    targets = set(dobs)
    years = {int(d[:4]) for d in dobs if d[:4].isdigit()}
    mentions = date_mentions(text, "hit")
    born_re = getattr(Readers.hit_facts, "_BORN_RE", None) or _FALLBACK_BORN_RE
    age_res = getattr(Readers.hit_facts, "AGE_RES", None) or _FALLBACK_AGE_RES
    spans: list[tuple[int, int]] = []
    for m in born_re.finditer(text):
        for iso, s, e in mentions:
            if m.end() <= s <= m.end() + 60 and iso in targets:
                spans.append((s, e))
                break
    for rx in age_res:
        for m in rx.finditer(text):
            try:
                age = int(m.group(1))
            except (IndexError, TypeError, ValueError):
                continue
            for iso, s, e in mentions:
                year = int(iso[:4])
                if {year - age - 1, year - age} <= years:
                    spans += [m.span(1), (s, e)]
    if not spans:
        spans = [(s, e) for iso, s, e in mentions if iso in targets]
    return merge_spans(spans)


_FALLBACK_REPORT_RE = re.compile(r"^[ \t]*According to\s+(?:.+?);[ \t]*([^;:\n]{4,40}?)[ \t]*:(?!//)",
                                 re.IGNORECASE | re.MULTILINE)


def report_line(profile_notes: str, iso: str):
    """(line, span of the date) for the dated report "According to …; <date>: …"
    whose date is ``iso``; (None, None) when it cannot be found."""
    rx = getattr(Readers.hit_facts, "REPORT_LINE_RE", None) or _FALLBACK_REPORT_RE
    for m in rx.finditer(profile_notes or ""):
        written = m.group(1)
        if not any(value == iso for value, _, _ in date_mentions(written, "hit")):
            continue
        line_start = profile_notes.rfind("\n", 0, m.start()) + 1
        line_end = profile_notes.find("\n", m.end())
        line_end = len(profile_notes) if line_end < 0 else line_end
        return profile_notes[line_start:line_end], [m.start(1) - line_start, m.end(1) - line_start]
    return None, None


def first_paragraph(text) -> str:
    return re.split(r"\n\s*\n", (text or "").strip(), maxsplit=1)[0]


def clip(text: str, facts: list[dict]) -> str:
    """Shorten a long text to the stretch around the highlighted values and
    shift every span to match. Short texts are returned unchanged."""
    if len(text) <= CLIP_LIMIT:
        return text
    spans = [s for f in facts for s in f["spans"]]
    first = min((s[0] for s in spans), default=0)
    last = max((s[1] for s in spans), default=0)
    start = max(0, first - 140)
    if start:
        cut = text.find(" ", start)
        start = cut + 1 if 0 <= cut < first else start
    end = min(len(text), max(last + 260, start + CLIP_LIMIT))
    if end < len(text):
        cut = text.rfind(" ", last, end)
        end = cut if cut > last else end
    prefix, suffix = ("… " if start else ""), (" …" if end < len(text) else "")
    shift = len(prefix) - start
    for f in facts:
        f["spans"] = [[s + shift, e + shift] for s, e in f["spans"] if s >= start and e <= end]
    return prefix + text[start:end] + suffix


# ---------------------------------------------------------------------------
# rules checked: one row per SOP rule, per resolved person
# ---------------------------------------------------------------------------

FIRED, BLOCKED, NOT_APPLICABLE, NO = "fired", "blocked", "na", "no"


def _or(values) -> str:
    return " or ".join(values)


def rules_for(cand: dict, hit: dict, screened_at, country_name) -> list[dict]:
    """The SOP rules in the order the system checks them, each with a state:

    fired    the rule holds and decides the hit
    blocked  the contradiction is there but could not be relied on
    na       not applicable: a fact the rule needs is unknown
    no       checked, and it does not hold
    """
    c, a = cand.get("customer") or {}, cand.get("assessment") or {}
    fired = list(a.get("fired") or [])
    blocked: dict[str, str] = {}
    for b in a.get("blocked") or []:
        blocked.setdefault(b.get("rule"), b.get("why") or "the facts behind it are uncertain")
    company = a.get("kind") == "company"
    dob, hit_dobs = c.get("dob"), list(hit.get("dobs") or [])
    cust_countries, hit_countries = list(c.get("countries") or []), list(hit.get("countries") or [])
    legal = c.get("legal_name") or "the customer"
    places = lambda codes: ", ".join(country_name(x) for x in codes)   # noqa: E731
    dob_word = "incorporation date" if company else "date of birth"
    rows: list[dict] = []

    def row(code, title, state, note):
        rows.append({"code": code, "label": title, "state": state, "note": note})

    def standard(code, title, fired_note, missing, no_note):
        """fired -> blocked -> a needed fact unknown -> checked, no contradiction."""
        if code in fired:
            row(code, title, FIRED, fired_note)
        elif code in blocked:
            row(code, title, BLOCKED, "contradiction seen but not relied on: " + blocked[code])
        elif missing:
            row(code, title, NOT_APPLICABLE, missing)
        else:
            row(code, title, NO, no_note)

    ct, ht = c.get("entity_type"), hit.get("entity_type")
    standard("ENTITY_TYPE_MISMATCH", "Type",
             f"contradiction: the customer is a {ct}, the hit is a {ht}",
             None if ct and ht else "entity type unknown for the " + ("customer" if not ct else "hit"),
             f"no contradiction: both are a {ct}")

    death = hit.get("date_of_death")
    standard("DECEASED", "Death",
             f"contradiction: the hit died on {death}, before screening on {screened_at}",
             "the hit gives no date of death" if not death else None if screened_at else "screening date unknown",
             f"no contradiction: date of death {death} is not certainly before screening on {screened_at}")

    report = hit.get("earliest_report_date")
    if company:
        temporal_fired = f"contradiction: incorporated {dob}, after the hit's earliest dated report on {report}"
        temporal_no = f"no contradiction: incorporated {dob}, not after the earliest dated report on {report}"
    else:
        temporal_fired = f"contradiction: born {dob}, at most {a.get('too_young_age')} at the hit's earliest dated report on {report}"
        temporal_no = f"no contradiction: born {dob}, not certainly under 16 at the earliest dated report on {report}"
    standard("TEMPORAL_IMPOSSIBILITY", "Time", temporal_fired,
             "the hit has no dated report" if not report else None if dob else f"customer {dob_word} unknown",
             temporal_no)

    if a.get("dob_agrees"):
        dob_no = f"no contradiction: {dob} agrees with the hit's {_or(hit_dobs)}"
    else:
        dob_no = f"no contradiction: {dob} against the hit's {_or(hit_dobs)} (not every date the hit gives is contradicted)"
    standard("DOB_MISMATCH", dob_word.capitalize(),
             f"contradiction: customer {dob} against the hit's {_or(hit_dobs)}",
             f"customer {dob_word} unknown" if not dob else None if hit_dobs else f"the hit gives no {dob_word}",
             dob_no)

    if not a.get("name_usable", True):
        name_missing = ("the hit has no name in Latin letters" if hit.get("names_comparable") is False
                        else "the customer's names have fewer than two real parts")
    elif not c.get("name_verified"):
        name_missing = "the customer's name is declared, not verified by an approved check"
    else:
        name_missing = None
    standard("NAME_MISMATCH_VERIFIED", "Verified name",
             f"contradiction: verified name {legal} agrees with none of the hit's names", name_missing,
             f"no contradiction: verified name {legal} agrees with a hit name")

    code = "LOCATION_MISMATCH"
    if code not in fired and code not in blocked and a.get("countries_contradict"):
        # The SOP's own exception: countries differ, but name and date of birth agree.
        row(code, "Location", BLOCKED,
            f"countries differ ({places(cust_countries)} against {places(hit_countries)}), but a country "
            f"difference does not clear a hit whose name and date of birth agree")
    else:
        standard(code, "Location",
                 f"contradiction: customer linked to {places(cust_countries)}, hit to {places(hit_countries)}, none shared",
                 "the customer has no country on file" if not cust_countries
                 else None if hit_countries else "the hit has no country on file",
                 f"no contradiction: both are linked to {places(a.get('common_countries') or [])}")

    same = cand.get("decision") == "SAME_ENTITY"
    title = "Confirm"
    code = cand.get("reason_code") if same else ("NAME_LOCATION_MATCH" if company else "NAME_DOB_MATCH")
    common = places(a.get("common_countries") or [])
    agree = lambda flag: "agrees" if a.get(flag) else "does not agree"   # noqa: E731
    if same:
        note = {"NAME_DOB_LOCATION_MATCH": f"confirmed: name, date of birth and country ({common}) agree",
                "NAME_DOB_MATCH": "confirmed: name and date of birth agree; no country to compare",
                "NAME_LOCATION_MATCH": f"confirmed: name and country ({common}) agree"}.get(code, "confirmed: the facts agree")
        row(code, title, FIRED, note)
    elif fired:
        row(code, title, NO, "not confirmed: a contradiction clears the hit")
    elif "CONFIRMATION" in blocked:
        row(code, title, BLOCKED, "the facts agree but cannot be relied on: " + blocked["CONFIRMATION"])
    elif blocked:
        row(code, title, NO, "not confirmed: a contradiction was seen")
    elif not a.get("name_usable", True):
        row(code, title, NOT_APPLICABLE, "the names cannot be compared part by part")
    elif company:
        if not cust_countries or not hit_countries:
            row(code, title, NOT_APPLICABLE, "no country on file for the " + ("hit" if cust_countries else "customer"))
        else:
            row(code, title, NO, f"not confirmed: name {agree('name_agrees')}, country {agree('countries_agree')}")
    elif not dob:
        row(code, title, NOT_APPLICABLE, "customer date of birth unknown")
    elif not hit_dobs:
        row(code, title, NOT_APPLICABLE, "the hit gives no date of birth")
    elif a.get("name_agrees") and a.get("dob_agrees") and a.get("countries_contradict"):
        row(code, title, NO, "not confirmed: name and date of birth agree, but the countries differ")
    else:
        row(code, title, NO, f"not confirmed: name {agree('name_agrees')}, date of birth {agree('dob_agrees')}")
    return rows


# ---------------------------------------------------------------------------
# which facts decided the hit
# ---------------------------------------------------------------------------

def decisive(cand: dict) -> dict:
    """Which of this person's facts the decision rests on.

    A clear rests on the facts of every rule that fired. A confirmation rests
    on the name, the date of birth and the shared country. A review rests on
    what the output cites for it: the contradiction that could not be relied
    on; else the country both sides share; else, with no shared country, the
    customer's identity source (name and date of birth).
    """
    c, a = cand.get("customer") or {}, cand.get("assessment") or {}
    seen = set(a.get("fired") or []) | {b.get("rule") for b in a.get("blocked") or []}
    decision = cand.get("decision")
    person = a.get("kind") != "company"
    same = decision == "SAME_ENTITY"
    held = decision == "REVIEW" and a.get("name_agrees") and a.get("dob_agrees") and a.get("countries_contradict")
    legal_agrees = a.get("agreeing_customer_name") == c.get("legal_name")
    identity = decision == "REVIEW" and not seen and not a.get("common_countries")
    countries: set[str] = set()
    if "LOCATION_MISMATCH" in seen or held:
        countries |= set(c.get("countries") or [])
    if (same and a.get("countries_agree")) or (decision == "REVIEW" and not a.get("fired")):
        countries |= set(a.get("common_countries") or [])
    return {
        "name": "NAME_MISMATCH_VERIFIED" in seen or (same and legal_agrees) or identity,
        "dob": bool({"DOB_MISMATCH", "TEMPORAL_IMPOSSIBILITY"} & seen) or (same and person) or identity,
        "hit_dob": "DOB_MISMATCH" in seen or (same and person) or bool(held),
        "report": "TEMPORAL_IMPOSSIBILITY" in seen,
        "countries": countries,
    }


# ---------------------------------------------------------------------------
# free-text sources behind one hit
# ---------------------------------------------------------------------------

def sources_for(dec: dict, diag: dict, raw_hit: dict, notes: dict, results: dict, label) -> list[dict]:
    """Every free-text record a fact of this hit came from: the record id, the
    text, and for each fact the value read from it and where it sits."""
    hit = diag.get("hit") or {}
    hit_id = dec["hit_id"]
    out: list[dict] = []
    index: dict[tuple, dict] = {}

    def source(record_id, cand, side, kind, meta, text) -> dict:
        key = (record_id, cand)
        if key not in index:
            index[key] = {"id": record_id, "cand": cand, "side": side, "kind": kind, "meta": meta,
                          "text": text, "facts": []}
            out.append(index[key])
        return index[key]

    def note_source(note_id, cand):
        note = notes.get(note_id)
        if not note:
            return None
        channel = (note.get("channel") or "").strip().lower()
        kind = "KYC note" if channel == "kyc" else f"Support note ({channel})" if channel else "Note"
        return source(note_id, cand, "customer", kind, note.get("created_at") or "", note.get("text") or "")

    def result_source(result_id):
        r = results.get(result_id)
        if not r:
            return None
        text = f"{r.get('title') or ''}. {r.get('snippet') or ''}"      # as the system reads it
        return source(result_id, None, "hit", "Search result", r.get("source") or "", text)

    def fact(src, title, value, spans, is_decisive=False, qualifier=False):
        if src is not None:
            src["facts"].append({"label": title, "value": value, "spans": spans,
                                 "decisive": bool(is_decisive), "qualifier": qualifier})

    for ci, cand in enumerate(diag.get("candidates") or []):
        c = cand.get("customer") or {}
        d = decisive(cand)
        company = (cand.get("assessment") or {}).get("kind") == "company"
        nid = c.get("name_source_id") or ""
        if nid.startswith("NOTE-") and c.get("legal_name"):
            src = note_source(nid, ci)
            if src:
                fact(src, "Legal name", c["legal_name"], name_spans(src["text"], c["legal_name"]), d["name"])
        nid = c.get("dob_source_id") or ""
        if nid.startswith("NOTE-") and c.get("dob"):
            src = note_source(nid, ci)
            if src:
                fact(src, "Incorporation date" if company else "Date of birth", c["dob"],
                     date_spans(src["text"], c["dob"], "text"), d["dob"])
        for code, ids in (c.get("country_sources") or {}).items():
            for nid in ids:
                if nid.startswith("NOTE-"):
                    src = note_source(nid, ci)
                    if src:
                        fact(src, "Country", label(code), country_spans(src["text"], code, label.names),
                             code in d["countries"])
        for code, ids in (c.get("possible_country_sources") or {}).items():
            for nid in ids:
                if nid.startswith("NOTE-"):
                    src = note_source(nid, ci)
                    if src:
                        fact(src, "Country mentioned, not established", label(code),
                             country_spans(src["text"], code, label.names))
        gaps = list(c.get("identity_gaps") or []) + list(c.get("location_gaps") or [])
        gaps += [b.get("why") or "" for b in (cand.get("assessment") or {}).get("blocked") or []]
        for gap in gaps:
            for nid in RECORD_ID_RE.findall(gap):
                src = note_source(nid.upper(), ci) if nid.upper().startswith("NOTE-") else None
                if src and not any(f["label"] == "Could not be relied on" and f["value"] == gap for f in src["facts"]):
                    fact(src, "Could not be relied on", gap, [], True)

    hit_decisive = [decisive(cand) for cand in diag.get("candidates") or []]
    dob_decides = any(d["hit_dob"] for d in hit_decisive)
    report_decides = any(d["report"] for d in hit_decisive)
    dobs = list(hit.get("dobs") or [])
    profile = raw_hit.get("profile_notes") or ""

    if hit.get("dob_origin") == "notes" and dobs:
        paragraph = first_paragraph(profile)
        src = source(f"{hit_id}#profile_notes", None, "hit", "Hit profile notes", "first paragraph", paragraph)
        fact(src, "Date of birth", _or(dobs), birth_spans(paragraph, dobs), dob_decides)
    if hit.get("dob_origin") == "search":
        category = (hit.get("primary_category") or "").strip().lower()
        phrase = LISTING_PHRASE.get(category, OTHER_PHRASE)
        for rid in hit.get("dob_source_ids") or []:
            src = result_source(rid)
            if not src:
                continue
            fact(src, "Date of birth", _or(dobs), birth_spans(src["text"], dobs), dob_decides)
            spans = find_all(src["text"], phrase)
            named = []
            for code in hit.get("countries") or []:
                found = country_spans(src["text"], code, label.names)
                if found:
                    named.append(label(code))
                    spans += [tuple(s) for s in found]
            fact(src, "About this hit: same listing, same country",
                 phrase + (" · " + ", ".join(named) if named else ""), merge_spans(spans), qualifier=True)
    if hit.get("earliest_report_date"):
        line, span = report_line(profile, hit["earliest_report_date"])
        if line:
            src = source(f"{hit_id}#profile_notes:report", None, "hit", "Hit profile notes", "dated report", line)
            fact(src, "Earliest dated report", hit["earliest_report_date"], [span], report_decides)
    for gap in hit.get("dob_gaps") or []:
        ids = [i.upper() for i in RECORD_ID_RE.findall(gap)]
        if ids:
            for rid in ids:
                fact(result_source(rid), "Could not be read", gap, [], True)
        elif "profile notes" in gap and profile:
            src = source(f"{hit_id}#profile_notes", None, "hit", "Hit profile notes", "first paragraph",
                         first_paragraph(profile))
            fact(src, "Could not be read", gap, [], True)

    # A cited note or search result that no fact above accounts for is still shown.
    for eid in dec.get("evidence") or []:
        if eid.startswith("NOTE-") and not any(s["id"] == eid for s in out):
            fact(note_source(eid, None), "Cited as evidence", eid, [], True)
        if eid.startswith("SR-") and not any(s["id"] == eid for s in out):
            fact(result_source(eid), "Cited as evidence", eid, [], True)

    for src in out:
        src["text"] = clip(src["text"], src["facts"])
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

ALERT_FIELDS = ("alert_id", "screened_at", "account_ref", "login_handle", "email", "hit_ids")
HIT_FIELDS = ("hit_id", "alert_id", "match_score", "entity_type", "name", "best_matching_name", "aliases",
              "gender", "dobs", "place_of_birth", "life_status", "deceased_date", "nationality", "citizenship",
              "countries", "categories", "primary_category", "subcategories", "position_or_allegation")


def wanted_ids(decisions: list[dict], diagnostics: list[dict]) -> tuple[set, set]:
    blob = json.dumps([decisions, diagnostics])
    ids = {i.upper() for i in RECORD_ID_RE.findall(blob)}
    return {i for i in ids if i.startswith("NOTE-")}, {i for i in ids if i.startswith("SR-")}


def pick(path: Path, key: str, wanted: set) -> dict:
    """The rows of a JSONL file whose ``key`` is in ``wanted`` (streamed)."""
    out = {}
    if not wanted or not path.exists():
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            if key not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get(key) in wanted:
                out[row[key]] = row
    return out


def build(args) -> int:
    decisions_path, diagnostics_path = Path(args.decisions), Path(args.diagnostics)
    data_dir, out_path = Path(args.data), Path(args.out)
    review_path = Path(args.llm_review)
    warnings: list[str] = []

    if not decisions_path.exists():
        raise SystemExit(f"{decisions_path} not found.")
    if not diagnostics_path.exists():
        raise SystemExit(f"{diagnostics_path} not found. It is written by the system's optional third argument:\n"
                         f"  python system/run {data_dir} {decisions_path} {diagnostics_path}")

    before = {p: p.stat().st_mtime for p in (decisions_path, diagnostics_path)}
    decisions = read_jsonl(decisions_path)
    diagnostics = read_jsonl(diagnostics_path)
    inputs = {"decisions": fingerprint(decisions_path), "diagnostics": fingerprint(diagnostics_path), "llm_review": None}

    load_readers(ROOT / "system" / "src")
    warnings += Readers.problems

    diag_by_hit = {d.get("hit_id"): d for d in diagnostics}
    out_of_sync = [d["hit_id"] for d in decisions
                   if d["hit_id"] not in diag_by_hit
                   or (diag_by_hit[d["hit_id"]].get("decision"), diag_by_hit[d["hit_id"]].get("reason_code"))
                   != (d.get("decision"), d.get("reason_code"))]
    if out_of_sync:
        warnings.append(f"{len(out_of_sync)} hit(s) differ between {decisions_path.name} and "
                        f"{diagnostics_path.name} (first: {out_of_sync[0]}); the files are from different runs")

    alerts_raw = {a["alert_id"]: a for a in read_jsonl(data_dir / "alerts.jsonl")}
    hits_raw = {h["hit_id"]: h for h in read_jsonl(data_dir / "hits.jsonl")}
    note_ids, result_ids = wanted_ids(decisions, diagnostics)
    notes = pick(data_dir / "notes.jsonl", "note_id", note_ids)
    results = pick(data_dir / "search_results.jsonl", "result_id", result_ids)

    # ISO2 -> country name, from the hits' own cards; the system's table fills the rest.
    names: dict[str, str] = {}
    for d in diagnostics:
        h = d.get("hit") or {}
        for code, name in zip(h.get("countries") or [], h.get("country_names") or []):
            names.setdefault(code, name)

    def label(code: str) -> str:
        if code not in names and Readers.countries is not None:
            try:
                names[code] = Readers.countries.display(code)
            except Exception:
                pass
        name = names.get(code)
        return f"{name} ({code})" if name and name != code else code
    label.names = names

    def country_name(code: str) -> str:
        label(code)                       # fills ``names`` from the system's table when needed
        return names.get(code, code)

    alerts = {}
    for aid, a in alerts_raw.items():
        row = {k: a.get(k) for k in ALERT_FIELDS}
        row["customer"] = {k: (a.get("customer") or {}).get(k) for k in ("name", "entity_type", "dob", "country", "city")}
        alerts[aid] = row
    hits = {hid: {k: h.get(k) for k in HIT_FIELDS} for hid, h in hits_raw.items()}

    derived = {}
    stats = {"sources": 0, "facts": 0, "located": 0, "decisive_hits": 0}
    not_located: list[str] = []
    for dec in decisions:
        hid = dec["hit_id"]
        diag = diag_by_hit.get(hid) or {}
        hit = diag.get("hit") or {}
        screened_at = (alerts_raw.get(dec.get("alert_id")) or {}).get("screened_at")
        try:
            sources = sources_for(dec, diag, hits_raw.get(hid) or {}, notes, results, label)
        except Exception as e:  # one odd record must not stop the build
            warnings.append(f"{hid}: source text could not be assembled ({type(e).__name__}: {e})")
            sources = []
        rules = [rules_for(cand, hit, screened_at, country_name) for cand in diag.get("candidates") or []]
        flag = any(f["decisive"] and not f["qualifier"] for s in sources for f in s["facts"])
        derived[hid] = {"rules": rules, "sources": sources, "free_text_decisive": flag}
        stats["sources"] += len(sources)
        stats["decisive_hits"] += flag
        for s in sources:
            for f in s["facts"]:
                if f["label"] in ("Could not be relied on", "Could not be read", "Cited as evidence"):
                    continue
                stats["facts"] += 1
                if f["spans"]:
                    stats["located"] += 1
                else:
                    not_located.append(f"{hid} {s['id']} {f['label']} = {f['value']}")

    llm_review = {}
    if review_path.exists():
        inputs["llm_review"] = fingerprint(review_path)
        for row in read_jsonl(review_path):
            if isinstance(row, dict) and row.get("hit_id"):
                llm_review.setdefault(row["hit_id"], []).append(row)

    for p, mtime in before.items():
        if p.stat().st_mtime != mtime:
            warnings.append(f"{p.name} changed while it was being read; build again")

    data = {
        "meta": {"inputs": inputs, "warnings": warnings, "stats": stats,
                 "readers": "system" if not Readers.problems else "built-in fallback for some readers"},
        "country_names": dict(sorted(names.items())),
        "decisions": decisions,
        "diagnostics": diag_by_hit,
        "alerts": alerts,
        "hits": hits,
        "derived": derived,
        "llm_review": llm_review,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("// Generated by tools/build_ui_data.py. Do not edit; rebuild instead.\n")
        f.write("window.SCREENING_DATA = ")
        json.dump(data, f, ensure_ascii=True, separators=(",", ":"))
        f.write(";\n")
    os.replace(tmp, out_path)

    counts: dict[str, int] = {}
    for d in decisions:
        counts[d.get("decision")] = counts.get(d.get("decision"), 0) + 1
    print(f"wrote {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")
    print(f"  {len(decisions)} hits: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"  decisions   {inputs['decisions']['modified']}  sha1 {inputs['decisions']['sha1']}")
    print(f"  diagnostics {inputs['diagnostics']['modified']}  sha1 {inputs['diagnostics']['sha1']}")
    print(f"  AI review   {'embedded for ' + str(len(llm_review)) + ' hits' if inputs['llm_review'] else 'none (no ' + review_path.name + ')'}")
    print(f"  free text   {stats['sources']} source records, {stats['located']} of {stats['facts']} extracted values "
          f"located in their text; {stats['decisive_hits']} hits rest on a free-text fact")
    for line in not_located[:args.show_missing]:
        print(f"    not located: {line}")
    if len(not_located) > args.show_missing:
        print(f"    ... and {len(not_located) - args.show_missing} more (--show-missing N)")
    for w in warnings:
        print(f"  WARNING: {w}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Embed the screening output into ui/data.js for ui/index.html.")
    p.add_argument("--decisions", default=str(ROOT / "output" / "dev.jsonl"))
    p.add_argument("--diagnostics", default=str(ROOT / "output" / "dev.diagnostics.jsonl"))
    p.add_argument("--llm-review", default=str(ROOT / "output" / "dev.llm_review.jsonl"))
    p.add_argument("--data", default=str(ROOT / "dev"), help="data folder (alerts, hits, notes, search results)")
    p.add_argument("--out", default=str(ROOT / "ui" / "data.js"))
    p.add_argument("--show-missing", type=int, default=5, help="how many unlocated values to list")
    return build(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
