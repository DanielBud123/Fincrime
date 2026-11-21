"""Step 5: the rules of POLICY.md, as code. Pure functions: a fact card in, a
decision out. No file reading.

PROVISIONAL: this file belongs to the decision half; it follows POLICY.md
principles 6-8 and the check order agreed in the team brief. Replace with the
teammate's version at join-up if theirs differs.

Clear only on a contradiction, confirm only on agreement, otherwise REVIEW.
Partial dates: a clear needs the contradiction to hold under every completion.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Optional

from dates import PartialDate, age_bounds_at, parse_date
from names import EMPTY_VARIANTS, Variants, names_agree
from schema import COMPANY, PERSON, CustomerFacts, Decision, FactCard, HitFacts

UNDER_AGE = 16          # POLICY.md principle 6: younger than 16 at the earliest dated report
YEAR_TOLERANCE = 1      # birth year more than 1 year outside the hit's -> contradiction


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------

def _bounds(d: PartialDate) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    early = (d.year, d.month or 1, d.day or 1)
    late = (d.year, d.month or 12, d.day or calendar.monthrange(d.year, d.month or 12)[1])
    return early, late


def one_dob_contradicts(cust: PartialDate, hit: PartialDate) -> bool:
    if abs(cust.year - hit.year) > YEAR_TOLERANCE:
        return True
    if cust.year == hit.year and cust.month is not None and hit.month is not None:
        if cust.month != hit.month:
            return True
        if cust.day is not None and hit.day is not None and cust.day != hit.day:
            return True
    return False


def one_dob_agrees(cust: PartialDate, hit: PartialDate) -> bool:
    if cust.year != hit.year:
        return False
    if cust.month is not None and hit.month is not None and cust.month != hit.month:
        return False
    if cust.day is not None and hit.day is not None and cust.day != hit.day:
        return False
    return True


def dob_contradicts(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    """Every hit DOB contradicts the customer's. Unknown never contradicts."""
    c = parse_date(cust_dob)
    hs = [parse_date(h) for h in hit_dobs]
    hs = [h for h in hs if h]
    if c is None or not hs:
        return False
    return all(one_dob_contradicts(c, h) for h in hs)


def dob_agrees(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    c = parse_date(cust_dob)
    hs = [parse_date(h) for h in hit_dobs]
    hs = [h for h in hs if h]
    if c is None or not hs:
        return False
    return any(one_dob_agrees(c, h) for h in hs)


def certainly_before(a: PartialDate, b: PartialDate) -> bool:
    """True when a < b under every completion of the partial dates."""
    return _bounds(a)[1] < _bounds(b)[0]


def too_young_at(dob: Optional[str], report: Optional[str]) -> Optional[int]:
    """Oldest possible age at the report if it is certainly under 16, else None."""
    d, r = parse_date(dob), parse_date(report)
    if d is None or r is None:
        return None
    youngest, oldest = age_bounds_at(d, r)
    return oldest if oldest < UNDER_AGE else None


def incorporated_after(inc: Optional[str], report: Optional[str]) -> bool:
    i, r = parse_date(inc), parse_date(report)
    return bool(i and r and certainly_before(r, i))


def dead_before(death: Optional[str], screened_at: Optional[str]) -> bool:
    d, s = parse_date(death), parse_date(screened_at)
    return bool(d and s and certainly_before(d, s))


# ---------------------------------------------------------------------------
# name / country helpers
# ---------------------------------------------------------------------------

@dataclass
class Assessment:
    """Everything the rules looked at, kept for the explanation."""
    name_usable: bool = True
    name_agrees: bool = False
    agreeing_hit_name: Optional[str] = None
    agreeing_customer_name: Optional[str] = None
    verified_mismatch: bool = False
    dob_agrees: bool = False
    dob_contradicts: bool = False
    countries_agree: bool = False
    countries_contradict: bool = False
    common_countries: list[str] = field(default_factory=list)
    too_young_age: Optional[int] = None
    incorporated_after: bool = False
    deceased: bool = False
    type_mismatch: bool = False
    fired: list[str] = field(default_factory=list)   # every clear rule that holds, in SOP order


def assess(card: FactCard, variants: Variants = EMPTY_VARIANTS) -> Assessment:
    c, h = card.customer, card.hit
    a = Assessment()
    company = c.entity_type == COMPANY or h.entity_type == COMPANY
    a.type_mismatch = c.entity_type != h.entity_type

    # Rule 8: an individual customer whose names have fewer than two real parts
    # can be neither confirmed nor cleared on name.
    a.name_usable = not (c.entity_type == PERSON and c.real_name_parts < 2)
    if a.name_usable:
        for hn in h.names:
            if names_agree(c.legal_name, hn, variants, company):
                a.name_agrees, a.agreeing_hit_name, a.agreeing_customer_name = True, hn, c.legal_name
                break
        if not a.name_agrees:
            for on in c.other_names:
                for hn in h.names:
                    if names_agree(on, hn, variants, company):
                        a.name_agrees, a.agreeing_hit_name, a.agreeing_customer_name = True, hn, on
                        break
                if a.name_agrees:
                    break
        legal_agrees = any(names_agree(c.legal_name, hn, variants, company) for hn in h.names)
        a.verified_mismatch = bool(c.name_verified and h.names and not legal_agrees)

    a.dob_agrees = dob_agrees(c.dob, h.dobs)
    a.dob_contradicts = dob_contradicts(c.dob, h.dobs)

    cc, hc = set(c.countries), set(h.countries)
    a.common_countries = sorted(cc & hc)
    a.countries_agree = bool(cc and hc and a.common_countries)
    a.countries_contradict = bool(cc and hc and not a.common_countries)

    if c.entity_type == PERSON:
        a.too_young_age = too_young_at(c.dob, h.earliest_report_date)
    else:
        a.incorporated_after = incorporated_after(c.dob, h.earliest_report_date)
    a.deceased = dead_before(h.date_of_death, card.screened_at)

    if a.type_mismatch:
        a.fired.append("ENTITY_TYPE_MISMATCH")
    if a.deceased:
        a.fired.append("DECEASED")
    if a.too_young_age is not None or a.incorporated_after:
        a.fired.append("TEMPORAL_IMPOSSIBILITY")
    if a.dob_contradicts:
        a.fired.append("DOB_MISMATCH")
    if a.verified_mismatch:
        a.fired.append("NAME_MISMATCH_VERIFIED")
    if a.countries_contradict and not (a.name_agrees and a.dob_agrees):
        a.fired.append("LOCATION_MISMATCH")
    return a


# ---------------------------------------------------------------------------
# the rules, in order
# ---------------------------------------------------------------------------

def decide(card: FactCard, variants: Variants = EMPTY_VARIANTS) -> tuple[Decision, Assessment]:
    """One customer candidate against one hit. Returns the decision without
    explanation/evidence (explain.py fills those) plus what was assessed."""
    a = assess(card, variants)
    c, h = card.customer, card.hit

    def d(decision, code):
        return Decision(alert_id=card.alert_id, hit_id=card.hit_id, decision=decision, reason_code=code,
                        resolved_customer_id=c.customer_id), a

    if a.type_mismatch:
        return d("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH")
    if a.deceased:
        return d("DIFFERENT_ENTITY", "DECEASED")
    if a.too_young_age is not None or a.incorporated_after:
        return d("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY")
    if a.dob_contradicts:
        return d("DIFFERENT_ENTITY", "DOB_MISMATCH")
    if a.verified_mismatch:
        return d("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED")
    if a.countries_contradict and not (a.name_agrees and a.dob_agrees):
        return d("DIFFERENT_ENTITY", "LOCATION_MISMATCH")
    if c.entity_type == PERSON and a.name_agrees and a.dob_agrees:
        if a.countries_contradict:
            return d("REVIEW", "INSUFFICIENT_DATA")
        if a.countries_agree:
            return d("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")
        return d("SAME_ENTITY", "NAME_DOB_MATCH")
    if c.entity_type == COMPANY and a.name_agrees and a.countries_agree:
        return d("SAME_ENTITY", "NAME_LOCATION_MATCH")
    return d("REVIEW", "INSUFFICIENT_DATA")
