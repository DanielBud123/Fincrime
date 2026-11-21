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

The design rule for this module: a fact that can clear a hit must come from
the source the SOP names, read with certainty. When that source exists but
cannot be read, the fact is unknown and the gap is recorded; the rules then
refuse to clear on it. Extra customer countries are harmless (they can only
block a location clear), so every country a note mentions is kept at least as
a possibility.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from countries import _LOOKUP, _fold, codes_in_text, field_codes
from dates import PartialDate, find_dates, parse_date
from load import Data, clean, entity_kind, normalize_email, normalize_phone
from names import Variants, names_agree, normalize_name
from places import has_unresolved_place, places_in_text
from schema import COMPANY, CustomerFacts

# ----------------------------------------------------------------------------
# Step 2: one person, one picture
# ----------------------------------------------------------------------------


def full_dob(data: Data, record_id: str) -> Optional[str]:
    d = data.customer_dobs.get(record_id)
    return d.iso() if d and d.is_full else None


def approved_doc_numbers(data: Data, record_id: str) -> set[str]:
    out = set()
    for app in data.applicants_by_customer.get(record_id, []):
        for k in data.kyc_by_applicant.get(app, []):
            if row_status(k.get("result")) == APPROVED and clean(k.get("document_number")):
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
# Step 3: identity checks (KYC rows and onboarding notes)
# ----------------------------------------------------------------------------

APPROVED, REJECTED, UNCLEAR = "approved", "rejected", "unclear"

APPROVED_RESULTS = {"approved", "approve", "passed", "pass", "verified", "accepted", "success", "successful",
                    "cleared", "clear", "ok", "valid", "completed", "complete"}
REJECTED_RESULTS = {"rejected", "reject", "declined", "failed", "fail", "denied", "expired", "refused",
                    "invalid", "cancelled", "canceled", "revoked", "unsuccessful", "withdrawn", "abandoned"}

# Words that say outright that a check did not pass.
NEGATIVE_RE = re.compile(
    r"\b(reject\w*|fail\w*|declin\w*|unsuccessful\w*|denied|refus\w*|expired|invalid\w*|abandon\w*|"
    r"cancel\w*|revoked|withdrawn)\b", re.I)
# Words that leave the outcome open. A note carrying any of these is not an approved check.
HEDGE_RE = re.compile(
    r"\b(?:not|never)\b|n't\b|\b(?:unable|cannot|mismatch\w*|no match|pending|await\w*|under review|in review|"
    r"manual review|being reviewed|to be \w+|re-?run\w*|re-?submi\w*|re-?upload\w*|partial\w*|incomplete|"
    r"inconclusive|low[- ]confidence|on hold|escalat\w*|quer(?:y|ied)|suspicious|flagged|blurr\w*|unreadable|"
    r"illegible|unclear|in progress|scheduled|will be|fraud\w*|discrepanc\w*|doubt\w*|unconfirmed|unverified|"
    r"expir(?:y|es|ing|ation))\b", re.I)
# Words that say a check passed.
POSITIVE_RE = re.compile(
    r"\b(verified|verifies|confirmed|confirms|validated|validates|approved|approves|passed|passes|cleared|"
    r"clears|success\w*|complete|completed|completes|authenticated|matches|matched|vetted|accepted|onboarded|"
    r"processed)\b", re.I)

IDENTITY_CHANNELS = {"kyc", "onboarding", "identity", "verification", "idv"}
DOCUMENT_RE = re.compile(
    r"\b(passports?|national id(?:entity)?(?: cards?)?|id cards?|identity cards?|identity documents?|id documents?|"
    r"driving licen[cs]es?|driver'?s? licen[cs]es?|registry extract|kyc|identity (?:check|verification)|"
    r"id (?:check|verification)|sumsub|veriff|persona|onfido|jumio|trulioo)\b", re.I)
CHECK_RE = re.compile(
    r"\b(verif\w*|validat\w*|confirm\w*|authenticat\w*|approv\w*|vett?ed|check\w*|reject\w*|fail\w*|declin\w*|"
    r"review\w*|cleared|passed)\b", re.I)

CAPS_NAME_RE = re.compile(r"\b([A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]+(?:\.|\b)(?:[ \-][A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]*(?:\.|\b))+)")
# One or more capitalised words in a row (a single word counts, so "BERG, PIETER" can be joined).
CAPS_RUN_RE = re.compile(r"\b[A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]+(?:\.|\b)(?:[ \-][A-ZÀ-ÝŠŽŁ][A-ZÀ-ÝŠŽŁ'’\-]*(?:\.|\b))*")
# Capitalised words that are never part of a person's name in an identity note.
CAPS_STOP = {
    "DOB", "ID", "KYC", "DATE", "OF", "BIRTH", "NAME", "N/A", "NA", "THE", "AND", "ON", "FOR", "VIA", "BY",
    "FROM", "USING", "IN", "AT", "TO", "A", "AN", "IS", "WAS", "PEP", "SOE", "US", "UK", "USA", "EU",
    "PASSPORT", "NATIONAL", "DRIVING", "LICENCE", "LICENSE", "IDENTITY", "CARD", "DOCUMENT", "VERIFIED",
    "APPROVED", "CONFIRMED", "PASSED", "FAILED", "REJECTED", "CHECK", "RESULT", "COMPLETE", "COMPLETED",
    "SUMSUB", "VERIFF", "PERSONA", "ONFIDO", "JUMIO", "TRULIOO", "MR", "MRS", "MS", "DR", "HOLDER",
}
_PARTICLE = r"(?:(?:van|der|den|de|la|del|della|di|da|dos|das|do|bin|binti|ibn|al|el|von|le|du|ben|abu)\s+)*"
TITLE_NAME_ANCHOR_RE = re.compile(
    r"(?:\bfor|\bof|\bholder|\bname(?: on document)?:?|\bshows|\bidentity of|\bverified|\bconfirmed|\bcleared|\bmatches)\s+"
    r"((?:[A-ZÀ-Ý][a-zà-ÿ'’\-]+\.?\s+" + _PARTICLE + r"){1,4}[A-ZÀ-Ý][A-Za-zà-ÿ'’\-]+)")

# The date of birth sits right after a birth word ("born on", "DOB:", "Date of birth on document:").
_BIRTH_BEFORE_RE = re.compile(
    r"(?:\bborn(?:\s+in\s+(?-i:[A-ZÀ-Þ])[\w'’.-]*(?:\s+(?-i:[A-ZÀ-Þ])[\w'’.-]*){0,2})?"   # "born in Bangladesh on"
    r"|\bbirth ?date|\bdate of birth|\bd\.?o\.?b\b\.?|\bbirth)"
    r"(?:\s+(?:on|in|is|was|of|as|at|set|to|be|recorded|given|shown|listed|stated|noted|registered|entered|"
    r"being|date|document|the|per|file|id|record|reads|showing|indicated))*"
    r"[\s:,(–-]*$", re.I)
# "03/05/1976 DOB via national ID", "her 08/10/2000 date of birth": the birth word right after the date.
_BIRTH_AFTER_RE = re.compile(r"\s+(?:dob|d\.o\.b\.?|date of birth|birth ?date)\b", re.I)
# A date after one of these is when something happened to the document or the check, not a birth.
_OTHER_DATE_BEFORE_RE = re.compile(
    r"(?:\b(?:on|as of|dated|at|issued|issue date|expir\w*|valid (?:until|to|thru|through|till)|renew\w*|until|since|"
    r"check(?:ed)?|previous(?:ly)?|prior|refresh\w*|review\w*|verified|validated|confirmed|approved|completed|"
    r"processed|cleared|passed|scheduled(?: for)?)"
    r"\s*[:(–-]?\s*|[(]\s*\w+\s*,\s*)$", re.I)
MIN_AGE_AT_CHECK = 10     # a person verified by passport is not younger than this


def row_status(result: Optional[str]) -> str:
    r = (result or "").strip().lower()
    if r in APPROVED_RESULTS:
        return APPROVED
    if r in REJECTED_RESULTS:
        return REJECTED
    return UNCLEAR


def note_status(text: str, complete: bool = False) -> str:
    """How an onboarding note's identity check ended.

    Any word that says the check did not pass, or leaves its outcome open,
    rules approval out. Otherwise the note is an approved check when it says
    so, or when it is a complete write-up (``complete``: it names the person
    and gives the date of birth) with nothing negative in it: a different
    team will not use the verb we expect, but a rejection says why.
    """
    negative, hedge, positive = NEGATIVE_RE.search(text), HEDGE_RE.search(text), POSITIVE_RE.search(text)
    if negative and not positive:
        return REJECTED
    if negative or hedge:
        return UNCLEAR
    return APPROVED if (positive or complete) else UNCLEAR


def is_approved(result: Optional[str]) -> bool:
    return row_status(result) == APPROVED


@dataclass
class IdentityCheck:
    source_id: str
    kind: str                           # "kyc" | "note"
    date: Optional[PartialDate]
    status: str                         # approved | rejected | unclear
    name: Optional[str] = None
    dob: Optional[PartialDate] = None
    countries: list[str] = field(default_factory=list)       # ISO2 of the document country
    country_unread: Optional[str] = None                     # a document country we could not read
    document_number: Optional[str] = None
    record_id: Optional[str] = None     # the customer record this check belongs to
    foreign: bool = False               # filed under the customer but names someone else

    @property
    def approved(self) -> bool:
        return self.status == APPROVED and not self.foreign

    @property
    def country(self) -> Optional[str]:
        return self.countries[0] if len(self.countries) == 1 else None

    def sort_key(self):
        return ((self.date.iso() if self.date else "0000"), self.kind == "kyc", self.source_id)


def kyc_row_check(row: dict, record_id: str) -> IdentityCheck:
    codes, unread = field_codes([row.get("document_country")])
    return IdentityCheck(
        source_id=row["check_id"], kind="kyc", date=parse_date(row.get("checked_at")),
        status=row_status(row.get("result")),
        name=clean(row.get("verified_name")), dob=parse_date(row.get("verified_dob")),
        countries=codes, country_unread=unread[0] if unread else None,
        document_number=(clean(row.get("document_number")) or "").upper() or None,
        record_id=record_id,
    )


def is_identity_note(note: dict) -> bool:
    """An onboarding note that writes up an identity check."""
    if (note.get("channel") or "").strip().lower() in IDENTITY_CHANNELS:
        return True
    text = note.get("text") or ""
    return bool(DOCUMENT_RE.search(text)) and bool(CHECK_RE.search(text))


def _drop_country_runs(words: list[str]) -> list[str]:
    """Remove runs of words that are a country name of two or more words
    ("UNITED KINGDOM"). A single word is kept: Jordan and Chad are also names."""
    out, i = [], 0
    while i < len(words):
        for n in (4, 3, 2):
            if i + n <= len(words) and _fold(" ".join(w.strip(".") for w in words[i:i + n])) in _LOOKUP:
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def _caps_names(text: str) -> list[str]:
    """Names written in capitals. A run of capitalised words is a name; two runs
    joined by ", " are one name when one side is a single word ("VAN DER BERG,
    PIETER" is surname, given name). Dropping the given name would make a
    surname-only name that can falsely mismatch a hit."""
    runs = []
    for m in CAPS_RUN_RE.finditer(text):
        words = [w for w in re.split(r"[ \-]", m.group(0).strip(" .")) if w]
        words = _drop_country_runs([w for w in words if w.strip(".") not in CAPS_STOP])
        if words:
            runs.append((m.start(), m.end(), words))
    names: list[str] = []
    i = 0
    while i < len(runs):
        _, end, words = runs[i]
        if i + 1 < len(runs) and text[end:runs[i + 1][0]] == ", " and 1 in (len(words), len(runs[i + 1][2])):
            other = runs[i + 1][2]
            single = (words if len(words) == 1 else other)[0].strip(".")
            if not (len(single) > 3 and _fold(single) in _LOOKUP):     # "ANA LOPEZ, NIGERIA" is not a surname
                words = words + other
                i += 1
        if len(words) >= 2 and " ".join(words) not in names:
            names.append(" ".join(words))
        i += 1
    return names


def _name_from_note(text: str) -> Optional[str]:
    """The person's name in an identity note: the run of capitalised words.
    A note naming two different people is ambiguous and yields None (fail closed)."""
    names = _caps_names(text)
    if len(names) == 1:
        return names[0]
    if len(names) > 1:
        parts = [set(normalize_name(n)) for n in names]
        if all(p <= parts[0] or parts[0] <= p for p in parts[1:]):   # the same person written twice
            return max(names, key=len)
        return None
    found = []
    for m in TITLE_NAME_ANCHOR_RE.finditer(text):
        cand = m.group(1).strip()
        if len(normalize_name(cand)) >= 2 and not codes_in_text(cand) and cand not in found:
            found.append(cand)
    return found[0] if len(found) == 1 else None


def _dob_from_note(text: str, created_at: Optional[PartialDate]) -> Optional[PartialDate]:
    """The birth date in an identity note.

    It is the date sitting right after a birth word, or in brackets right after
    the name. Failing that, it is the one date left once the note's own date
    and document dates (issued, expires, "on <date>") are set aside. Two
    candidates, or a date that would make the person a small child at the
    check, give None: unknown stays unknown.
    """
    every = find_dates(text, source="text")
    mentions = [m for m in every if m.date.month is not None]
    if not every:
        return None

    def plausible(d: PartialDate) -> Optional[PartialDate]:
        if created_at and not (MIN_AGE_AT_CHECK <= created_at.year - d.year <= 120):
            return None
        return d

    # A birth word right before the date ("born in Lagos on …", "DOB 1960") or right after
    # it ("03/05/1976 DOB"). A year alone is a date of birth only in this position.
    born = [m.date for m in every
            if _BIRTH_BEFORE_RE.search(text[max(0, m.start - 64):m.start])
            or (m.date.month is not None and _BIRTH_AFTER_RE.match(text[m.end:m.end + 20]))]
    born = list(dict.fromkeys(born))
    if born:
        return plausible(born[0]) if len(born) == 1 else None
    bracketed = [m.date for m in mentions
                 if text[max(0, m.start - 1):m.start] == "(" and text[m.end:m.end + 1] == ")"
                 and not (created_at and m.date == created_at)]
    bracketed = list(dict.fromkeys(bracketed))
    if len(bracketed) == 1:
        return plausible(bracketed[0])
    rest = [m.date for m in mentions
            if not (created_at and m.date == created_at)
            and not _OTHER_DATE_BEFORE_RE.search(text[max(0, m.start - 26):m.start])]
    rest = list(dict.fromkeys(rest))
    if len(rest) == 1:
        return plausible(rest[0])
    return None


def note_check(note: dict, record_id: str) -> IdentityCheck:
    text = note.get("text") or ""
    created = parse_date(note.get("created_at"))
    name, dob = _name_from_note(text), _dob_from_note(text, created)
    return IdentityCheck(
        source_id=note["note_id"], kind="note", date=created,
        status=note_status(text, complete=bool(name and dob)),
        name=name, dob=dob, countries=codes_in_text(text), record_id=record_id,
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
# Step 3: countries the support notes tie to the customer
# ----------------------------------------------------------------------------

RESIDENCE_RE = re.compile(
    r"\b(liv\w+|resid\w+|based|home|dwell\w*|household|domicil\w*|stay\w*|relocat\w*|moved|settl\w*|"
    r"life|career|employed|employment|worked|working|workplace|work|job|occupation|position|professional|"
    r"located|location|inside|within|base|"
    r"address\w*|citizen\w*|national\w*|origin\w*|born|grew up|raised|comes? from|came from|(?:is|are|was) from|"
    r"hails? from|native of|returned|spent|permit|expat\w*|immigra\w*|emigra\w*)\b", re.I)
# Plans and possibilities are not places someone lived: a plan word governing a
# move verb ("will relocate", "considering moving"). A past tense ("lived",
# "relocated") is never a plan, whatever else the sentence says.
HYPOTHETICAL_RE = re.compile(
    r"\b(?:will|would|might|plans? to|planning to|intends? to|intending to|considering|considered|"
    r"thinking (?:of|about)|hopes? to|hoping to|wants? to|would like to|looking to)\s+(?:\w+\s+){0,2}?"
    r"(?:move|moving|relocate|relocating|live|living|settle|settling|emigrate|emigrating|immigrate|"
    r"immigrating|reside|residing)\b", re.I)
# A note about something else that happens to name a country: a transfer, a trip,
# a relative, an employer, a document.
NON_RESIDENCE_RE = re.compile(
    r"\b(transfer\w*|payment\w*|paid|pay|sent|send\w*|remit\w*|money|purchase\w*|merchant\w*|supplier\w*|"
    r"invoice\w*|holiday\w*|vacation\w*|travel\w*|trip|visit\w*|flight\w*|airline\w*|hotel\w*|call(?:ed|ing)?|"
    r"number|fees?|charge\w*|card|exchange rate|match|mother|father|brother|sister|son|daughter|wife|husband|"
    r"family|relative\w*|friend\w*|employer|company|document|issued|uploaded|bank account|contact)\b", re.I)


@dataclass
class NoteReading:
    confident: list[str] = field(default_factory=list)   # countries the note says the customer lived or worked in
    possible: list[str] = field(default_factory=list)    # countries it merely mentions
    unresolved: bool = False                             # it talks about residence and names a place we cannot map


def read_support_note(note: dict) -> NoteReading:
    text = note.get("text") or ""
    countries = codes_in_text(text)
    settled, ambiguous = places_in_text(text)
    reading = NoteReading()
    residence = bool(RESIDENCE_RE.search(text))
    # A support note that names a country is saying where the customer lived, in
    # whatever words, unless it is a plan or is plainly about something else.
    about_residence = not HYPOTHETICAL_RE.search(text) and (residence or not NON_RESIDENCE_RE.search(text))
    if about_residence:
        reading.confident = list(dict.fromkeys(countries + settled))
        reading.possible = [c for c in ambiguous if c not in reading.confident]
        reading.unresolved = (residence and not reading.confident and not reading.possible
                              and has_unresolved_place(text))
    else:
        reading.possible = list(dict.fromkeys(countries + settled + ambiguous))
    return reading


def residence_countries(note: dict) -> list[str]:
    """Countries a support note says the customer lived (or worked) in."""
    return read_support_note(note).confident


# ----------------------------------------------------------------------------
# Step 3: the customer's picture
# ----------------------------------------------------------------------------

@dataclass
class CustomerPicture:
    facts: CustomerFacts
    checks: list[IdentityCheck] = field(default_factory=list)
    latest_approved: Optional[IdentityCheck] = None


def _same_or_newer(check: IdentityCheck, reference: Optional[IdentityCheck]) -> bool:
    if reference is None or check.date is None or reference.date is None:
        return True
    return check.date.sort_key() >= reference.date.sort_key()


def build_customer_facts(data: Data, record_ids: list[str], link: str = "none") -> CustomerPicture:
    variants: Variants = data.variants
    primary = data.customers[record_ids[0]]
    kind = entity_kind(primary.get("entity_type"))
    company = kind == COMPANY

    declared: list[str] = []
    for rid in record_ids:
        rec = data.customers[rid]
        for n in (rec.get("full_name"), rec.get("preferred_name"), rec.get("login_name")):
            n = clean(n)
            if n and n not in declared:
                declared.append(n)
    declared_parts = {p for n in declared for p in normalize_name(n, company, variants)}

    declared_full_dobs = {full_dob(data, rid) for rid in record_ids} - {None}

    checks = identity_checks(data, record_ids)
    # A note filed under the customer is this customer's check when it shares a
    # name part with them or carries their exact date of birth. One that does
    # neither names someone else and is not used.
    for c in checks:
        if c.kind == "note" and c.name:
            parts = set(normalize_name(c.name, company, variants))
            same_dob = bool(c.dob and c.dob.is_full and c.dob.iso() in declared_full_dobs)
            if not same_dob and not (parts & declared_parts) \
                    and not any(names_agree(c.name, n, variants, company) for n in declared):
                c.foreign = True
    approved = [c for c in checks if c.approved]
    latest = approved[0] if approved else None

    identity_gaps: list[str] = []
    for c in checks:
        if c is latest or not _same_or_newer(c, latest):
            continue
        if c.foreign and c.status == APPROVED:
            identity_gaps.append(f"{c.source_id} is filed under the customer but names someone else")
        elif c.status == UNCLEAR:
            identity_gaps.append(f"the outcome of identity check {c.source_id} could not be read")
        elif c.approved and latest and c.date and latest.date and c.date == latest.date:
            if (c.name and latest.name and not names_agree(c.name, latest.name, variants, company)) \
                    or (c.dob and latest.dob and c.dob != latest.dob):
                identity_gaps.append(f"approved checks {latest.source_id} and {c.source_id} of the same day disagree")
    identity_certain = not identity_gaps

    # Legal name and date of birth come from the most recent approved check only.
    # If that check exists but a field cannot be read, the field is unknown: an
    # older check is not used in its place.
    declared_name = clean(primary.get("full_name")) or (declared[0] if declared else "")
    if latest and latest.name:
        legal_name, name_source, name_verified = latest.name, latest.source_id, True
    else:
        legal_name, name_source, name_verified = declared_name, primary["record_id"], False

    declared_dob, declared_dob_source = None, None
    for rid in record_ids:
        d = data.customer_dobs.get(rid)
        if d:
            declared_dob, declared_dob_source = d, rid
            break
    dob_certain = identity_certain
    if latest and latest.dob:
        dob, dob_source = latest.dob.iso(), latest.source_id
    else:
        dob = declared_dob.iso() if declared_dob else None
        dob_source = declared_dob_source
        if latest:
            dob_certain = False
            identity_gaps.append(f"the date of birth on the latest approved check {latest.source_id} could not be read")

    other_names = [n for n in declared if n != legal_name]

    # A check we could not use, at least as recent as the one we did, that states a
    # different name or date of birth: the customer's identity is then in doubt,
    # and nothing may be confirmed on the facts in hand.
    identity_conflict = False
    for c in checks:
        if c is latest or not _same_or_newer(c, latest):
            continue
        if c.status == UNCLEAR or (c.foreign and c.status == APPROVED):
            if (c.name and not names_agree(c.name, legal_name, variants, company)) \
                    or (c.dob and dob and c.dob.iso() != dob):
                identity_conflict = True

    # Countries: established ones with their sources, and mere possibilities.
    country_sources: dict[str, list[str]] = {}
    possible_sources: dict[str, list[str]] = {}
    location_gaps: list[str] = []

    def add(target: dict, code: Optional[str], source: str):
        if code:
            target.setdefault(code, [])
            if source not in target[code]:
                target[code].append(source)

    for rid in record_ids:
        rec = data.customers[rid]
        codes, unread = field_codes([rec.get("residence_country"), rec.get("nationality")])
        for code in codes:
            add(country_sources, code, rid)
        for u in unread:
            location_gaps.append(f"a country on {rid} could not be read ({u})")
    for c in checks:
        if c.approved:
            for code in c.countries:
                add(country_sources, code, c.source_id)
            if c.country_unread:
                location_gaps.append(f"the document country on {c.source_id} could not be read ({c.country_unread})")
            elif not c.countries:
                location_gaps.append(f"the document country on {c.source_id} could not be read")
        else:
            for code in c.countries:
                add(possible_sources, code, c.source_id)
    for rid in record_ids:
        email = normalize_email(data.customers[rid].get("email"))
        for note in data.notes_by_email.get(email, []) if email else []:
            if is_identity_note(note):
                continue
            reading = read_support_note(note)
            for code in reading.confident:
                add(country_sources, code, note["note_id"])
            for code in reading.possible:
                add(possible_sources, code, note["note_id"])
            if reading.unresolved:
                location_gaps.append(f"{note['note_id']} says where the customer lived but names no country we can read")
    possible_sources = {k: v for k, v in possible_sources.items() if k not in country_sources}

    source_ids = list(record_ids)
    for s in (name_source, dob_source):
        if s and s not in source_ids:
            source_ids.append(s)
    for srcs in country_sources.values():
        for s in srcs:
            if s not in source_ids:
                source_ids.append(s)

    real_parts = max((len(normalize_name(n, company, variants)) for n in [legal_name] + other_names), default=0)

    facts = CustomerFacts(
        customer_id=primary["record_id"], entity_type=kind, legal_name=legal_name,
        name_verified=name_verified, other_names=other_names, dob=dob,
        countries=sorted(country_sources), source_ids=source_ids,
        record_ids=list(record_ids), name_source_id=name_source, dob_source_id=dob_source,
        country_sources=country_sources, link=link, real_name_parts=real_parts,
        possible_countries=sorted(possible_sources), possible_country_sources=possible_sources,
        countries_complete=not location_gaps, location_gaps=location_gaps,
        name_certain=identity_certain, dob_certain=dob_certain, identity_gaps=identity_gaps,
        identity_conflict=identity_conflict,
    )
    return CustomerPicture(facts=facts, checks=checks, latest_approved=latest)
