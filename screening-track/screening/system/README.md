# Same Person or Not? — screening decision system

A deterministic, rule-based entity-resolution system for Track 2 ("Is my customer
sanctioned?"). It reads the data folder, works out who the customer really is and
who the listed person really is, compares the two under the bank's identity SOP
(`POLICY.md`), and writes one decision per hit with the records that decided it.

```
system/run <data folder> <output file>        # e.g. system/run dev output/dev.jsonl
python system/run dev output/dev.jsonl        # same thing on Windows
python validate.py --data dev --output output/dev.jsonl --score dev/practice_labels.jsonl
python -m unittest discover -s system/tests
```

Python 3.10+, standard library only. No network, no language model, no API key.
A full run on the development set (440 alerts, 819 hits, 72k customer records)
takes about 25 seconds on a laptop and costs nothing.

## Architecture

```
                    ┌──────────────────────────────────────────────────────────────┐
alerts.jsonl ──►    │ 1 resolve_customer   link (account / login / email) or search │
                    │   ▼                  joint holders picked by screened details │
                    │ 2 merge_person       same phone + full DOB, or same approved  │
                    │   ▼                  document number (chains)                 │
customers, accounts │ 3 customer_facts     latest APPROVED check (KYC row or KYC    │
onboarding, kyc,    │                      note) -> legal name, DOB, doc country;   │──► CustomerFacts
notes ─────────────►│                      countries from every record, document   │    (with the source id
                    │                      and "lived in" notes                     │     behind each fact)
                    └──────────────────────────────────────────────────────────────┘
                                                                                           ┌──────────┐
hits.jsonl ───────► 4 hit_facts   names+aliases; DOB from `dobs`, else first paragraph     │ 5 decide │──► 6 explain ──► output line
search_results ───►               of profile notes (age at a date -> two years), else      │  (SOP    │    evidence = records
                                  search results about the same listing in a hit country;  │  rules)  │    that decided it,
                                  countries; "According to …; <date>:" report lines; death └──────────┘    2–4 sentence reason
```

Modules (`system/src/`):

| Module | Role |
|---|---|
| `load.py` | Step 0. Reads every JSONL once; indexes by account id, login, email, phone, applicant id, note email, search query, normalised name part and birth year. |
| `dates.py` | The one date reader: ISO, `DD/MM/YYYY`, "19 May 2004", "May 19, 2004", bare years; partial dates stay partial. Also finds dates in free text and does the age arithmetic. |
| `countries.py` | Names, ISO codes, nationalities and "City, Region, Country" strings → ISO2. Territories are their own country; "International"/"Europe" are not countries. |
| `names.py` | SOP rule 8: normalisation, variant groups, together-or-apart parts, edit budget by part length, initials and placeholders, company legal forms. |
| `resolve_customer.py` | Step 1: alert → candidate persons. |
| `customer_facts.py` | Steps 2–3: merge records, verified identity from KYC rows **and** KYC notes, countries with provenance. |
| `hit_facts.py` | Step 4: the hit's picture. |
| `decide.py` | Step 5: the rules, in SOP order. Pure functions. |
| `explain.py` | Step 6: evidence selection and the reason text. |
| `pipeline.py`, `run` | Orchestration, fail-closed error handling, output. |

## How we find the customer

1. **Follow the link.** `account_ref → accounts → customer(s)`, `login_handle → accounts → customer`,
   `email → customer`. An account with joint holders yields two records; the screened name, date of
   birth, country and city pick the one that fits. If none fits on name (nicknames, typos) the other
   details decide; if still none, both are kept and the hit is decided for each.
2. **No link: search.** Candidates are blocked by the screened birth year (every unlinked alert has one)
   or by normalised name parts, then filtered: a full, preferred or login name that agrees with the
   screened name under rule 8, a DOB equal in every part both give, the screened country among the
   record's residence or nationality, the screened city inside the record's city or address. A
   missing detail never excludes a record.
3. **One person, one picture.** Starting from each fitting record we chain through records that share
   a phone number *and* the same full date of birth (dates read through the one date reader, since
   `September 12, 1985` and `1985-09-12` are the same day) or whose approved checks carry the same
   document number. All of a person's records contribute facts and are cited.
4. **Verified beats declared.** The person's identity checks are the KYC rows reached through
   onboarding **plus** the onboarding notes that write up a check ("Sumsub completed identity
   verification for NILS MARTIN, born …"). Notes are parsed structurally, not by template: the name in
   capitals, the birth date (the date next to a birth word or in brackets after the name, else the one
   date that is not the check date), the document country. A note with rejection wording is not
   evidence. The most recent approved check gives the legal name (`name_verified = true`), the DOB and
   the document country; otherwise the declared values are used and the name is not verified.
5. **Countries tied to the customer:** residence and nationality on every merged record, the document
   country of approved checks, and countries named in support notes that talk about living, working or
   being based somewhere. Adding a country can only make us review more, never clear more.

## How we find the listed person

- **Names:** `name`, `best_matching_name`, `aliases`.
- **Date of birth**, in SOP order: the `dobs` field; else the first paragraph of `profile_notes`
  ("born on 1 May 1957", "aged 45 in March 2019" → 1973 or 1974, "he was 46" with the paragraph's date);
  else search results for the name, and only a result that names the hit's listing type
  ("a politically exposed person", "the subject of enforcement action", …) **and** a country tied to the
  hit. Both candidate years from an age are kept; the rules need every hit date to contradict before
  clearing. Companies take only the `dobs` field (incorporation).
- **Countries:** `countries`, `nationality`, `citizenship`, the last part of each address, `place_of_birth`.
- **Earliest dated report:** exactly the lines "According to …; <Month D, YYYY>: …".
- **Death:** the `deceased_date` field.

## The rules

In this order; the first that fires gives the reason code. Partial dates clear only when the
contradiction holds under every completion.

1. Person vs company → `ENTITY_TYPE_MISMATCH`
2. Date of death certainly before screening → `DECEASED`
3. Oldest possible age at the earliest report < 16, or incorporation certainly after it → `TEMPORAL_IMPOSSIBILITY`
4. Every hit DOB contradicted (year more than 1 apart, or same year with a different month or day) → `DOB_MISMATCH`
5. Verified legal name agrees with none of the hit's names → `NAME_MISMATCH_VERIFIED`
6. Every customer country differs from every hit country, unless name and DOB agree → `LOCATION_MISMATCH`
7. Person with name and DOB agreeing: countries differ → `REVIEW`; countries agree → `NAME_DOB_LOCATION_MATCH`; no country → `NAME_DOB_MATCH`.
   Company with name and country agreeing → `NAME_LOCATION_MATCH`
8. Otherwise `REVIEW / INSUFFICIENT_DATA`

A customer whose names have fewer than two real parts can be neither confirmed nor cleared on name.
When several people fit an alert, each is decided; the same decision is given, otherwise
`REVIEW / AMBIGUOUS_CUSTOMER_RECORD`; either way `customer_record_id` is `AMBIGUOUS`.

## How we represent evidence

Every fact on the fact card carries the id of the record it came from: the DOB's source, the legal
name's source, and a map country → records. The output cites only what decided the hit, the way the
practice labels do:

| Reason code | Evidence |
|---|---|
| `DOB_MISMATCH` | the check or note that gave the customer's DOB, plus the search result that gave the hit's |
| `NAME_MISMATCH_VERIFIED` | the check or note behind the verified name |
| `LOCATION_MISMATCH` | every record that contributed a customer country |
| `TEMPORAL_IMPOSSIBILITY` | the person's records and the DOB source |
| `DECEASED` | the person's records and `H-xxxxxx#deceased_date` |
| `SAME_ENTITY` | the person's records, the DOB source, the search result if used |
| `REVIEW` | the person's records and the check or note that gave the name and DOB |

Hit facts come from the hit itself and are not cited, except search results.

## Determinism

No model, no randomness, no network. All indexes are plain dictionaries; candidate lists are sorted
by record id; checks are ordered by date then id; the output follows `hits.jsonl` order. Two
consecutive runs produce byte-identical files. If any step throws for a hit, that hit is answered
`REVIEW / INSUFFICIENT_DATA` and the error is logged to stderr: a crash can never clear a hit.

## Results on the practice labels

`validate.py --score dev/practice_labels.jsonl`: 50 of 50 decisions right, 0 unsafe clearances,
decision score 100, reason code accepted and customer record right on 100%, and the evidence list is
identical to the label's on all 50. On the whole development set the system clears 461 hits,
confirms 122 and reviews 236 (29%). Two consecutive runs are byte-identical.

## Three cases

**A clear mismatch — H-D6EDC1 (`DIFFERENT_ENTITY / LOCATION_MISMATCH`).** Alert A-C21BD3 has no link.
The screened name, DOB, country and city fit one record, CUS-401918; its onboarding leads to applicant
APP-D471F9 whose latest approved check KYC-60A0F7 gives the document country. Every country tied to the
customer is the United Kingdom; the hit MUHAMMAD NADEEM is tied only to Pakistan. Evidence:
`CUS-401918, KYC-60A0F7`.

**A match — H-582410 (`SAME_ENTITY / NAME_DOB_LOCATION_MATCH`).** Account ACC-C4CA34 has two holders;
the screened name and DOB fit CUS-377745. The customer has no KYC row, but the onboarding note
NOTE-14E25A records an approved check with DOB 1968-03-05. The hit's profile says she was "a 30-year-old"
in November 1998, so born 1967 or 1968, which agrees. Both are tied to Spain and the names agree.
Evidence: `CUS-377745, NOTE-14E25A`.

**Left for review — H-FA9F83 (`REVIEW / INSUFFICIENT_DATA`).** Account ACC-08D260 leads to CUS-783545,
whose latest approved check KYC-80B445 verifies the name Diana Cristian; the name agrees with the hit
and both are tied to Moldova. The hit gives no date of birth in its fields, notes or qualifying search
results, so nothing contradicts and the DOB cannot confirm. The reason says exactly that.

## Honest limits

- Free-text extraction is regex-based and conservative: a sentence it cannot read yields "unknown",
  which routes to REVIEW rather than a clear. New wordings in the unseen set will lower the clear
  rate before they produce an unsafe clearance.
- `DECEASED` needs a date; a `life_status` of "Deceased" without one is not used.
- Countries in prose are matched against a fixed table of names, codes and nationalities.
