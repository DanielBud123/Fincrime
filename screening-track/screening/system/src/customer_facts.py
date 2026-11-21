"""Steps 2 and 3: merge a customer's records into one person and build the
customer side of the fact card, with the id of the record behind each fact.

Principle 3 (one person, one picture): records sharing a phone number AND the
same full date of birth are one person, and so are records whose approved
identity checks carry the same document number; this chains.

Principle 4 (verified beats declared): the most recent approved identity
check, whether a KYC row or an onboarding note, gives the legal name, date of
birth and document country. Rejected or expired checks are not evidence.

Countries tied to the customer: residence and nationality on every record,
the approved identity document, and the countries the notes say they lived in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from countries import codes_in_text, to_iso2, to_iso2_list
from dates import PartialDate, find_dates, parse_date
from load import Data, clean, is_company, normalize_email, normalize_phone
from names import normalize_name, strip_accents
from schema import COMPANY, PERSON, CustomerFacts

# ----------------------------------------------------------------------------
# Step 2: one person, one picture
# ----------------------------------------------------------------------------


def full_dob(data: Data, record_id: str) -> Optional[str]:
    d = parse_date(data.customers[record_id].get("dob"))
    return d.iso() if d and d.is_full else None


def approved_doc_numbers(data: Data, record_id: str) -> set[str]:
    out = set()
    for app in data.applicants_by_customer.get(record_id, []):
        for k in data.kyc_by_applicant.get(app, []):
            if is_approved(k.get("result")) and clean(k.get("document_number")):
                out.add(k["document_number"].strip().upper())
    return out


def merge_person(data: Data, seed: str) -> list[str]:
    """All record ids that are the same person as ``seed`` (seed first)."""
    person = [seed]
    seen = {seed}
    queue = [seed]
    while queue:
        rid = queue.pop(0)
        rec = data.customers[rid]
        linked: list[str] = []
        phone = normalize_phone(rec.get("phone"))
        dob = full_dob(data, rid)
        if phone and dob:
            for other in data.customers_by_phone.get(phone, []):
                if other != rid and full_dob(data, other) == dob:
                    linked.append(other)
        for doc in approved_doc_numbers(data, rid):
            linked.extend(o for o in data.customers_by_doc_number.get(doc, ()) if o != rid)
        for other in sorted(set(linked)):
            if other not in seen:
                seen.add(other)
                person.append(other)
                queue.append(other)
    return person


# ----------------------------------------------------------------------------
# Step 3: verified identity (KYC rows and KYC notes)
# ----------------------------------------------------------------------------

APPROVED_RESULTS = {"approved", "approve", "passed", "pass", "verified", "clear", "cleared", "success", "successful", "ok"}
NEGATIVE_RE = re.compile(
    r"\b(reject\w*|fail\w*|unable|could ?not|couldn't|cannot|can't|expired?|expiry|declin\w*|unsuccessful\w*|"
    r"not (?:be )?(?:verified|confirmed|validated|approved|matched?|successful)|mismatch\w*|inconclusive|pending|"
    r"incomplete|abandon\w*|refus\w*|denied|invalid|fraud\w*|suspicious|flagged)\b", re.I)
IDENTITY_RE = re.compile(
    r"\b(identity|id check|id verification|kyc|verif\w*|validat\w*|passport|national id|driving licen[cs]e|"
    r"identity card|id card|document|sumsub|veriff|persona|onfido|jumio|trulioo)\b", re.I)
CAPS_NAME_RE = re.compile(r"\b([A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]+(?:\.|\b)(?:[ \-][A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]*(?:\.|\b))+)")
CAPS_STOP = {"DOB", "ID", "KYC", "DATE", "OF", "BIRTH", "NAME", "N/A", "NA", "THE", "AND", "ON", "FOR", "VIA", "BY",
             "FROM", "USING", "IN", "AT", "TO", "A", "AN", "IS", "WAS", "PEP", "SOE", "US", "UK", "USA", "EU"}
TITLE_NAME_ANCHOR_RE = re.compile(
    r"(?:\bfor|\bof|\bholder|\bname(?: on document)?:?|\bshows|\bidentity of|\bverified|\bconfirmed|\bcleared|\bmatches)\s+"
    r"((?:[A-ZÀ-Ý][a-zà-ÿ'’\-]+\.?\s+){1,4}[A-ZÀ-Ý][A-Za-zà-ÿ'’\-]+)")
BIRTH_ANCHOR_RE = re.compile(r"\b(born|birth|dob|d\.o\.b\.?|date of birth|birth ?date|née?)\b", re.I)


def is_approved(result: Optional[str]) -> bool:
    return bool(result) and result.strip().lower() in APPROVED_RESULTS


@dataclass
class IdentityCheck:
    source_id: str
    kind: str                           # "kyc" | "note"
    date: Optional[PartialDate]
    approved: bool
    name: Optional[str] = None
    dob: Optional[PartialDate] = None
    country: Optional[str] = None       # ISO2 document country
    document_number: Optional[str] = None
    record_id: Optional[str] = None     # the customer record this check belongs to

    def sort_key(self):
        return ((self.date.iso() if self.date else "0000"), self.kind == "kyc", self.source_id)


def kyc_row_check(row: dict, record_id: str) -> IdentityCheck:
    return IdentityCheck(
        source_id=row["check_id"], kind="kyc", date=parse_date(row.get("checked_at")),
        approved=is_approved(row.get("result")),
        name=clean(row.get("verified_name")), dob=parse_date(row.get("verified_dob")),
        country=to_iso2(row.get("document_country")),
        document_number=(clean(row.get("document_number")) or "").upper() or None,
        record_id=record_id,
    )


def is_identity_note(note: dict) -> bool:
    if (note.get("channel") or "").strip().lower() in {"kyc", "onboarding", "identity", "verification"}:
        return True
    text = note.get("text") or ""
    return bool(IDENTITY_RE.search(text)) and bool(re.search(r"\b(identity|verif|validat|kyc|id check)", text, re.I))


def _name_from_note(text: str) -> Optional[str]:
    """The person's name in an identity note: the run of capitalised words.
    A note naming two different people is ambiguous and yields None (fail closed)."""
    names: list[str] = []
    for m in CAPS_NAME_RE.finditer(text):
        cand = m.group(1).strip(" .")
        words = [w for w in re.split(r"[ \-]", cand) if w]
        words = [w for w in words if w.strip(".") not in CAPS_STOP]
        if len(words) >= 2:
            name = " ".join(words)
            if name not in names:
                names.append(name)
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        parts = [set(normalize_name(n)) for n in names]
        if all(p & parts[0] for p in parts[1:]):   # the same person written twice
            return max(names, key=len)
        return None
    m = TITLE_NAME_ANCHOR_RE.search(text)
    if m:
        cand = m.group(1).strip()
        if len(normalize_name(cand)) >= 2 and not codes_in_text(cand):
            return cand
    return None


def _dob_from_note(text: str, created_at: Optional[PartialDate]) -> Optional[PartialDate]:
    """The birth date in an identity note. The check date is the one equal to
    the note's own date or sitting right after 'on'/'as of'/'dated'; what is
    left, when it is exactly one date, is the date of birth. Anything
    ambiguous is left unknown (fail closed)."""
    mentions = [m for m in find_dates(text) if m.date.month is not None]  # a DOB has at least a month
    if not mentions:
        return None
    # 1. A date right after a birth word, or inside brackets right after the name, is the DOB.
    for m in mentions:
        before = text[max(0, m.start - 40):m.start]
        if BIRTH_ANCHOR_RE.search(before) and not re.search(r"\b(on|as of|dated|at)\s*$", before, re.I):
            return m.date
        if re.search(r"\(\s*$", before) and text[m.end:m.end + 1] == ")":
            return m.date
    # 2. Otherwise drop the check date(s) and keep what is left if unambiguous.
    rest = []
    for m in mentions:
        before = text[max(0, m.start - 12):m.start]
        is_check = (created_at and m.date == created_at) or re.search(r"\b(on|as of|dated|at)\s*[:\-]?\s*$", before, re.I) \
            or re.search(r"\(\s*\w+\s*,\s*$", before)
        if not is_check:
            rest.append(m.date)
    rest = list(dict.fromkeys(rest))
    if len(rest) == 1:
        return rest[0]
    return None


def note_check(note: dict, record_id: str) -> IdentityCheck:
    text = note.get("text") or ""
    created = parse_date(note.get("created_at"))
    approved = not NEGATIVE_RE.search(text)
    countries = codes_in_text(text)
    return IdentityCheck(
        source_id=note["note_id"], kind="note", date=created, approved=approved,
        name=_name_from_note(text), dob=_dob_from_note(text, created),
        country=countries[0] if len(countries) == 1 else None, record_id=record_id,
    )


def identity_checks(data: Data, record_ids: list[str]) -> list[IdentityCheck]:
    checks: list[IdentityCheck] = []
    for rid in record_ids:
        for app in data.applicants_by_customer.get(rid, []):
            for row in data.kyc_by_applicant.get(app, []):
                checks.append(kyc_row_check(row, rid))
        email = normalize_email(data.customers[rid].get("email"))
        for note in data.notes_by_email.get(email, []) if email else []:
            if is_identity_note(note):
                checks.append(note_check(note, rid))
    checks.sort(key=IdentityCheck.sort_key, reverse=True)   # most recent first
    return checks


# ----------------------------------------------------------------------------
# Step 3: the customer's picture
# ----------------------------------------------------------------------------

RESIDENCE_RE = re.compile(
    r"(liv\w+|resid\w+|based|home|dwell\w*|household|domicil\w*|stay\w*|relocat\w*|moved|settl\w*|"
    r"life|career|employ\w+|work\w*|job|occupation|position|professional|located|location|inside|within|base|"
    r"address\w*|citizen\w*|national\w*|origin\w*|born|grew up|raised|from)", re.I)


def residence_countries(note: dict) -> list[str]:
    """Countries a non-identity note says the customer lived (or worked) in."""
    text = note.get("text") or ""
    if not RESIDENCE_RE.search(text):
        return []
    return codes_in_text(text)


@dataclass
class CustomerPicture:
    facts: CustomerFacts
    checks: list[IdentityCheck] = field(default_factory=list)
    latest_approved: Optional[IdentityCheck] = None
    declared_dob_source: Optional[str] = None


def build_customer_facts(data: Data, record_ids: list[str], link: str = "none") -> CustomerPicture:
    primary = data.customers[record_ids[0]]
    company = is_company(primary.get("entity_type"))
    entity_type = COMPANY if company else PERSON

    checks = identity_checks(data, record_ids)
    approved = [c for c in checks if c.approved]
    latest = approved[0] if approved else None

    # Legal name and DOB: most recent approved check first, then the next approved
    # check that has the field, then the declared values on the primary record.
    legal_name, name_source, name_verified = None, None, False
    dob, dob_source = None, None
    for c in approved:
        if legal_name is None and c.name and len(normalize_name(c.name, company, data.variants)) >= 1:
            legal_name, name_source, name_verified = c.name, c.source_id, True
        if dob is None and c.dob:
            dob, dob_source = c.dob.iso(), c.source_id
        if legal_name and dob:
            break
    if legal_name is None:
        legal_name, name_source = clean(primary.get("full_name")) or "", primary["record_id"]
    if dob is None:
        d = parse_date(primary.get("dob"))
        if d is None:   # a merged record may carry the date the primary lacks
            for rid in record_ids[1:]:
                d = parse_date(data.customers[rid].get("dob"))
                if d:
                    primary_for_dob = rid
                    break
        else:
            primary_for_dob = primary["record_id"]
        if d:
            dob, dob_source = d.iso(), primary_for_dob

    other_names: list[str] = []
    for rid in record_ids:
        rec = data.customers[rid]
        for n in (rec.get("full_name"), rec.get("preferred_name"), rec.get("login_name")):
            n = clean(n)
            if n and n != legal_name and n not in other_names:
                other_names.append(n)

    # Countries with provenance.
    country_sources: dict[str, list[str]] = {}

    def add(code: Optional[str], source: str):
        if not code:
            return
        country_sources.setdefault(code, [])
        if source not in country_sources[code]:
            country_sources[code].append(source)

    for rid in record_ids:
        rec = data.customers[rid]
        for code in to_iso2_list([rec.get("residence_country"), rec.get("nationality")]):
            add(code, rid)
    for c in approved:
        add(c.country, c.source_id)
    for rid in record_ids:
        email = normalize_email(data.customers[rid].get("email"))
        for note in data.notes_by_email.get(email, []) if email else []:
            if is_identity_note(note):
                continue
            for code in residence_countries(note):
                add(code, note["note_id"])

    source_ids = list(record_ids)
    for s in (name_source, dob_source):
        if s and s not in source_ids:
            source_ids.append(s)
    for srcs in country_sources.values():
        for s in srcs:
            if s not in source_ids:
                source_ids.append(s)

    names_for_parts = [legal_name] + other_names
    real_parts = max((len(normalize_name(n, company, data.variants)) for n in names_for_parts), default=0)

    facts = CustomerFacts(
        customer_id=primary["record_id"], entity_type=entity_type, legal_name=legal_name,
        name_verified=name_verified, other_names=other_names, dob=dob,
        countries=sorted(country_sources), source_ids=source_ids,
        record_ids=list(record_ids), name_source_id=name_source, dob_source_id=dob_source,
        country_sources=country_sources, link=link, real_name_parts=real_parts,
    )
    return CustomerPicture(facts=facts, checks=checks, latest_approved=latest)
