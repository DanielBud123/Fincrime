"""Step 6: evidence and a reason an analyst can read.

Evidence names only the records that decided the hit, the way the practice
labels do: a DOB mismatch cites the record that gave the customer's DOB (and
the search result that gave the hit's), a location mismatch cites every record
that contributed a customer country, a verified-name mismatch cites the check
behind the name. Hit facts come from the hit itself and are not cited, except
search results. The reason is two to four sentences with the hit's own facts,
and it says plainly when a contradiction was seen but could not be relied on.
"""
from __future__ import annotations

from countries import display
from decide import Assessment, Blocked
from schema import COMPANY, CustomerFacts, Decision, FactCard, HitFacts


def _join(items, word="and"):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {word} " + items[-1]


def _names(codes):
    return _join([display(c) for c in codes], "and") if codes else "no country"


def _kind(entity_type) -> str:
    return "company" if entity_type == COMPANY else "person"


def _hit_dobs_clause(h: HitFacts) -> str:
    """'...but the hit's <clause>.' with the hit's own facts."""
    if not h.dobs:
        return "profile gives no date of birth"
    if h.dob_origin == "field":
        return ("listed date of birth is " if len(h.dobs) == 1 else "listed dates of birth are ") + _join(h.dobs, "or")
    if h.dob_origin == "notes":
        return "profile notes put its birth year at " + _join(h.dobs, "or")
    if h.dob_origin == "search":
        return f"search results ({_join(h.dob_source_ids)}) put its birth year at " + _join(h.dobs, "or")
    return "date of birth is " + _join(h.dobs, "or")


def _country_evidence(c: CustomerFacts) -> list[str]:
    out = list(c.record_ids)
    for srcs in c.country_sources.values():
        for s in srcs:
            if s not in out:
                out.append(s)
    return out


def _dob_evidence(c: CustomerFacts, h: HitFacts) -> list[str]:
    out = [c.dob_source_id] if c.dob_source_id else []
    return out + [s for s in h.dob_source_ids if s not in out]


def _clear_sentence(code: str, c: CustomerFacts, h: HitFacts, a: Assessment, card: FactCard) -> tuple[str, list[str]]:
    """The sentence and evidence for one clear rule."""
    hit_name = a.agreeing_hit_name or (h.names[0] if h.names else "the hit")
    if code == "ENTITY_TYPE_MISMATCH":
        return (f"The customer {c.legal_name} is a {_kind(c.entity_type)} ({_join(c.record_ids)}) but the hit "
                f"{hit_name} is a {_kind(h.entity_type)}, so they cannot be the same entity.", list(c.record_ids))
    if code == "DECEASED":
        return (f"The hit's profile gives a date of death of {h.date_of_death}, before the customer "
                f"{c.legal_name} was screened on {card.screened_at}.",
                list(c.record_ids) + [f"{h.hit_id}#deceased_date"])
    if code == "TEMPORAL_IMPOSSIBILITY":
        if a.incorporated_after:
            text = (f"The customer was incorporated on {c.dob} ({c.dob_source_id}), after the hit's earliest "
                    f"dated report on {h.earliest_report_date}.")
        else:
            text = (f"The customer was born in {c.dob[:4]} ({c.dob_source_id}), so they were at most "
                    f"{a.too_young_age} when the hit's profile reports activity on {h.earliest_report_date}.")
        return text, list(c.record_ids) + [c.dob_source_id]
    if code == "DOB_MISMATCH":
        return (f"The customer's date of birth is {c.dob} ({c.dob_source_id}) but the hit's {_hit_dobs_clause(h)}.",
                _dob_evidence(c, h))
    if code == "NAME_MISMATCH_VERIFIED":
        return (f"The customer's verified name is {c.legal_name} ({c.name_source_id}), which does not match "
                f"the hit's name {_join(h.names[:3], 'or')}.", [c.name_source_id])
    if code == "LOCATION_MISMATCH":
        return (f"The customer is linked only to {_names(c.countries)} but the hit is linked only to "
                f"{_names(h.countries)}.", _country_evidence(c))
    return "", []


def _blocked_sentence(b: Blocked, c: CustomerFacts, h: HitFacts, card: FactCard) -> tuple[str, list[str]]:
    """What points to a different entity, and why it was not relied on."""
    if b.rule == "LOCATION_MISMATCH":
        return (f"The customer's records point to {_names(c.countries)} and the hit to {_names(h.countries)}, "
                f"but {b.why}, so the difference in country cannot clear the hit.", _country_evidence(c))
    if b.rule == "DOB_MISMATCH":
        return (f"The customer's date of birth {c.dob} ({c.dob_source_id}) differs from the hit's "
                f"{_join(h.dobs, 'or')}, but {b.why}, so it cannot clear the hit.", _dob_evidence(c, h))
    if b.rule == "NAME_MISMATCH_VERIFIED":
        return (f"The customer's verified name {c.legal_name} ({c.name_source_id}) does not match the hit's name "
                f"{_join(h.names[:2], 'or')}, but {b.why}, so the name cannot clear the hit.", [c.name_source_id])
    if b.rule == "CONFIRMATION":
        return (f"The customer's details on file agree with the hit, but {b.why}, so the match cannot be confirmed.",
                list(c.record_ids))
    if b.rule == "TEMPORAL_IMPOSSIBILITY":
        return (f"The customer's date {c.dob} ({c.dob_source_id}) would rule out the hit's earliest report on "
                f"{h.earliest_report_date}, but {b.why}, so it cannot clear the hit.", [c.dob_source_id])
    return "", []


def explain(card: FactCard, decision: Decision, a: Assessment) -> Decision:
    """Fill ``evidence_ids`` and ``explanation`` for a single-candidate decision."""
    c, h = card.customer, card.hit
    code = decision.reason_code
    hit_name = a.agreeing_hit_name or (h.names[0] if h.names else "the hit")
    sentences: list[str] = []
    evidence: list[str] = []

    def add_ev(ids):
        for i in ids:
            if i and i not in evidence:
                evidence.append(i)

    if decision.decision == "DIFFERENT_ENTITY":
        # The main rule first, then every other contradiction that also holds (the labels
        # accept any of them and cite the records of each).
        for fired in [code] + [f for f in a.fired if f != code]:
            text, ev = _clear_sentence(fired, c, h, a, card)
            if text:
                sentences.append(text)
                add_ev(ev)
    elif code in ("NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH"):
        add_ev(c.record_ids + _dob_evidence(c, h))
        sentences.append(f"The customer's date of birth {c.dob} ({c.dob_source_id}) agrees with the hit's "
                         f"{_join(h.dobs, 'or')}" + (f" ({_join(h.dob_source_ids)})" if h.dob_source_ids else "") + ".")
        if code == "NAME_DOB_LOCATION_MATCH":
            sentences.append(f"Both the customer and the hit are linked to {_names(a.common_countries)}.")
        else:
            sentences.append("No country is recorded on one side, so location could not be compared, "
                             "and nothing contradicts the match.")
        sentences.append(f"The customer's name {a.agreeing_customer_name} agrees with the hit's name {hit_name}.")
    elif code == "NAME_LOCATION_MATCH":
        add_ev(c.record_ids)
        for code_ in a.common_countries:
            add_ev(c.country_sources.get(code_, []))
        sentences.append(f"Both the customer and the hit are linked to {_names(a.common_countries)}.")
        sentences.append(f"The customer's name {a.agreeing_customer_name} agrees with the hit's name {hit_name}, "
                         f"and nothing contradicts the match.")
    elif a.blocked:
        # A contradiction was seen but rests on an incomplete or uncertain picture.
        for b in a.blocked[:2]:
            text, ev = _blocked_sentence(b, c, h, card)
            if text:
                sentences.append(text)
                add_ev(ev)
        if not evidence:
            add_ev([c.customer_id])
        sentences.append("Clearing on an uncertain fact would be unsafe, so the hit is left for a person to review.")
    else:  # REVIEW / INSUFFICIENT_DATA for one candidate
        # Cite what the reason states: the records behind the agreeing country; failing
        # that, the identity source and the record the link led to.
        for code_ in a.common_countries:
            add_ev(c.country_sources.get(code_, []))
        if not evidence:
            add_ev([c.name_source_id, c.dob_source_id, c.customer_id])
        if a.countries_agree:
            sentences.append(f"Both the customer and the hit are linked to {_names(a.common_countries)}.")
        elif a.countries_contradict:
            sentences.append(f"The customer is linked to {_names(c.countries)} and the hit to {_names(h.countries)}, "
                             f"but a country difference does not clear a hit whose name and date of birth agree.")
        else:
            sentences.append("Location cannot be compared: " +
                             ("the hit" if not h.countries else "the customer") + " has no country on file.")
        if a.name_agrees:
            sentences.append(f"The customer's name {a.agreeing_customer_name} agrees with the hit's name {hit_name}.")
        elif not a.name_usable:
            sentences.append(f"The customer's name {c.legal_name} cannot be compared with the hit's name part by "
                             f"part, so it can neither confirm nor clear the hit.")
        elif c.name_verified:
            sentences.append(f"The customer's verified name {c.legal_name} agrees with the hit's name {hit_name} only "
                             f"partially, which is not enough to clear or confirm.")
        else:
            sentences.append(f"The customer's declared name {c.legal_name} does not clearly agree with the hit's name "
                             f"{hit_name}, and a declared name cannot clear a hit.")
        if a.dob_agrees and a.countries_contradict:
            sentences.append(f"The date of birth {c.dob} ({c.dob_source_id}) agrees with the hit's, so the hit can be "
                             f"neither cleared nor confirmed.")
        elif not c.dob:
            sentences.append("The customer has no verified or declared date of birth, so the date of birth cannot be "
                             "compared and the hit can be neither cleared nor confirmed.")
        elif not h.dobs:
            sentences.append("Nothing in the customer's records contradicts the hit, and the date of birth cannot be "
                             "compared with it, so the hit can be neither cleared nor confirmed.")
        elif not a.dob_agrees and not a.dob_contradicts:
            sentences.append(f"The customer's date of birth {c.dob} ({c.dob_source_id}) is within a year of the hit's "
                             f"{_join(h.dobs, 'or')}, which neither agrees nor contradicts, so the hit can be neither "
                             f"cleared nor confirmed.")
        else:
            sentences.append("Nothing in the customer's records contradicts the hit and the agreement is not enough "
                             "to confirm it, so it can be neither cleared nor confirmed.")

    decision.evidence_ids = evidence
    decision.sentences = sentences[:4]
    decision.explanation = " ".join(decision.sentences)
    return decision


def explain_no_customer(alert_id: str, hit_id: str, screened_name: str, link: str) -> Decision:
    how = {"account": "its account reference", "login": "its login handle", "email": "its email address"}.get(link)
    why = (f"The alert's link ({how}) does not lead to any customer record" if how else
           f"No customer record fits the screened details for {screened_name}")
    return Decision(alert_id=alert_id, hit_id=hit_id, decision="REVIEW", reason_code="INSUFFICIENT_DATA",
                    evidence_ids=[], resolved_customer_id=None,
                    explanation=f"{why}, so the customer cannot be identified and the hit cannot be compared. "
                                f"It is left for a human to review.")


def explain_ambiguous(alert_id: str, hit_id: str, results: list[tuple[Decision, FactCard]]) -> Decision:
    """Several people fit the alert. Same decision for all -> give it; different
    decisions -> REVIEW / AMBIGUOUS_CUSTOMER_RECORD. Either way the customer
    record is AMBIGUOUS and the evidence covers every person."""
    decisions = {d.decision for d, _ in results}
    evidence: list[str] = []
    for d, _ in results:
        for e in d.evidence_ids:
            if e not in evidence:
                evidence.append(e)
    people = "; ".join(" + ".join(card.customer.record_ids) for _, card in results)
    if len(decisions) == 1:
        first = results[0][0]
        intro = (f"{len(results)} different people in the system of record fit the alert (records {people}), "
                 f"and each leads to the same decision.")
        body = " ".join(first.sentences[:3]) if first.sentences else first.explanation   # four sentences in all
        return Decision(alert_id=alert_id, hit_id=hit_id, decision=first.decision, reason_code=first.reason_code,
                        evidence_ids=evidence, resolved_customer_id="AMBIGUOUS",
                        explanation=f"{intro} {body}")
    outcomes = _join(sorted({f"{d.decision} ({d.reason_code})" for d, _ in results}), "and")
    return Decision(alert_id=alert_id, hit_id=hit_id, decision="REVIEW", reason_code="AMBIGUOUS_CUSTOMER_RECORD",
                    evidence_ids=evidence, resolved_customer_id="AMBIGUOUS",
                    explanation=f"{len(results)} different people in the system of record fit the alert (records "
                                f"{people}) and they lead to different decisions: {outcomes}. A human must decide "
                                f"which person the alert is about.")
