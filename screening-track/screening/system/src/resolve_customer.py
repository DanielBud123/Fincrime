"""Step 1: alert -> the customer(s) it is about.

Follow the link the alert carries (account_ref, login_handle, email). An
account can have joint holders; the screened name and date of birth pick the
one who fits. Without a link, search the system of record for records that fit
what was screened. Every fitting record is then merged into its person
(step 2); the result is a list of persons, the linked one first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from countries import to_iso2, to_iso2_list
from customer_facts import merge_person
from dates import PartialDate, parse_date
from load import Data, clean, is_company, normalize_email, screened
from names import names_agree, normalize_name, strip_accents


@dataclass
class Candidate:
    record_ids: list[str]        # the person's records, the one the link led to first
    link: str                    # account | login | email | name


def dates_compatible(a: Optional[PartialDate], b: Optional[PartialDate]) -> bool:
    """Equal in every part both give. Unknown never contradicts."""
    if a is None or b is None:
        return True
    if a.year != b.year:
        return False
    if a.month is not None and b.month is not None and a.month != b.month:
        return False
    if a.day is not None and b.day is not None and a.day != b.day:
        return False
    return True


def _fold(s: Optional[str]) -> str:
    return strip_accents(s or "").lower().strip()


def name_fits(data: Data, record: dict, screened_name: Optional[str], company: bool) -> bool:
    if not screened_name:
        return True
    for n in (record.get("full_name"), record.get("preferred_name"), record.get("login_name")):
        if clean(n) and names_agree(screened_name, n, data.variants, company):
            return True
    return False


def dob_fits(record: dict, screened_dob: Optional[str]) -> bool:
    return dates_compatible(parse_date(record.get("dob")), parse_date(screened_dob))


def country_fits(record: dict, screened_country: Optional[str]) -> bool:
    code = to_iso2(screened_country)
    if not code:
        return True
    record_codes = to_iso2_list([record.get("residence_country"), record.get("nationality")])
    if not record_codes:
        return True
    return code in record_codes


def city_fits(record: dict, screened_city: Optional[str]) -> bool:
    city = _fold(screened_city)
    if not city:
        return True
    rec_city, rec_addr = _fold(record.get("city")), _fold(record.get("address"))
    if not rec_city and not rec_addr:
        return True
    head = city.split(",")[0].strip()
    for needle in {city, head}:
        if needle and (needle in rec_city or needle in rec_addr or (rec_city and rec_city in needle)):
            return True
    return False


def fits(data: Data, record_id: str, s: dict, strict_name: bool = True) -> bool:
    """Does this record fit the screened details? Missing details never exclude."""
    rec = data.customers[record_id]
    company = is_company(rec.get("entity_type")) or is_company(s.get("entity_type"))
    if strict_name and not name_fits(data, rec, s.get("name"), company):
        return False
    return dob_fits(rec, s.get("dob")) and country_fits(rec, s.get("country")) and city_fits(rec, s.get("city"))


def _by_link(data: Data, alert: dict) -> tuple[list[str], str]:
    """Record ids a link points at (possibly several joint holders), and the link type."""
    ref = clean(alert.get("account_ref"))
    if ref:
        ids = []
        for a in data.accounts_by_id.get(ref, []):
            if a["customer_id"] in data.customers and a["customer_id"] not in ids:
                ids.append(a["customer_id"])
        if ids:
            return ids, "account"
    login = clean(alert.get("login_handle"))
    if login:
        ids = []
        for a in data.accounts_by_login.get(login.lower(), []):
            if a["customer_id"] in data.customers and a["customer_id"] not in ids:
                ids.append(a["customer_id"])
        if ids:
            return ids, "login"
    email = normalize_email(alert.get("email"))
    if email:
        ids = [r for r in data.customers_by_email.get(email, []) if r in data.customers]
        if ids:
            return ids, "email"
    return [], "none"


def _search(data: Data, s: dict) -> list[str]:
    """Records that fit the screened details, found without a link.
    Blocking: by birth year when a DOB was screened, else by name parts."""
    company = is_company(s.get("entity_type"))
    block: set[str] = set()
    d = parse_date(s.get("dob"))
    if d:
        block |= data.customers_by_birth_year.get(d.year, set())
    parts = normalize_name(s.get("name"), company, data.variants)
    if not d or not block:
        for p in parts:
            block |= data.customers_by_name_part.get(p, set())
            g = data.variants.group_of.get(p)
            if g is not None:
                block |= data.customers_by_name_part.get(f"@{g}", set())
    if not block:
        block = set(data.customers)   # last resort: full scan
    hits = [rid for rid in block if fits(data, rid, s)]
    return sorted(hits)


def resolve(data: Data, alert: dict) -> list[Candidate]:
    s = screened(alert)
    ids, link = _by_link(data, alert)
    if ids:
        if len(ids) > 1:
            fitting = [r for r in ids if fits(data, r, s)]
            if not fitting:   # name alone may be a nickname or typo: fall back to the other details
                fitting = [r for r in ids if fits(data, r, s, strict_name=False)]
            ids = fitting or ids
    else:
        ids = _search(data, s)
        link = "name"

    # Merge into persons; a record already covered by an earlier person is skipped.
    candidates: list[Candidate] = []
    covered: set[str] = set()
    for rid in ids:
        if rid in covered:
            continue
        person = merge_person(data, rid)
        covered.update(person)
        candidates.append(Candidate(record_ids=person, link=link))
    return candidates
