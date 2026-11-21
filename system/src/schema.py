"""The fact card: the contract between the data half and the decision half.

It is a superset of the card agreed in both CLAUDE.md files. Every agreed field
is present with the same name and meaning. The extra fields carry two things:

- provenance: which record each fact came from, because the output must cite
  exactly the records that decided a hit;
- completeness: whether each side's picture is complete and certain enough to
  clear a hit. A clear needs a complete picture; a gap can only lead to REVIEW.

Dates are ISO strings, partial dates allowed: "1985", "1985-03", "1985-03-12"
or None. Countries are ISO alpha-2 upper-case.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

PERSON = "person"
COMPANY = "company"


@dataclass
class CustomerFacts:
    customer_id: str                       # the record the link led to (first of record_ids)
    entity_type: Optional[str]             # "person" | "company" | None when the record's type is unknown
    legal_name: str
    name_verified: bool                    # True when legal_name comes from the most recent approved check
    other_names: list[str] = field(default_factory=list)
    dob: Optional[str] = None              # birth date, or incorporation date for a company
    countries: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    # --- provenance ---
    record_ids: list[str] = field(default_factory=list)      # all records merged into this person
    name_source_id: Optional[str] = None                     # KYC-/NOTE-/CUS- id behind legal_name
    dob_source_id: Optional[str] = None                      # KYC-/NOTE-/CUS- id behind dob
    country_sources: dict[str, list[str]] = field(default_factory=dict)  # ISO2 -> record ids
    link: str = "none"                     # account | login | email | name
    real_name_parts: int = 0               # rule 8: <2 real parts -> name can neither confirm nor clear
    # --- completeness: what a clear may rely on ---
    possible_countries: list[str] = field(default_factory=list)          # mentioned somewhere, not established
    possible_country_sources: dict[str, list[str]] = field(default_factory=dict)
    countries_complete: bool = True        # False: a country tied to the customer may be missing
    location_gaps: list[str] = field(default_factory=list)   # why, in words
    name_certain: bool = True              # False: the verified name may not be the most recent approved one
    dob_certain: bool = True               # False: the date of birth may not be the most recent approved one
    identity_gaps: list[str] = field(default_factory=list)   # why, in words
    identity_conflict: bool = False        # an unusable check states another name or date of birth: confirm nothing


@dataclass
class HitFacts:
    hit_id: str
    entity_type: Optional[str]             # "person" | "company" | None when unknown
    names: list[str] = field(default_factory=list)
    dobs: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    earliest_report_date: Optional[str] = None
    date_of_death: Optional[str] = None
    source_ids: list[str] = field(default_factory=list)
    # --- provenance ---
    dob_source_ids: list[str] = field(default_factory=list)  # SR- ids when dobs came from search results
    dob_origin: Optional[str] = None                         # "field" | "notes" | "search" | None
    country_names: list[str] = field(default_factory=list)   # countries as written, for the reason text
    primary_category: Optional[str] = None
    # --- completeness ---
    names_comparable: bool = True          # False: no name written in Latin letters
    dobs_complete: bool = True             # False: the hit may give a birth date we could not read
    dob_gaps: list[str] = field(default_factory=list)
    countries_complete: bool = True        # False: a country field held a value we could not read
    country_gaps: list[str] = field(default_factory=list)


@dataclass
class FactCard:
    alert_id: str
    hit_id: str
    screened_at: Optional[str]
    customer: CustomerFacts
    hit: HitFacts

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    alert_id: str
    hit_id: str
    decision: str                          # DIFFERENT_ENTITY | SAME_ENTITY | REVIEW
    reason_code: str
    evidence_ids: list[str] = field(default_factory=list)
    resolved_customer_id: Optional[str] = None   # CUS-xxxxxx | "AMBIGUOUS" | None
    explanation: str = ""
    sentences: list[str] = field(default_factory=list)   # the explanation, sentence by sentence (not output)

    def to_output_line(self) -> dict:
        """Diligent's submission format (README section 5)."""
        return {
            "hit_id": self.hit_id,
            "alert_id": self.alert_id,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "customer_record_id": self.resolved_customer_id,
            "reason": self.explanation,
            "evidence": list(dict.fromkeys(self.evidence_ids)),
        }


REASON_CODES = {
    "DIFFERENT_ENTITY": ["TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
                         "NAME_MISMATCH_VERIFIED", "ENTITY_TYPE_MISMATCH", "DECEASED"],
    "SAME_ENTITY": ["NAME_DOB_LOCATION_MATCH", "NAME_DOB_MATCH", "NAME_LOCATION_MATCH"],
    "REVIEW": ["INSUFFICIENT_DATA", "AMBIGUOUS_CUSTOMER_RECORD"],
}
