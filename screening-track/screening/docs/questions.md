# Open questions (take to office hours; do not guess)

Decisions we took in code are marked **(we do X)**.

## Scoring and format
- Does `evidence` get penalised for citing the hit's own record (`H-xxxxxx`) or a `H-xxxxxx#field` reference? The
  practice labels never cite hit ids, only CUS/KYC/NOTE/SR. **(we cite only customer-side records and SR ids,
  plus `H-xxxxxx#deceased_date` for DECEASED, which has no label example)**
- For REVIEW / INSUFFICIENT_DATA the labels sometimes cite the CUS record and sometimes only the NOTE. Which is
  preferred? **(we cite the person's records plus the check or note that gave the name/DOB and any note that
  added a shared country)**
- When several people fit and all lead to the same decision, the labels cite every person's records. Confirmed?
  **(we do that, with `customer_record_id` = AMBIGUOUS as POLICY.md principle 3 says)**

## Customer side
- Do account phone numbers count for the "same phone and full DOB" merge, or only the phone on the customer record?
  All 13 label merges work with the customer-record phone. **(we use customer-record phones only)**
- A link that leads to a dead reference (account/login/email not found): search by screened details, or REVIEW
  with null? **(we fall back to the screened-details search)**
- Joint holders where neither holder fits the screened name: keep both (→ ambiguous) or none? **(we keep both)**
- Does a non-KYC note that names a country without a "lived/worked" phrasing count as a place they lived?
  **(we require a residence/work word; adding a country can only make us review more, never clear more)**
- Should the document country of older approved checks count, or only the latest approved check's?
  **(we count all approved checks' countries but cite only records that contributed a country)**

## Hit side
- A `life_status` of "Deceased" with no `deceased_date`: can DECEASED ever fire? **(no: it needs a date before screening)**
- Should "born"/age sentences outside the first paragraph of `profile_notes` count? **(no, first paragraph only)**
- When several qualifying search results give different ages, do all their years count as the hit's possible years?
  **(yes, union; only every DOB contradicting clears)**
- Nationality fields holding "City, Region, Country": last part only, confirmed? **(yes)**

## Rules (for the decision half)
- Rule 8 vs team brief: the SOP says single letters are initials and not parts, parts under 4 letters must be
  identical, 4–6 letters allow 1 edit, 7+ allow 2, and names agree when ≥2 parts match OR every part of the
  shorter name matches. **(we follow the SOP wording)**
- Does a customer alias (preferred name) count toward agreement? **(yes for agreement; the verified legal name
  alone decides NAME_MISMATCH_VERIFIED)**
- Which reason code when two clear rules fire? **(labels accept any; we use the SOP order: type, death, time,
  DOB, verified name, location)**
- Does a 1-year birth-year gap count as "agree" for confirmation? **(no: neither agrees nor contradicts → REVIEW)**
- Declared name agrees but verified legal name does not: clear on NAME_MISMATCH_VERIFIED? **(yes, §6 "even if the
  name on their record does")**
- Placeholder "digits and the like": pure-digit tokens only, or mixed tokens like "N26" (label H-24D490)?
  **(pure digits only)**
- Partial date of death (`"2022-03"`) vs screened_at: **(clear only when every completion is before screening)**
- A name listed in two variant groups (joseph/joe are in the Yusuf group and the Joseph group): match against
  either group? **(yes: Yusuf ~ Joseph)**

## Team (decision half ↔ data half), from STOP 1/STOP 2
- Fact card: the provenance fields in `schema.py` (record_ids, name/dob source ids, country_sources, hit
  dob_source_ids) and `customer_record_id = AMBIGUOUS` whenever >1 person fits match the STOP 1 proposal.
  **Agreed; the superset card replaces the STOP 1 branch's schema.py.**
- Layout: the brief calls `system/run` and wants `system/` and `output/` in the repo. Proposal: move
  `screening-track/screening/{system,output,docs}` to the repo root before submission (one `git mv` commit).
- `names.py` (decision half) replaces the provisional one; same API. Fix: a part in two variant groups now
  matches either (`Variants.groups_of`). `Variants.group_of` (one id per part, used for name blocking in
  `load.py` / `resolve_customer.py`) keeps the lowest group id, so a no-link, no-DOB search for "Yusuf" will not
  block in a "Joseph" record. Low impact (every no-link alert has a DOB); index all groups if needed.
- Unsafe-clear surfaces to harden before freeze (data half): identity notes count as approved unless negative
  wording, and their CAPS-extracted name sets `name_verified` (can fire NAME_MISMATCH_VERIFIED); note-derived
  DOBs feed DOB_MISMATCH/TEMPORAL; `BIRTH_RE` reads "gave birth in 2010" as a DOB; `DD/MM/YYYY` assumed day-first;
  hit countries missing from the country table are dropped silently; the no-link search blocks by birth year,
  so records with no parseable DOB are never found. Reasons are sometimes one sentence (brief asks 2–4).
