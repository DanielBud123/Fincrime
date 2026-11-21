"""Fact card contract between the data half and the decision half.

Copied field-for-field from CLAUDE.md. Do not add, rename or remove a field
without agreeing it with the data half first.

Dates are strings, partial allowed: "1985", "1985-03", "1985-03-12", or None.
Countries are ISO alpha-2 upper-case ("GB", "EG"), normalized by the data half.
"""
from dataclasses import dataclass, field
from typing import Literal, Optional

EntityType = Literal["person", "company"]
DecisionValue = Literal["DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"]
ReasonCode = Literal[
    "TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
    "NAME_MISMATCH_VERIFIED", "ENTITY_TYPE_MISMATCH", "DECEASED",
    "NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH",
    "INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD",
]


@dataclass
class CustomerFacts:
    customer_id: str
    entity_type: EntityType
    legal_name: str
    name_verified: bool  # True only when legal_name comes from the latest approved KYC check
    other_names: list[str] = field(default_factory=list)
    dob: Optional[str] = None  # birth date (person) or incorporation date (company)
    countries: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass
class HitFacts:
    entity_type: EntityType
    names: list[str]
    dobs: list[str] = field(default_factory=list)  # every birth date from any source; may be []
    countries: list[str] = field(default_factory=list)
    earliest_report_date: Optional[str] = None
    date_of_death: Optional[str] = None
    source_ids: list[str] = field(default_factory=list)


@dataclass
class FactCard:
    alert_id: str
    hit_id: str
    screened_at: str
    customer: CustomerFacts
    hit: HitFacts


@dataclass
class Decision:
    alert_id: str
    hit_id: str
    decision: DecisionValue
    reason_code: ReasonCode
    evidence_ids: list[str]
    resolved_customer_id: Optional[str]
    explanation: str  # one plain sentence an analyst could read
