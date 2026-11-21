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
