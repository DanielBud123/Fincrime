# Screening system handover (for the team)

The live, editable copy of this handover is the Claude doc "Screening System Handover"; this file is
the repo snapshot of it as of 2026-11-21.

## Where it stands

| Check (validate.py on the 50 practice labels) | Result |
|---|---|
| Decisions right | 50 of 50 |
| Unsafe clearances | 0 |
| Decision score | 100 |
| Reason code accepted, customer record right | 100% |
| Evidence list identical to the label | 50 of 50 |
| Unit tests (`system/tests/test_rules.py`) | 24 pass |
| Run time, full dev set | 10–25 s, byte-identical across runs |

Dev set (819 hits): 461 cleared, 122 confirmed, 236 reviewed. By code: LOCATION_MISMATCH 213,
NAME_MISMATCH_VERIFIED 127, DOB_MISMATCH 91, TEMPORAL_IMPOSSIBILITY 25, DECEASED 4, ENTITY_TYPE_MISMATCH 1,
NAME_DOB_LOCATION_MATCH 78, NAME_LOCATION_MATCH 40, NAME_DOB_MATCH 4, INSUFFICIENT_DATA 222,
AMBIGUOUS_CUSTOMER_RECORD 14.

```bash
python system/run dev output/dev.jsonl
python validate.py --data dev --output output/dev.jsonl --score dev/practice_labels.jsonl
python -m unittest discover -s system/tests
```

## How it works

0. `load.py` reads every JSONL once and indexes by account, login, email, phone, applicant, note email,
   search query, name part and birth year. `dates.py` is the one date reader (partial dates stay partial).
1. `resolve_customer.py`: follow account_ref / login_handle / email; joint holders split by the screened
   details; no link → block by screened birth year, filter by name (rule 8), DOB, country, city.
2. `customer_facts.merge_person`: chain records sharing phone + full DOB, or an approved document number.
3. `customer_facts.build_customer_facts`: latest approved check (KYC row **or** KYC note) → legal name, DOB,
   document country; countries from all records, approved documents and residence-worded notes; every fact
   carries its source id.
4. `hit_facts.py`: names + aliases; DOB from `dobs`, else first paragraph (age → two years), else search
   results with the listing phrase and a hit country; countries; "According to …; date:" report lines; death.
5. `decide.py`: SOP rules in order; partial-date certainty; all firing clear rules recorded.
6. `explain.py`: evidence per label conventions; 2–4 sentence reason; several people → AMBIGUOUS.

Any exception for a hit → REVIEW / INSUFFICIENT_DATA (fail closed).

## Decisions to challenge

| Decision | Where | What breaks if wrong |
|---|---|---|
| Single-customer link followed without a fit check | `resolve_customer._by_link` | Relative's login resolves the wrong person |
| Joint holders picked by screened details; none fit → keep both | `resolve_customer.resolve` | Wrong pick uses another customer's facts |
| No-link search blocked by screened birth year | `resolve_customer._search` | Year typo → nobody found → REVIEW null |
| Merge on customer-record phone + full DOB, or shared approved doc number | `customer_facts.merge_person` | Missed merge loses countries → REVIEW becomes clear |
| Latest approved check (row or note) wins; negative wording drops a note | `customer_facts.identity_checks` | Mis-parsed note name → false NAME_MISMATCH_VERIFIED |
| Notes add a country only with living/working/address/origin wording | `customer_facts.RESIDENCE_RE` | Load-bearing: when it broke, 3 labelled REVIEWs became unsafe clears |
| Hit DOB: field → first paragraph → qualifying search; ages give two years | `hit_facts.build_hit_facts` | Wrong age reading fabricates a DOB → false DOB_MISMATCH |
| Search result needs listing phrase + a hit country | `hit_facts.result_is_about_hit` | Namesakes feed false DOBs |
| Evidence copies label conventions; hit ids never cited | `explain.py` | Reasons mark drops |
| Rule 8 per SOP text, not the team brief | `names.py` | Too strict → wrong verified-name clears (cost 60) |
| No LLM | whole system | Some REVIEWs left on the table |

## Edge cases to probe (tried today)

**Dates.** Read: ISO, `19/05/2004`, `05-11-1998`, `13.07.1969`, `February 19, 2002`, `Nov. 5, 1998`,
`5th November 1998`, `1996`, `1962-09`. Unknown: `1998/11/05`, `05.11.98`. Slash dates are always day-first
(provably right in dev; a US-ordered source would swap month/day → possible false DOB_MISMATCH).
"born between 1970 and 1972" → 1970 only.

**Ages** (`hit_facts.dobs_from_text`). Read: "a 30-year-old", "he was 46", "aged 45", "at the age of 33",
"Raković, 29, a politically exposed person", "turned 50", "Age: 55", "born on 1 May 1957", "born in 1966".
Unknown: "in his forties", "forty-five", "At 52, in June 2011", "was 32 at the time of his arrest in 2004",
"now 61 (2024)", "(b. 1960)". Fixed today: "PKR 11,000,000" was read as age 11 → fake years → wrong clear;
now a word must precede the comma and a lowercase word must follow the age. Try to break it with amounts,
addresses, phone numbers, lists. The age's date = first date after the age, else first date in the paragraph.

**Names.** "Md" is not a variant of Mohammad → verified "MD AMIN" vs hit "Mohammad Amin" clears (ask
organisers). Initials dropped → "J. Smith" agrees with "John Smith"; one-word alias "Smith" agrees too.
Parts under 4 letters must be identical ("Lee Wei" ≠ "Li Wei"). Particles count as parts. Non-Latin aliases
never match and give an empty search key.

**Countries.** US states/cities are not countries ("Texas", "New York" → nothing). Adjectives match in prose
("Swiss bank account" → CH). "Congo" → CG; "Georgia" → GE unless ", United States"; "New Jersey" → US.

**Notes.** Residence needs a living/working/address/origin word: "sent money to family in Nigeria" and
"holidayed in Spain" add nothing; "relocated to Kenya", "Confirmed address in Portugal" add the country.
A KYC note naming two different people → no name. Two unanchored dates → no DOB. Negative words: reject, fail,
unable, could not, expired, declined, unsuccessful, not verified/confirmed/validated/approved/matched, mismatch,
inconclusive, pending, incomplete, refused, denied, invalid, fraud, suspicious, flagged. "verification was not
completed" is NOT caught.

**Resolution.** Dead link → search. City match is substring both ways ("York" matches "New York"). Only the
customer-record phone merges; 7 shared document numbers in dev are untested by labels.

**Hit side.** DECEASED needs `deceased_date`. Only "According to …; Month D, YYYY: …" lines are reports.
A hit with no country never uses search results. Companies: only `dobs`.

**Rules.** One-year gap neither agrees nor contradicts. TEMPORAL/DECEASED need certainty under every
completion of partial dates. Two firing clear rules → first in SOP order is the code, both are cited.

## How to test an idea in two minutes

```python
import sys, json; sys.path.insert(0, "system/src")
from hit_facts import dobs_from_text
from customer_facts import _name_from_note, _dob_from_note, residence_countries
from countries import find_in_text
from names import Variants, names_agree
from dates import parse_date
V = Variants(json.load(open("dev/name_variants.json", encoding="utf-8")))
print(dobs_from_text("When questioned in January 2023, he was 46."))        # [1976, 1977]
print(residence_countries({"text": "The client lived and worked in Denmark from 2016 to 2018."}))
print(names_agree("Mohamed Ali Hassan", "Muhammad Hasan", V))
```

```python
import sys; sys.path.insert(0, "system/src")
from load import load; from pipeline import Pipeline
data = load("dev"); p = Pipeline(data)
hit = data.hits["H-2017F1"]
print(p.decide_one(data.alerts[hit["alert_id"]], hit).to_output_line())
```

Rule cases: copy a `test_NN` in `system/tests/test_rules.py`. A wrong practice hit: compare the label's `path`
list in `dev/practice_labels.jsonl` with the fact card (`p.customer_cards(alert)`, `hit_facts.build_hit_facts`).
A useful finding = something the system reads **wrongly with confidence**, plus the function that reads it.

## Open questions (see docs/questions.md)

Hit-field evidence (`H-xxx#deceased_date`) penalised? "Md" = Mohammad? Account phones in the merge? Dead link →
search or null? Same decision for several people → cite all records? `life_status` Deceased without a date?
REVIEW evidence = agreeing-country records only?

## Ownership

`names.py`, `decide.py`: decision half, provisional (SOP wording). `schema.py`: superset of the agreed card.
Everything else: data half, done. Not done: public GitHub repo (root currently `Fincrime/`), no LLM fallback
(deliberate). Effort order: wording that creates a false fact → wording that loses a real fact → open questions.
