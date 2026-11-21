# Open questions — decision half (names.py, decide.py)

Kept apart from `docs/questions.md` (data half) until we merge. Decisions taken in code are marked **(we do X)**.

## For the 15:00 mentors
- Does a 1-year birth-year gap count as "agree" for confirmation? **(no: neither agrees nor contradicts → REVIEW)**
- Declared name agrees but the verified legal name does not: clear on NAME_MISMATCH_VERIFIED? **(yes, §6 "even if
  the name on their record does")**
- "An individual customer whose names have fewer than two real parts can be neither confirmed nor cleared on name":
  per name or across all the customer's names? **(per name: a one-part verified legal name never clears, and only
  names with ≥2 real parts can confirm)**
- Placeholder "digits and the like": pure-digit tokens only, or mixed tokens like "N26" (label H-24D490)?
  **(pure digits only)**
- Partial date of death (`"2022-03"`) vs screened_at. **(clear only when every completion is before screening)**
- A part listed in two variant groups (joseph/joe are in the Yusuf group and the Joseph group): match either group?
  **(yes: Yusuf ~ Joseph)**
- Which reason code when two clear rules fire? **(labels accept any; order: type, death, time, DOB, verified name,
  location)**

## For the data half (at merge)
- Interface: `decide(card, variants)` returns `(Decision, Assessment)` like the provisional version, not a bare
  `Decision` as the brief says, so explain.py keeps writing evidence and reasons. `decide_hit(alert_id, hit,
  candidates, screened_at, variants)` exists per the brief; pipeline.py does the same loop itself today.
- `decide.py` ignores `CustomerFacts.real_name_parts`; it counts real parts per name itself.
- `names.Variants.group_of` (one group id per part, used for name blocking in load.py / resolve_customer.py) keeps the
  lowest group id; matching uses `groups_of`. A no-link, no-DOB search for "Yusuf" will not block in a "Joseph"
  record. Low impact (every no-link alert has a DOB).
- `test_rules.py` fallback legal forms (used when `dev/` is absent) lack `"se"`, so `test_rule_8` fails without the
  data folder. One word to add.
- Unsafe-clear surfaces on the data side: identity notes count as approved unless negative wording, and their
  CAPS-extracted name sets `name_verified` (can fire NAME_MISMATCH_VERIFIED); note-derived DOBs feed
  DOB_MISMATCH/TEMPORAL; `BIRTH_RE` reads "gave birth in 2010" as a DOB; `DD/MM/YYYY` is assumed day-first; hit
  countries missing from the country table are dropped silently; the no-link search blocks by birth year, so records
  without a parseable DOB are never found. Some reasons are one sentence (brief asks 2–4).
- Layout: the brief calls `system/run` and wants `system/` and `output/` in the repo. Proposal: move them to the
  repo root at merge (one `git mv` commit).
