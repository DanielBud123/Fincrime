"""Step 0: read every JSONL file once and build lookup tables.

Alerts and hits are the fixed starting points; everything else is a library we
look things up in. All indexes are plain dicts so each lookup is instant and
the run is deterministic.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from dates import parse_date
from names import Variants, normalize_name, query_key

FILES = {
    "alerts": "alerts.jsonl",
    "hits": "hits.jsonl",
    "customers": "customers.jsonl",
    "accounts": "accounts.jsonl",
    "onboarding": "onboarding.jsonl",
    "kyc_checks": "kyc_checks.jsonl",
    "notes": "notes.jsonl",
    "search_results": "search_results.jsonl",
}
OPTIONAL_FILES = {"practice_labels": "practice_labels.jsonl"}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def as_list(value) -> list:
    """List fields arrive as lists in JSONL, as '; ' strings in the workbook."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [v for v in value if v not in (None, "")]
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"\s*;\s*", value) if p.strip()]
    return [value]


def clean(value) -> Optional[str]:
    """A scalar string field; blanks and placeholders read as None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"n/a", "na", "none", "null", "unknown", "-", "--"}:
        return None
    return s


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    return digits or None


def normalize_email(email: Optional[str]) -> Optional[str]:
    e = clean(email)
    return e.lower() if e else None


def screened(alert: dict) -> dict:
    """The customer as screened: {name, entity_type, dob, country, city}.
    The JSONL nests it under ``customer``; the workbook flattens it."""
    c = alert.get("customer")
    if isinstance(c, dict):
        return {
            "name": clean(c.get("name")),
            "entity_type": clean(c.get("entity_type")),
            "dob": clean(c.get("dob")),
            "country": clean(c.get("country")),
            "city": clean(c.get("city")),
        }
    return {
        "name": clean(alert.get("customer_name") or alert.get("name")),
        "entity_type": clean(alert.get("entity_type")),
        "dob": clean(alert.get("dob")),
        "country": clean(alert.get("country")),
        "city": clean(alert.get("city")),
    }


def is_company(entity_type: Optional[str]) -> bool:
    return bool(entity_type) and entity_type.strip().lower() in {
        "company", "organisation", "organization", "entity", "corporate", "business"}


@dataclass
class Data:
    data_dir: Path
    alerts: dict[str, dict]
    alert_order: list[str]
    hits: dict[str, dict]
    hit_order: list[str]
    customers: dict[str, dict]
    accounts_by_id: dict[str, list[dict]]
    accounts_by_login: dict[str, list[dict]]
    accounts_by_customer: dict[str, list[dict]]
    onboarding_by_account: dict[str, list[dict]]
    onboarding_by_customer: dict[str, list[dict]]
    kyc_by_applicant: dict[str, list[dict]]
    notes_by_email: dict[str, list[dict]]
    search_by_query: dict[str, list[dict]]
    customers_by_email: dict[str, list[str]]
    customers_by_phone: dict[str, list[str]]
    customers_by_name_part: dict[str, set[str]]
    customers_by_birth_year: dict[int, set[str]]
    customer_name_parts: dict[str, list[str]]      # record_id -> normalized full_name parts
    applicants_by_customer: dict[str, list[str]]
    customers_by_doc_number: dict[str, set[str]]   # approved checks only
    variants: Variants
    practice_labels: list[dict] = field(default_factory=list)

    def hits_of(self, alert: dict) -> list[dict]:
        return [self.hits[h] for h in as_list(alert.get("hit_ids")) if h in self.hits]


def load(data_dir) -> Data:
    data_dir = Path(data_dir)
    raw = {key: read_jsonl(data_dir / fname) for key, fname in FILES.items()}
    for key, fname in OPTIONAL_FILES.items():
        p = data_dir / fname
        raw[key] = read_jsonl(p) if p.exists() else []

    variants_path = data_dir / "name_variants.json"
    variants = Variants(json.loads(variants_path.read_text(encoding="utf-8"))) if variants_path.exists() else Variants()

    alerts = {a["alert_id"]: a for a in raw["alerts"]}
    hits = {h["hit_id"]: h for h in raw["hits"]}
    customers = {c["record_id"]: c for c in raw["customers"]}

    accounts_by_id, accounts_by_login, accounts_by_customer = defaultdict(list), defaultdict(list), defaultdict(list)
    for a in raw["accounts"]:
        accounts_by_id[a["account_id"]].append(a)
        if clean(a.get("login_handle")):
            accounts_by_login[a["login_handle"].strip().lower()].append(a)
        accounts_by_customer[a["customer_id"]].append(a)

    onboarding_by_account, onboarding_by_customer = defaultdict(list), defaultdict(list)
    applicants_by_customer = defaultdict(list)
    for o in raw["onboarding"]:
        onboarding_by_account[o["account_id"]].append(o)
        onboarding_by_customer[o["customer_id"]].append(o)
        if clean(o.get("kyc_applicant_id")):
            applicants_by_customer[o["customer_id"]].append(o["kyc_applicant_id"])

    kyc_by_applicant = defaultdict(list)
    for k in raw["kyc_checks"]:
        kyc_by_applicant[k["applicant_id"]].append(k)
    for checks in kyc_by_applicant.values():       # most recent first, stable on check_id
        checks.sort(key=lambda k: ((parse_date(k.get("checked_at")) or parse_date("1800")).iso(), k["check_id"]), reverse=True)

    notes_by_email = defaultdict(list)
    for n in raw["notes"]:
        e = normalize_email(n.get("requester_email"))
        if e:
            notes_by_email[e].append(n)
    for ns in notes_by_email.values():
        ns.sort(key=lambda n: (n.get("created_at") or "", n["note_id"]))

    search_by_query = defaultdict(list)
    for s in raw["search_results"]:
        search_by_query[query_key(s.get("query") or "")].append(s)

    customers_by_email, customers_by_phone = defaultdict(list), defaultdict(list)
    customers_by_name_part, customers_by_birth_year = defaultdict(set), defaultdict(set)
    customer_name_parts = {}
    for rid, c in customers.items():
        e = normalize_email(c.get("email"))
        if e:
            customers_by_email[e].append(rid)
        p = normalize_phone(c.get("phone"))
        if p:
            customers_by_phone[p].append(rid)
        company = is_company(c.get("entity_type"))
        parts = normalize_name(c.get("full_name"), company, variants)
        customer_name_parts[rid] = parts
        for name in (c.get("full_name"), c.get("preferred_name"), c.get("login_name")):
            for part in normalize_name(name, company, variants):
                customers_by_name_part[part].add(rid)
                g = variants.group_of.get(part)
                if g is not None:
                    customers_by_name_part[f"@{g}"].add(rid)
        d = parse_date(c.get("dob"))
        if d:
            customers_by_birth_year[d.year].add(rid)

    customers_by_doc_number = defaultdict(set)
    for rid, apps in applicants_by_customer.items():
        for app in apps:
            for k in kyc_by_applicant.get(app, []):
                if (k.get("result") or "").lower() == "approved" and clean(k.get("document_number")):
                    customers_by_doc_number[k["document_number"].strip().upper()].add(rid)

    return Data(
        data_dir=data_dir,
        alerts=alerts, alert_order=[a["alert_id"] for a in raw["alerts"]],
        hits=hits, hit_order=[h["hit_id"] for h in raw["hits"]],
        customers=customers,
        accounts_by_id=dict(accounts_by_id), accounts_by_login=dict(accounts_by_login),
        accounts_by_customer=dict(accounts_by_customer),
        onboarding_by_account=dict(onboarding_by_account), onboarding_by_customer=dict(onboarding_by_customer),
        kyc_by_applicant=dict(kyc_by_applicant),
        notes_by_email=dict(notes_by_email),
        search_by_query=dict(search_by_query),
        customers_by_email=dict(customers_by_email), customers_by_phone=dict(customers_by_phone),
        customers_by_name_part=dict(customers_by_name_part), customers_by_birth_year=dict(customers_by_birth_year),
        customer_name_parts=customer_name_parts,
        applicants_by_customer=dict(applicants_by_customer),
        customers_by_doc_number=dict(customers_by_doc_number),
        variants=variants,
        practice_labels=raw["practice_labels"],
    )
