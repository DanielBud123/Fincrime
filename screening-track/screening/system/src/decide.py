"""Step 5: the rules of POLICY.md, as code. Pure functions: a fact card in, a
decision out. No file reading.

Joined up with the decision half (branch decision/names-decide): its tests
(test_decide.py, test_names.py) run against this module, and decide_hit()
below is its interface, taken unchanged. Its rule order and partial-date
readings are the ones this module follows.

Clear only on a contradiction, confirm only on agreement, otherwise REVIEW.

The SOP rules, thresholds and order are untouched. What this module adds is a
gate in front of every clear: a contradiction clears a hit only when the facts
behind it are complete and certain. A contradiction that rests on an
incomplete or uncertain picture is recorded as *blocked* and the hit goes to
REVIEW; it is never confirmed either, because something does contradict it.
Clearing wrongly costs twenty times what a review costs.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Optional

from dates import PartialDate, age_bounds_at, parse_date
from names import EMPTY_VARIANTS, Variants, has_latin_parts, names_agree, names_certainly_disagree, normalize_name
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


def _dates(values) -> list[PartialDate]:
    out = [parse_date(v) for v in values or []]
    return [d for d in out if d]


def dob_contradicts(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    """Every hit DOB contradicts the customer's. Unknown never contradicts."""
    c, hs = parse_date(cust_dob), _dates(hit_dobs)
    if c is None or not hs:
        return False
    return all(one_dob_contradicts(c, h) for h in hs)


def dob_agrees(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    c, hs = parse_date(cust_dob), _dates(hit_dobs)
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
    _, oldest = age_bounds_at(d, r)
    return oldest if oldest < UNDER_AGE else None


def incorporated_after(inc: Optional[str], report: Optional[str]) -> bool:
    i, r = parse_date(inc), parse_date(report)
    return bool(i and r and certainly_before(r, i))


def dead_before(death: Optional[str], screened_at: Optional[str]) -> bool:
    d, s = parse_date(death), parse_date(screened_at)
    return bool(d and s and certainly_before(d, s))


# ---------------------------------------------------------------------------
# assessment
# ---------------------------------------------------------------------------

@dataclass
class Blocked:
    """A contradiction the facts show but that cannot be relied on to clear."""
    rule: str
    why: str


@dataclass
class Assessment:
    """Everything the rules looked at, kept for the explanation."""
    kind: str = PERSON                      # which rules apply: person or company
    name_usable: bool = True
    name_agrees: bool = False
    agreeing_hit_name: Optional[str] = None
    agreeing_customer_name: Optional[str] = None
    verified_mismatch: bool = False
    dob_agrees: bool = False
    dob_contradicts: bool = False
    countries_agree: bool = False
    countries_contradict: bool = False      # both sides have countries and none is shared
    common_countries: list[str] = field(default_factory=list)
    too_young_age: Optional[int] = None
    incorporated_after: bool = False
    deceased: bool = False
    type_mismatch: bool = False
    fired: list[str] = field(default_factory=list)       # every clear rule that holds, in SOP order
    blocked: list[Blocked] = field(default_factory=list)  # contradictions that could not be relied on


def _first(gaps: list[str], fallback: str) -> str:
    return gaps[0] if gaps else fallback


def assess(card: FactCard, variants: Variants = EMPTY_VARIANTS) -> Assessment:
    c, h = card.customer, card.hit
    a = Assessment()
    company = COMPANY in (c.entity_type, h.entity_type)
    a.kind = c.entity_type or h.entity_type or PERSON

    # Type: only two known, different types contradict.
    a.type_mismatch = bool(c.entity_type and h.entity_type and c.entity_type != h.entity_type)

    # Names. Rule 8: an individual customer whose names have fewer than two real
    # parts can be neither confirmed nor cleared on name. Read per name, as the
    # decision half does: only a customer name with two or more real parts can
    # agree, and a one-part verified name never clears. The parts are counted here
    # from the card's own names, not taken from a field a caller may leave unset.
    comparable = [hn for hn in h.names if has_latin_parts(hn)]
    own_company = c.entity_type == COMPANY
    usable_names = [n for n in [c.legal_name] + list(c.other_names)
                    if n and not (a.kind == PERSON and len(normalize_name(n, own_company, variants)) < 2)]
    a.name_usable = bool(comparable) and bool(usable_names)
    legal_agrees = False
    if a.name_usable:
        for cn in usable_names:
            hit = next((hn for hn in comparable if names_agree(cn, hn, variants, company)), None)
            if hit:
                a.name_agrees, a.agreeing_hit_name, a.agreeing_customer_name = True, hit, cn
                break
        legal_agrees = any(names_agree(c.legal_name, hn, variants, company) for hn in comparable)
        if c.name_verified and not legal_agrees:
            if not c.name_certain:
                a.blocked.append(Blocked("NAME_MISMATCH_VERIFIED", _first(c.identity_gaps, "the verified name is uncertain")))
            elif a.kind == PERSON and len(normalize_name(c.legal_name, False, variants)) < 2:
                a.blocked.append(Blocked("NAME_MISMATCH_VERIFIED", "the verified name has fewer than two real parts"))
            elif not all(names_certainly_disagree(c.legal_name, hn, variants, company) for hn in comparable):
                a.blocked.append(Blocked("NAME_MISMATCH_VERIFIED",
                                         "the names agree under another way of writing them"))
            else:
                a.verified_mismatch = True

    # Date of birth.
    a.dob_agrees = dob_agrees(c.dob, h.dobs)
    if dob_contradicts(c.dob, h.dobs):
        if not c.dob_certain:
            a.blocked.append(Blocked("DOB_MISMATCH", _first(c.identity_gaps, "the customer's date of birth is uncertain")))
        elif not h.dobs_complete:
            a.blocked.append(Blocked("DOB_MISMATCH", _first(h.dob_gaps, "the hit may give another date of birth")))
        else:
            a.dob_contradicts = True

    # Countries.
    cc, hc = set(c.countries), set(h.countries)
    a.common_countries = sorted(cc & hc)
    a.countries_agree = bool(a.common_countries)
    a.countries_contradict = bool(cc and hc and not a.common_countries)
    location_fires = False
    if a.countries_contradict and not (a.name_agrees and a.dob_agrees):
        maybe = sorted(set(c.possible_countries) & hc)
        if not c.countries_complete:
            a.blocked.append(Blocked("LOCATION_MISMATCH", _first(c.location_gaps, "a country tied to the customer may be missing")))
        elif not h.countries_complete:
            a.blocked.append(Blocked("LOCATION_MISMATCH", _first(h.country_gaps, "a country tied to the hit could not be read")))
        elif maybe:
            sources = sorted({s for code in maybe for s in c.possible_country_sources.get(code, [])})
            a.blocked.append(Blocked("LOCATION_MISMATCH",
                                     f"{', '.join(sources) or 'a record'} mentions a country the hit is tied to"))
        else:
            location_fires = True

    # Time.
    young = too_young_at(c.dob, h.earliest_report_date) if a.kind == PERSON else None
    late = incorporated_after(c.dob, h.earliest_report_date) if a.kind == COMPANY else False
    if young is not None or late:
        if not c.dob_certain:
            a.blocked.append(Blocked("TEMPORAL_IMPOSSIBILITY", _first(c.identity_gaps, "the customer's date is uncertain")))
        else:
            a.too_young_age, a.incorporated_after = young, late
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
    if location_fires:
        a.fired.append("LOCATION_MISMATCH")
    return a


# ---------------------------------------------------------------------------
# the rules, in order
# ---------------------------------------------------------------------------

def decide(card: FactCard, variants: Variants = EMPTY_VARIANTS) -> tuple[Decision, Assessment]:
    """One customer candidate against one hit. Returns the decision without
    explanation/evidence (explain.py fills those) plus what was assessed."""
    a = assess(card, variants)
    c = card.customer

    def d(decision, code):
        return Decision(alert_id=card.alert_id, hit_id=card.hit_id, decision=decision, reason_code=code,
                        resolved_customer_id=c.customer_id), a

    if a.fired:                       # the first clear rule in SOP order gives the code
        return d("DIFFERENT_ENTITY", a.fired[0])
    if a.blocked:                     # something contradicts, but not reliably: neither clear nor confirm
        return d("REVIEW", "INSUFFICIENT_DATA")
    person_match = a.kind == PERSON and a.name_agrees and a.dob_agrees and not a.countries_contradict
    company_match = a.kind == COMPANY and a.name_agrees and a.countries_agree
    if (person_match or company_match) and c.identity_conflict:
        # The facts in hand agree, but a check we could not use says otherwise.
        a.blocked.append(Blocked("CONFIRMATION", _first(c.identity_gaps, "the customer's identity is in doubt")))
        return d("REVIEW", "INSUFFICIENT_DATA")
    if person_match:
        return d("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH" if a.countries_agree else "NAME_DOB_MATCH")
    if company_match:
        return d("SAME_ENTITY", "NAME_LOCATION_MATCH")
    return d("REVIEW", "INSUFFICIENT_DATA")


# ---------------------------------------------------------------------------
# several people: the decision-half interface (from decision/names-decide)
# ---------------------------------------------------------------------------

def decide_hit(alert_id: str, hit: HitFacts, candidates: list[CustomerFacts], screened_at: Optional[str],
               variants=EMPTY_VARIANTS) -> Decision:
    """One hit against every person who fits the alert (candidates ordered by
    link strength). No candidate -> REVIEW with no customer. Several people ->
    the shared decision, or REVIEW / AMBIGUOUS_CUSTOMER_RECORD when they differ;
    either way the customer record is AMBIGUOUS (POLICY.md principle 3)."""
    from explain import explain, explain_ambiguous   # explain imports Assessment from here

    if not candidates:
        return Decision(alert_id=alert_id, hit_id=hit.hit_id, decision="REVIEW", reason_code="INSUFFICIENT_DATA",
                        evidence_ids=list(hit.source_ids), resolved_customer_id=None,
                        explanation="No customer record could be resolved for this alert, so the hit cannot be "
                                    "compared with anyone and is left for a human to review.")
    results = []
    for cust in candidates:
        card = FactCard(alert_id=alert_id, hit_id=hit.hit_id, screened_at=screened_at, customer=cust, hit=hit)
        results.append((explain(card, *decide(card, variants)), card))
    if len(results) == 1:
        return results[0][0]
    return explain_ambiguous(alert_id, hit.hit_id, results)
