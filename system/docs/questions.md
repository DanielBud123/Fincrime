# Open questions — decision half

## STOP 1 — for the data half (contract)

`system/src/schema.py` copies the fact card field-for-field from CLAUDE.md. Nothing changed yet.
Two proposed changes, **not made until you agree**:

1. **`customer_record_id` = `AMBIGUOUS` whenever more than one person fits.**
   POLICY §3: "If more than one person fits an alert, decide the hit for each ... Either way `customer_record_id` is `AMBIGUOUS`."
   Practice labels H-6C7985 and H-CDEC83 are `REVIEW / INSUFFICIENT_DATA` with `customer_record_ids: ["AMBIGUOUS"]`: all candidates agreed, still AMBIGUOUS.
   CLAUDE.md `decide_hit()` currently returns `results[0]` with that candidate's id.
   Proposal: when `len(candidates) > 1`, `resolved_customer_id = "AMBIGUOUS"` regardless of whether decisions agree.

2. **Per-fact source ids on the fact card.**
   Scoring checks that evidence "cites the records that decided it (and not everything you looked at)". Labels cite narrowly:
   - DOB_MISMATCH → only the customer DOB source (KYC/NOTE), plus SR id if the hit DOB came from search (H-D861DA, H-622EDD, H-58A39C).
   - NAME_MISMATCH_VERIFIED → only the KYC/NOTE with the verified name (H-2808BE, H-EDBB79).
   - LOCATION_MISMATCH → CUS record(s) + KYC/NOTE carrying countries (H-8E4EC8, H-539324).
   - SAME_ENTITY → CUS record(s) + DOB source + SR if used (H-0181BD).
   With one lumped `source_ids` list we can't do this. Proposal (additive, nothing renamed):
   - `customer.name_source_ids`, `customer.dob_source_ids`, `customer.country_source_ids`, `customer.record_ids` (all CUS ids of the person)
   - `hit.dob_source_ids` (empty when from the `dobs` field/profile notes, SR ids when from search), `hit.report_source_ids`, `hit.death_source_ids`
   Keep `source_ids` as the union for fallback.

3. **Repo layout.** Code lives in `system/src`, `system/tests`, `system/docs` so it ships in the submitted `system/` folder. `.gitignore` excludes `dev/`, `*.jsonl`, `.env` (brief: never commit data or API key). OK?

## STOP 2 heads-up — names.py follows POLICY §8, not CLAUDE.md

Decision-half owner's call: where CLAUDE.md's name spec differs from POLICY.md §8, POLICY wins. Differences:

| Topic | CLAUDE.md | POLICY §8 (implemented) |
|---|---|---|
| Names agree | every shorter part matches **AND** ≥2 matched | ≥2 parts match **OR** every part of shorter name matches |
| Initials | initial matches part starting with that letter | single letters are not parts (dropped) |
| Short parts | edit ≤1 at any length | parts <4 letters must be identical |
| Dropped tokens | placeholders | placeholders + digits; for companies also `company_legal_forms` |
| <2 real parts | can't confirm (ex. 15) | individual can be neither confirmed **nor cleared** on name |

Evidence: label H-02115F "Pescanova S.A." vs "Pescanova, Sociedad Anónima" = SAME_ENTITY. Fails under CLAUDE.md rule (only 1 part matched), passes under POLICY (shorter name fully matched).
Affects your no-link customer search via `names_agree()`.
Variants: only the provided `name_variants.json`, loaded from the run's data folder. No expanded list (labels H-D9BBCC Markus≠Mark, H-CF173B Jonathan≠John).

## For the 15:00 Diligent mentors

1. When two clear rules fire at once, which reason code do the labels prefer? (Labels list several, e.g. `["TEMPORAL_IMPOSSIBILITY","LOCATION_MISMATCH"]`; README says any listed is accepted — confirm.)
2. Does a 1-year birth-year gap count as "agree" for confirmation? (We say no; but age-derived DOBs already give two years — labels H-582410 "1967 or 1968".)
3. Customer's *declared* name agrees but *verified* legal name doesn't — clear on NAME_MISMATCH_VERIFIED? (We say yes, per §6 "even if the name on their record does".)
4. Does an alias on the customer side (preferred name, login name) count toward agreement? Toward preventing NAME_MISMATCH_VERIFIED?
5. Placeholder "digits and the like": pure-digit tokens only, or also mixed tokens like "N26" (label H-24D490 "N26 Bank AG")? We drop pure digits only.
6. Partial date of death (`"2022-03"`) vs screened_at: clear only when every completion is before screened_at — confirm.
7. Countries: does "the approved identity document" country count even when the record's residence/nationality differ? (§6 Location lists it — we include it.)
8. Bible counts (766 hits / 379 alerts) are stale; current dev data is 819 hits / 440 alerts. Any other dev-set changes we should know about?
