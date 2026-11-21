# Same Person or Not? — screening decision system

A deterministic, rule-based entity-resolution system for Track 2 ("Is my customer
sanctioned?"). It reads the data folder, works out who the customer really is and
who the listed person really is, compares the two under the bank's identity SOP
(`POLICY.md`), and writes one decision per hit with the records that decided it.

```
system/run <data folder> <output file> [diagnostics file]
python system/run dev output/dev.jsonl        # the same thing on Windows
python validate.py --data dev --output output/dev.jsonl --score dev/practice_labels.jsonl
python -m unittest discover -s system/tests
```

Python 3.10+, standard library only. No network, no language model, no API key.
A full run on the development set (440 alerts, 819 hits, 72k customer records)
takes about 10 seconds on a laptop and costs nothing.

## The idea in one line

**Clear only on a contradiction that rests on a complete, certain picture.** A wrong clear costs 60, a
needless review 2 or 3. So every reader returns a fact only when it is sure, says so when it met
something it could not read, and each clear rule refuses to fire on an incomplete or uncertain side.

## Architecture

```
                    ┌──────────────────────────────────────────────────────────────┐
alerts.jsonl ──►    │ 1 resolve_customer   link (account / login / email) or search │
                    │   ▼                  joint holders kept unless one fits fully │
                    │ 2 merge_person       same phone + full DOB, or same approved  │
                    │   ▼                  document number (chains)                 │
customers, accounts │ 3 customer_facts     most recent APPROVED check (KYC row or   │
onboarding, kyc,    │                      onboarding note) -> legal name, DOB;     │──► CustomerFacts
notes ─────────────►│                      countries from records, documents and    │    facts + source ids
                    │                      notes; gaps recorded                     │    + completeness
                    └──────────────────────────────────────────────────────────────┘
                                                                                           ┌──────────┐
hits.jsonl ───────► 4 hit_facts   names+aliases; DOB from `dobs`, else one sentence in     │ 5 decide │──► 6 explain ──► output line
search_results ───►               the first paragraph, else a search result about the same │ SOP rules│    evidence = records
                                  listing in a hit country; countries; dated report lines; │ + gates  │    that decided it,
                                  death; gaps recorded                                     └──────────┘    2–4 sentence reason
```

Modules (`system/src/`):

| Module | Role |
|---|---|
| `load.py` | Step 0. Reads every JSONL once; indexes by account id, login, email, phone, applicant id, note email, search query, name part and birth year. Detects whether numeric dates are day-first or month-first. |
| `dates.py` | The one date reader. Partial dates stay partial. Finds dates in free text; a bare year counts only in a time context. |
| `countries.py`, `places.py` | Names, ISO codes, nationalities and "City, Region, Country" strings → ISO2; reports any value it cannot map. Cities and US states for the customer's notes. |
| `names.py` | SOP rule 8, plus a stricter test used only for clearing: a mismatch must hold under every way of splitting the name. |
| `resolve_customer.py` | Step 1: alert → the people it could be about. |
| `customer_facts.py` | Steps 2–3: merge records, verified identity from KYC rows **and** onboarding notes, countries with provenance, gaps. |
| `hit_facts.py` | Step 4: the hit's picture and its gaps. |
| `decide.py` | Step 5: the SOP rules in order, each behind a completeness gate. Pure functions. |
| `explain.py` | Step 6: evidence selection and the reason text. |
| `pipeline.py`, `run` | Orchestration, fail-closed error handling, output, optional diagnostics. |

## How we find the customer

1. **Follow the link.** `account_ref → accounts → customer(s)`, `login_handle → accounts → customer`,
   `email → customer`. An account with joint holders yields two records; a holder is picked only when
   it fits every screened detail (name, date of birth, country, city). Otherwise all holders are kept
   and the hit is decided for each.
2. **No link: search.** A fitting record has a full, preferred or login name that agrees with the
   screened name under rule 8, a DOB equal in every part both give, the screened country among its
   residence or nationality, and the screened city inside its city or address. A missing detail never
   excludes a record: records with no date of birth are always candidates. Finding too few people is
   the dangerous direction, because we would decide on one person's facts when two fit.
3. **One person, one picture.** From each fitting record we chain through records that share a phone
   number *and* the same full date of birth, or whose approved checks carry the same document number.
4. **Verified beats declared.** The person's identity checks are the KYC rows reached through
   onboarding **plus** the onboarding notes that write up a check. A note is read structurally: the
   name in capitals, the birth date right after a birth word or in brackets after the name, the
   document country. It is an approved check only if nothing in it says otherwise ("not completed",
   "under review", "partially verified", "re-upload requested" all rule approval out). The legal name
   and date of birth come from the **most recent** approved check and from no other: if that check
   cannot be read, the fact is unknown, not replaced by an older one.
5. **Countries tied to the customer:** residence and nationality on every merged record, the document
   country of approved checks, and places a support note says they lived or worked, including cities
   and US states. Every country a note merely mentions is kept as a possibility.

## How we find the listed person

- **Names:** `name`, `best_matching_name`, `aliases`. A hit whose names are all in another script
  cannot be compared and is never cleared or confirmed on name.
- **Date of birth**, in SOP order: the `dobs` field; else **a sentence** in the first paragraph of
  `profile_notes` ("born on 1 May 1957", "aged 45 in March 2019" → 1973 or 1974); else search results
  for the name, and only a result that carries the hit's exact listing phrase and a country tied to
  the hit. An age is read only when the text states one age, tied to one year, about a person. A
  provider's record dump or a dated report line is not a sentence about a birth and is never read.
- **Countries:** `countries`, `nationality`, `citizenship`, the last part of each address,
  `place_of_birth`. Never widened: an extra hit country could create a clear.
- **Earliest dated report:** only lines "According to …; <full date>: …".
- **Death:** the `deceased_date` field. **Type:** person, company, or unknown.

## The rules

In this order; the first that fires gives the reason code. Partial dates clear only when the
contradiction holds under every completion. These are the SOP's rules, thresholds and order, unchanged.

1. Person vs company, both known → `ENTITY_TYPE_MISMATCH`
2. Date of death certainly before screening → `DECEASED`
3. Oldest possible age at the earliest report < 16, or incorporation certainly after it → `TEMPORAL_IMPOSSIBILITY`
4. Every hit DOB contradicted (year more than 1 apart, or same year with a different month or day) → `DOB_MISMATCH`
5. Verified legal name agrees with none of the hit's names → `NAME_MISMATCH_VERIFIED`
6. Every customer country differs from every hit country, unless name and DOB agree → `LOCATION_MISMATCH`
7. Person with name and DOB agreeing: countries differ → `REVIEW`; countries agree → `NAME_DOB_LOCATION_MATCH`; no country → `NAME_DOB_MATCH`.
   Company with name and country agreeing → `NAME_LOCATION_MATCH`
8. Otherwise `REVIEW / INSUFFICIENT_DATA`

**The gate in front of every clear.** A contradiction clears only when the facts behind it are complete
and certain. Otherwise it is recorded as *blocked*, the hit goes to REVIEW, and it is not confirmed
either, because something does contradict it.

| Clear rule | Refused when |
|---|---|
| `LOCATION_MISMATCH` | a country field on either side did not map; a support note says where the customer lived but names no place we can read; any record mentions a country the hit is tied to |
| `DOB_MISMATCH` | the customer's date is not from their most recent approved check; a newer check's outcome is unreadable; a listed hit date did not parse; the hit states a birth or age we could not read |
| `NAME_MISMATCH_VERIFIED` | the verified name is uncertain or has fewer than two real parts; the names agree under another way of writing them |
| `TEMPORAL_IMPOSSIBILITY` | the customer's date is uncertain; the report line is not a full date |
| `ENTITY_TYPE_MISMATCH` | either type is unknown |

On the development set no customer has an incomplete or uncertain picture, so the gates change no
decision there. They exist for wording nobody has seen.

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
| `REVIEW` | the records behind the agreeing country; for a blocked contradiction, the records it rests on |

When two clear rules hold, the first in SOP order is the code and both are explained and cited. Hit
facts come from the hit itself and are not cited, except search results.

The optional diagnostics file holds, per hit, the full fact card for each candidate customer: every
fact, its source record, every gap, and every contradiction that was seen but not relied on. It is the
content of an analyst screen. It is not part of the submission and is not committed, since it carries
more customer detail than the output needs.

## Determinism

No model, no randomness, no network. All indexes are plain dictionaries; candidate lists are sorted
by record id; checks are ordered by date then id; the output follows `hits.jsonl` order. Two
consecutive runs produce byte-identical files. If any step throws for a hit, that hit is answered
`REVIEW / INSUFFICIENT_DATA` and the error is logged to stderr: a crash can never clear a hit.

## Results and testing

`validate.py --score dev/practice_labels.jsonl`: 50 of 50 decisions right, 0 unsafe clearances,
decision score 100, reason code accepted and customer record right on 100%, and the evidence list is
identical to the label's on all 50. On the whole development set the system clears 464 hits,
confirms 124 and reviews 231 (28%).

84 unit tests. The readers are tested against rewordings in pairs: sentences that must be read, and
look-alikes that must stay unknown.

| Reader | Must read | Must stay unknown |
|---|---|---|
| Ages and birth dates | 31 | 30 ("PKR 11,000,000", "a 30-year sentence", "aged between 40 and 45", "born c. 1960", two ages in one sentence) |
| Support notes (residence) | 24 | 17 ("sent money to family in Nigeria", "the card works in Japan", "will relocate to Canada next year") |
| Onboarding notes (approval, name, date of birth) | 23 | 24 ("verification was not completed", "partially verified", "previous check 2010-03-03", two people in one note) |
| Dated report lines | 4 | 7 ("…; as of May 15, 2019:", "…; September 2025:") |
| Search result qualification | 6 | 8 ("law enforcement officer", country only in the query, a relative with the same surname) |

Zero false facts across these. 41 further tests cover rules the practice labels never exercise:
DECEASED, type mismatch, the age-15 and age-16 boundary, partial dates, several fitting people, rule
order, and every gate.

A second set, `tools/independent_cases.py`, was written outside this codebase from the SOP and from
how support desks, KYC providers and watchlist providers write. It lists the acceptable answers for
178 cases and separates a wrong fact from a missed one: **177 pass, 0 wrong facts**. The one case left
unknown is "Born c. 1960", which we do not read as exactly 1960. Its first run found six wrong facts,
two of them in the dangerous direction ("moved to the UK" dropped the UK; "VAN DER BERG, PIETER" lost
the given name); all are fixed and none changed a development-set decision.

`docs/hardening-log.md` records each finding, its fix and its effect, including the changes that were
tried and reverted.

## Three cases

**A clear mismatch — H-D6EDC1 (`DIFFERENT_ENTITY / LOCATION_MISMATCH`).** Alert A-C21BD3 has no link.
The screened name, DOB, country and city fit one record, CUS-401918; its onboarding leads to applicant
APP-D471F9 whose latest approved check KYC-60A0F7 gives the document country. Every country tied to the
customer is the United Kingdom, no note mentions another, and every country field mapped; the hit
MUHAMMAD NADEEM is tied only to Pakistan. Evidence: `CUS-401918, KYC-60A0F7`.

**A match — H-582410 (`SAME_ENTITY / NAME_DOB_LOCATION_MATCH`).** Account ACC-C4CA34 has two holders;
only CUS-377745 fits the screened name and DOB. The customer has no KYC row, but the onboarding note
NOTE-14E25A records an approved check with DOB 1968-03-05. The hit's profile says she was "a 30-year-old"
in November 1998, so born 1967 or 1968, which agrees. Both are tied to Spain and the names agree.
Evidence: `CUS-377745, NOTE-14E25A`.

**Left for review — H-009799 (`REVIEW / AMBIGUOUS_CUSTOMER_RECORD`).** Alert A-6E930F has no link and
two people fit it, both born in 1993. The hit's only report line is dated "December 1998", which is not
a full date, so the under-16 rule is not applied. One person is tied only to Ireland and would be cleared
on location; the other is also tied to the United States, where the hit is, and cannot be. The decisions
differ, so a person must decide which customer the alert is about.

## Known limitations

- **Free text is read by pattern.** A sentence the readers do not recognise is unknown or reported as
  unread, which leads to REVIEW. New wording in the unseen set lowers the clear rate before it produces
  an unsafe clearance. Not read: ages in words ("forty-five"), decades ("in his forties"), approximate
  or ranged years ("born c. 1960"), two-digit years, and a note that says a document is "dated" a day
  that is probably the date of birth.
- **Text that came with the watchlist record is not always a fact the SOP names.** We read a date of
  birth from one sentence in the first paragraph and from nothing else in the profile. Where a provider's
  record dump shows a "DOB:" line we do not use it (see `docs/questions.md`, question 2).
- **Report lines dated by month or year alone are not counted** as dated reports (question 1).
- **Names follow the SOP text literally.** "Md" is not Mohammad unless `name_variants.json` says so.
- **`DECEASED` needs a date;** a `life_status` of "Deceased" without one is not used.
- **A support note that names a country** ties the customer to it unless the note is a plan or is
  plainly about something else (a transfer, a holiday, a relative, an employer). In that case it does
  not tie them to it, but it still stops a location clear when the hit is tied to that country.
- **No language model.** Five scored runs with no cache would put reproducibility at risk, and a model's
  reading would have to be checked against the text before it could be trusted to clear anything.
