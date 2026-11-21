"""The identity rules of POLICY.md (principles 6-8) as code.

Decision half. Pure functions: a fact card in, a decision out. No file
reading, no data loading, no model.

Clear only on a contradiction, confirm only on agreement, otherwise REVIEW.
Partial dates clear only when the contradiction holds under every completion.

`decide(card, variants)` returns (Decision, Assessment): the Assessment is what
the rules looked at, which explain.py turns into evidence and the reason.
`decide_hit(...)` handles several customer candidates for one hit.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from typing import Optional

from dates import age_bounds_at, parse_date
from names import EMPTY_VARIANTS, normalize_name, names_agree
from schema import COMPANY, PERSON, CustomerFacts, Decision, FactCard, HitFacts

UNDER_AGE = 16          # younger than 16 at the earliest dated report -> TEMPORAL_IMPOSSIBILITY
YEAR_TOLERANCE = 1      # birth years more than 1 apart -> contradiction
MIN_NAME_PARTS = 2      # an individual's name with fewer real parts can neither confirm nor clear


# --- dates -------------------------------------------------------------------

def parse_partial(d: Optional[str]) -> Optional[tuple[int, Optional[int], Optional[int]]]:
    """'1985' -> (1985, None, None); '1985-03-12' -> (1985, 3, 12); unknown -> None."""
    p = parse_date(d)
    return (p.year, p.month, p.day) if p else None


def _earliest(p) -> tuple[int, int, int]:
    return p[0], p[1] or 1, p[2] or 1


def _latest(p) -> tuple[int, int, int]:
    month = p[1] or 12
    return p[0], month, p[2] or calendar.monthrange(p[0], month)[1]


def certainly_before(a: Optional[str], b: Optional[str]) -> bool:
    """a < b under every completion of both partial dates. Unknown -> False."""
    pa, pb = parse_partial(a), parse_partial(b)
    return bool(pa and pb) and _latest(pa) < _earliest(pb)


def _one_contradicts(c, h) -> bool:
    if abs(c[0] - h[0]) > YEAR_TOLERANCE:
        return True
    if c[0] == h[0] and c[1] and h[1]:
        return c[1] != h[1] or bool(c[2] and h[2] and c[2] != h[2])
    return False


def _one_agrees(c, h) -> bool:
    return c[0] == h[0] and not (c[1] and h[1] and c[1] != h[1]) and not (c[2] and h[2] and c[2] != h[2])


def _hit_dates(hit_dobs: list[str]) -> list:
    return [p for p in (parse_partial(d) for d in hit_dobs) if p]


def dob_contradicts(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    """EVERY hit DOB contradicts the customer's. Unknown on either side -> False."""
    c, hs = parse_partial(cust_dob), _hit_dates(hit_dobs)
    return bool(c and hs) and all(_one_contradicts(c, h) for h in hs)


def dob_agrees(cust_dob: Optional[str], hit_dobs: list[str]) -> bool:
    """SOME hit DOB has the same year and equal month/day wherever both give one."""
    c = parse_partial(cust_dob)
    return bool(c) and any(_one_agrees(c, h) for h in _hit_dates(hit_dobs))


def oldest_age_if_too_young(dob: Optional[str], report: Optional[str]) -> Optional[int]:
    """Oldest possible age at the report when it is certainly under 16, else None."""
    d, r = parse_date(dob), parse_date(report)
    if not (d and r):
        return None
    oldest = age_bounds_at(d, r)[1]
    return oldest if oldest < UNDER_AGE else None


# --- names and countries -------------------------------------------------------

def _is_company(card: FactCard) -> bool:
    return COMPANY in (card.customer.entity_type, card.hit.entity_type)


def _name_counts(name: Optional[str], card: FactCard, variants) -> bool:
    """Rule 8: an individual's name with fewer than two real parts cannot confirm or clear."""
    if card.customer.entity_type != PERSON:
        return bool(normalize_name(name, True, variants))
    return len(normalize_name(name, False, variants)) >= MIN_NAME_PARTS


def agreeing_names(card: FactCard, variants=EMPTY_VARIANTS) -> Optional[tuple[str, str]]:
    """(customer name, hit name) for the first agreeing pair: legal name first,
    then the customer's other names (aliases count for agreement only)."""
    company = _is_company(card)
    for cn in [card.customer.legal_name] + list(card.customer.other_names):
        if not _name_counts(cn, card, variants):
            continue
        for hn in card.hit.names:
            if names_agree(cn, hn, variants, company):
                return cn, hn
    return None


def name_agrees(card: FactCard, variants=EMPTY_VARIANTS) -> bool:
    return agreeing_names(card, variants) is not None


def verified_name_mismatch(card: FactCard, variants=EMPTY_VARIANTS) -> bool:
    """The VERIFIED legal name agrees with none of the hit's names. A declared
    name, or an individual's name with fewer than two real parts, never clears."""
    c = card.customer
    if not (c.name_verified and card.hit.names and _name_counts(c.legal_name, card, variants)):
        return False
    company = _is_company(card)
    return not any(names_agree(c.legal_name, hn, variants, company) for hn in card.hit.names)


def countries_agree(card: FactCard) -> bool:
    return bool(set(card.customer.countries) & set(card.hit.countries))


def countries_contradict(card: FactCard) -> bool:
    cc, hc = set(card.customer.countries), set(card.hit.countries)
    return bool(cc and hc) and not (cc & hc)


# --- assessment and rules ------------------------------------------------------

@dataclass
class Assessment:
    """Everything the rules looked at, kept for the explanation (explain.py)."""
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
    fired: list[str] = field(default_factory=list)   # every clear rule that holds, in rule order


def assess(card: FactCard, variants=EMPTY_VARIANTS) -> Assessment:
    c, h = card.customer, card.hit
    a = Assessment()
    a.type_mismatch = c.entity_type != h.entity_type
    a.name_usable = any(_name_counts(n, card, variants) for n in [c.legal_name] + list(c.other_names))
    pair = agreeing_names(card, variants)
    if pair:
        a.name_agrees, (a.agreeing_customer_name, a.agreeing_hit_name) = True, pair
    a.verified_mismatch = verified_name_mismatch(card, variants)
    a.dob_agrees = dob_agrees(c.dob, h.dobs)
    a.dob_contradicts = dob_contradicts(c.dob, h.dobs)
    a.common_countries = sorted(set(c.countries) & set(h.countries))
    a.countries_agree = countries_agree(card)
    a.countries_contradict = countries_contradict(card)
    if c.entity_type == PERSON:
        a.too_young_age = oldest_age_if_too_young(c.dob, h.earliest_report_date)
    else:
        a.incorporated_after = certainly_before(h.earliest_report_date, c.dob)
    a.deceased = certainly_before(h.date_of_death, card.screened_at)

    for code, holds in [
        ("ENTITY_TYPE_MISMATCH", a.type_mismatch),
        ("DECEASED", a.deceased),
        ("TEMPORAL_IMPOSSIBILITY", a.too_young_age is not None or a.incorporated_after),
        ("DOB_MISMATCH", a.dob_contradicts),
        ("NAME_MISMATCH_VERIFIED", a.verified_mismatch),
        # A country difference never clears a hit whose name and DOB agree.
        ("LOCATION_MISMATCH", a.countries_contradict and not (a.name_agrees and a.dob_agrees)),
    ]:
        if holds:
            a.fired.append(code)
    return a


def decide(card: FactCard, variants=EMPTY_VARIANTS) -> tuple[Decision, Assessment]:
    """One customer candidate against one hit. Evidence and explanation are
    left empty here; explain.py fills them from the Assessment."""
    a = assess(card, variants)

    def result(decision: str, code: str):
        return Decision(alert_id=card.alert_id, hit_id=card.hit_id, decision=decision, reason_code=code,
                        resolved_customer_id=card.customer.customer_id), a

    if a.fired:                                   # first clear rule in order wins
        return result("DIFFERENT_ENTITY", a.fired[0])
    if card.customer.entity_type == PERSON and a.name_agrees and a.dob_agrees:
        if a.countries_contradict:                # name + DOB agree, country differs: never clear, never confirm
            return result("REVIEW", "INSUFFICIENT_DATA")
        if a.countries_agree:
            return result("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH")
        return result("SAME_ENTITY", "NAME_DOB_MATCH")
    if card.customer.entity_type == COMPANY and a.name_agrees and a.countries_agree:
        return result("SAME_ENTITY", "NAME_LOCATION_MATCH")
    return result("REVIEW", "INSUFFICIENT_DATA")


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
