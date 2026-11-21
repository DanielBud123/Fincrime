# Hardening log

Goal of this pass: stay right on wording and situations the development set never showed, without
adding a single unsafe clearance. An unsafe clearance costs 60; a needless review costs 2 or 3.

## Where it ended

| | Before | After |
|---|---|---|
| Practice labels right / unsafe clearances | 50 of 50 / 0 | 50 of 50 / 0 |
| Reason code, customer record, evidence identical to label | 100% / 100% / 50 of 50 | 100% / 100% / 50 of 50 |
| Dev set: cleared / confirmed / reviewed | 461 / 122 / 236 | 464 / 124 / 231 |
| Unit tests | 24 | 84 |
| Independent edge cases (`tools/independent_cases.py`) | not run | 177 pass, 0 wrong facts, 1 unknown on purpose |
| Two runs byte-identical | yes | yes |
| Run time, full dev set | 10–25 s | 6–12 s |

14 dev hits changed. None moved toward a riskier answer without an individual check (see "Effect on dev").

## The principle that came out of it

**A clear needs a complete, certain picture.** Hardening readers one sentence at a time cannot cover
wording nobody has seen. So every side of the fact card now says whether it is complete, and each clear
rule refuses to fire on an incomplete or uncertain fact. The hit then goes to REVIEW and is never
confirmed either, because something does contradict it. On dev these gates change nothing (no customer
has an incomplete picture); on unseen wording they turn a would-be wrong clear into a review.

**Reading more is not safer.** The worst change in this pass came from a reader that got *better*:
see "Tried and reverted".

## Findings, ranked

Level 1: a fact read wrongly with confidence that could clear a hit.

| # | Finding | Where | Fix | Test |
|---|---|---|---|---|
| 1 | "joseph" and "joe" are listed in two variant groups; the lookup kept one, so Yusuf and Joseph never matched: a false verified-name mismatch | `names.Variants` | a part keeps every group it is listed in | `TestNames.test_a_part_listed_in_two_groups_matches_both` |
| 2 | Report lines "…; as of May 15, 2019:", "…; found on March 04, 2026:", "…; June 2014:" and "…; 2016:" were all taken as dated reports; a too-early report fabricates an under-16 clear | `hit_facts.report_dates` | only "According to …; <full date>:" counts, parsed with no fallback | `TestReportLines` |
| 3 | When the latest approved check could not be read, an older check's name or DOB was used in its place | `customer_facts.build_customer_facts` | name and DOB come from the most recent approved check only; unreadable means unknown, and the gap blocks clears | `TestDob`, `TestTemporal`, `TestName` (uncertain cases) |
| 4 | A birth word within 40 characters made any date a DOB ("DOB 05/11/98; check date 2024-01-02" read the check date) | `customer_facts._dob_from_note` | the date must sit right after the birth word or in brackets after the name; document dates (issued, expires, valid until) are set aside; a date making the person a small child is refused | `TestIdentityNotes.test_dob_versus_document_and_check_dates` |
| 5 | Any note without a rejection word counted as an approved check | `customer_facts.note_status` | words that leave the outcome open (not, pending, under review, partially, re-upload, low-confidence, manual review …) rule approval out; a newer unreadable check blocks name and DOB clears | `TestIdentityNotes.test_soft_rejections_are_not_approvals` (15 cases) |
| 6 | An unknown or missing hit type was treated as "person", so a company customer cleared on type | `load.entity_kind`, `decide.assess` | unknown type is None and never contradicts | `TestEntityType.test_unknown_type_never_clears` |
| 7 | The unlinked search looked only at records with the screened birth year, missing records with no date of birth that fit by name; we then decided on one person when two fit | `resolve_customer._search` | candidates are that birth year plus every record with no readable date of birth | dev: one alert gained a third fitting person |
| 8 | Joint holders: if no holder's name fit, one was picked on date of birth alone | `resolve_customer.resolve` | a holder is picked only when it fits every screened detail; otherwise all are kept and decided | dev: all 58 joint alerts have exactly one full fit |
| 9 | A country value that did not map was silently dropped, on either side; a note naming a city, or a place we cannot map, added nothing | `countries.field_codes`, `places.py`, `customer_facts.read_support_note` | unmapped values make that side incomplete and block the location clear; cities and US states resolve; every country a note mentions is kept at least as a possibility, and a possibility the hit shares blocks the clear | `TestLocation`, `TestResidenceNotes` |
| 10 | Ages: "the 1960s" read as 1960; "born c. 1960" and "born between 1970 and 1972" read as one year; two ages or two years in a sentence resolved by position; "he was 46 kilometres" | `hit_facts.read_birth_facts`, `dates.find_dates` | one age, tied to one year, said of a person; approximations, ranges, relatives' ages and two-year sentences are reported as unread, never guessed | `TestBirthAndAgeReader` (26 read, 28 look-alikes) |
| 11 | A verified-name mismatch was decided on one way of splitting a name | `names.names_certainly_disagree` | the mismatch must hold with apostrophes dropped or split, with ø/ł/đ transliterated, and for companies with a wider list of legal forms; a hit whose names are only in another script is not comparable | `TestNames`, `TestName` |
| 12 | Listing phrases were also matched in shortened forms ("adverse media") | `hit_facts.result_is_about_hit` | exact SOP phrases only; the country must be in the result's own title or snippet | `TestSearchResultQualification` |
| 13 | Day-first was assumed for every numeric date | `dates.detect_numeric_order` | order detected per source from the data; a source showing both orders keeps only the year of an ambiguous date; watchlist text never inherits the bank's convention | `TestDates` |

Level 2: a rule situation the labels never exercised.

| # | Finding | Fix | Test |
|---|---|---|---|
| 14 | A contradiction that was blocked by a gate could still let the hit be confirmed on other facts | a blocked contradiction forces REVIEW | `TestConfirmation.test_a_blocked_contradiction_is_never_confirmed` |
| 15 | A check we cannot use that states a different name or DOB left confirmation open | `identity_conflict` blocks SAME_ENTITY | `TestConfirmation.test_identity_in_doubt_is_never_confirmed` |
| 16 | A note filed under the customer that names someone else was used as their verified identity | used only if it shares a name part with the customer or carries their exact date of birth | dev: the one such note carries the customer's exact DOB, so it stays in use |
| 17 | DECEASED, ENTITY_TYPE_MISMATCH, TEMPORAL boundaries, partial dates, several people, rule order: no tests | 41 rule tests from made-up fact cards | `TestDeceased` … `TestSeveralPeopleAndOrder` |

Level 3: a real fact the readers gave up on.

| # | Finding | Fix | Effect |
|---|---|---|---|
| 18 | "born on 27/06/1969" was not read from KYC notes ("on" was taken as a check-date cue); about 490 verified DOBs lost | birth word, then optional "on", then the date | KYC notes with DOB read: 22,076 → 22,565 of 22,575 |
| 19 | "Thomas P Walsh was 25 when taken into custody during February 1986" and "Mark E Phillips, at 24, was …": nine planted dev sentences neither old nor new reader read. The old system missed them silently; the new one first reported them as unread | read "<Name> was N when/at/…" with a capitalised name or person word before "was", and "<Name>, at N," | 4 new clears, 2 new confirms; each cross-checked against a sibling hit for the same person worded differently |

## Independent edge cases (second round)

`tools/independent_cases.py` was written outside this codebase, from the SOP and from how support
desks, KYC providers and watchlist providers write. It lists the acceptable answers per case and
separates a wrong fact from a missed one. First run: 169 pass, 6 wrong facts, 3 missed. After the fixes
below: **177 pass, 0 wrong facts, 1 missed on purpose**. No dev decision, reason code, evidence list,
customer record or reason text changed.

| # | Case | Verdict | Fix | Test |
|---|---|---|---|---|
| 20 | "Originally from Bangladesh, moved to the UK in 2008" gave BD only | **Valid, dangerous.** Two-letter codes were kept out of prose so the pronoun "us" would not match, which also dropped UK and US. A missed customer country is the route to an unsafe location clear | `countries.find_in_text` reads UK and US when written in capitals | `TestResidenceNotes.MUST_ADD`; "contact us" stays unread |
| 21 | "VAN DER BERG, PIETER" gave "van der berg" | **Valid, dangerous.** A surname-only verified name falsely mismatches a hit "Pieter Berg" | `customer_facts._caps_names` joins "SURNAME, GIVEN"; two full names either side of a comma are two people; a country after the comma is not a given name | `TestIdentityNotes.test_surname_first_keeps_the_given_name` |
| 22 | A snippet about "Luis Velasco Morillo" qualified for the hit Elvira Velasco Morillo | **Valid.** Same surname, listing and country, different person; his age would become her date of birth | `hit_facts.result_is_about_hit` also requires every word of one of the hit's names (initials aside) in the result. All 71 qualifying dev results still qualify | `TestSearchResultQualification.test_a_relative_with_the_same_surname_is_not_the_hit` |
| 23 | "the card works in Japan", "a Nigerian employer", "works for a Nigerian company remotely from Ireland" read as residence | **Valid, safe direction.** A false customer country cannot clear, but it is a false fact | "works" and "employer" are no longer residence words; `NON_RESIDENCE_RE` names what a note is about when it is not about living somewhere | `TestResidenceNotes.MUST_NOT_ADD` |
| 24 | "now 61 (2024)" and "DOB 1998/11/05" unread | **Valid, certain readings** | "now N" is an age; a year-first date is year-month-day whatever the separator | `TestBirthAndAgeReader.MUST_READ`, `TestDates` |
| 25 | "Born c. 1960." expected 1960 | **Not adopted.** An approximate year read as exact clears a customer born in 1962 (two years apart). It stays unknown and is reported as unread | none | `TestBirthAndAgeReader.MUST_STAY_UNKNOWN` |

Checking the dev notes against the tightened readers turned up three more things, none from the
independent set:

| # | Finding | Fix |
|---|---|---|
| 26 | Twelve genuine residence notes only raised a possibility: nine because "transfer inquiry … lived and worked in Spain" was taken for a plan, three because of vocabulary outside the cue list ("an inhabitant and employee in Kenya", "situated and active in the workforce in Romania") | A plan needs a plan word governing a move verb, and a past tense is never a plan. A support note that names a country now establishes it unless it is a plan or plainly about something else. On dev every one of 3,067 country-naming support notes is a residence note |
| 27 | Eight KYC notes with a certain date of birth were unread: "born in Bangladesh on 13/07/1983", "confirms a date of birth of 1974", "03/05/1976 DOB via national ID", "date of birth is set at 13/10/1967" | The birth word may be followed by "in <Place>", may come right after the date, and may introduce a year alone. 22,572 of 22,575 notes now give a date of birth |
| 28 | "previous check 2010-03-03" would have been read as a date of birth once old enough to pass the plausibility test | Dates after check, previous, refresh, verified, scheduled and similar words are check dates |

Still unread, on purpose: three dev notes say the document is "dated 1952-01-21". That is very likely the
date of birth, but it could be an issue date, so it stays unknown and blocks clears that would rest on it.

## Merge with the decision half (decision/names-decide)

| # | Finding | Fix | Effect |
|---|---|---|---|
| 29 | Name agreement depended on argument order: "stlogistics" written together matched "logistics" with two edits, and coverage was counted on the first name only when both names had as many parts. H-124BB8's verified-name clear held only because the customer's name is passed first | The decision half's rule: a joined pair gets the edit budget of its shortest piece, and coverage counts on both names | Order-dependent pairs on dev: 0 of 3,479. One reason text changed (H-5EEC5A: "Mun Chen" written together is "München", so the secondary name mismatch it cited was wrong); no decision changed |
| 30 | `decide.py` took the customer's name-part count from a field the caller can leave at 0, so a hand-built fact card was treated as having no usable name | Count the parts inside `decide.py` from the card's names; only a name with two or more real parts can agree (the decision half's per-name reading) | No dev change; the decision half's 27 tests now pass |
| 31 | An onboarding note saying the customer "gave birth on 2010-05-01" gave that date as her date of birth | "gave/give/giving birth" is not a birth word | No dev change |

## Tried and reverted

These are the changes that made things worse. They are the reason for the "reading more is not safer" rule.

1. **Reading month-first dates in watchlist profiles.** It made "DOB: 6/20/1955", inside a provider's
   record dump, readable. The customer was born 19 November 1955, so H-2C6B2E flipped from SAME_ENTITY to
   a DOB clear. But the dataset plants a search result putting this hit's birth year at 1955 or 1956, which
   the SOP allows only when the profile gives no date of birth. The answer key therefore treats the profile
   as giving none. **Fix:** a date of birth is read from the first paragraph only when it is one line of
   prose about the person; a record dump or a report line is never read, in either direction.
2. **Joining the `dobs` field with the first paragraph.** The labels speak of "the hit's listed date of
   birth" when the field is filled, so the SOP order (field, else paragraph, else search) is kept.
3. **Requiring a "passed" verb for an approved note.** 371 dev notes say "finalized", "concluded" or
   "underwent verification". **Fix:** a complete write-up (name and date of birth, nothing negative) is an
   approved check.
4. **Detecting date order over notes and watchlist text together.** It dropped the day and month of half
   the dates in KYC notes and broke evidence parity on two labels. **Fix:** per source.
5. **Counting report lines dated only by month or year.** Not reverted, but noted: three TEMPORAL clears
   rested on such lines. Two are still cleared on location; one (H-009799) is now a REVIEW. Counting them
   when the answer key does not is a 60; the reverse is a 3. See `docs/questions.md`.

## Effect on dev, hit by hit

| Change | Hits | Why |
|---|---|---|
| NAME_MISMATCH_VERIFIED → LOCATION_MISMATCH (still cleared) | 4 | company names that agree under a wider list of legal forms |
| TEMPORAL_IMPOSSIBILITY → LOCATION_MISMATCH (still cleared) | 2 | report line dated by month only |
| TEMPORAL_IMPOSSIBILITY → REVIEW / AMBIGUOUS_CUSTOMER_RECORD | 1 | report line dated "December 1998"; one of two fitting people is not otherwise cleared |
| REVIEW → REVIEW / AMBIGUOUS_CUSTOMER_RECORD | 1 | a third fitting person, a record with no date of birth |
| REVIEW → DIFFERENT_ENTITY / DOB_MISMATCH | 4 | finding 19; H-8C46EF, H-52BE0D, H-84E6E6, H-7A7ADF |
| REVIEW → SAME_ENTITY / NAME_DOB_LOCATION_MATCH | 2 | finding 19; H-2EBD19, H-792AF1 |

## Audits on the final code

- **Facts behind the 464 clears.** All 26 search snippets and all 20 profile sentences behind a DOB clear
  state one age and one year and are read correctly. Of 165 KYC notes behind a clear, 160 share a name part
  with the declared record and 151 match its date of birth; the rest are records with no declared date of
  birth or the dataset's deliberate "verified name differs" cases.
- **Rules with no label.** 4 DECEASED (death dates 3 to 5 years before screening), 1 ENTITY_TYPE_MISMATCH
  (a utility company against a person), 4 NAME_DOB_MATCH (hits with no country), 16
  AMBIGUOUS_CUSTOMER_RECORD (all unlinked alerts where several people fit), 22 TEMPORAL (all on full report
  dates). All read by hand; none changed.
- **Customer resolution.** 58 joint accounts: exactly one holder fits in each. No dead links. Unlinked:
  119 alerts with one person, 17 with two, 10 with three or more, none with nobody. 8 people whose latest
  check is not approved use the older approved one. 132 merged people; none loses a country. 7 shared
  document numbers each merge a record with no date of birth into its twin, which only that rule can do.
- **Verified-name clears (123).** 88 rest on the name alone. 95 share exactly one identical part with the
  best hit name, 28 share none. 50 take the name from a note. 28 hits carry an alias in another script. 10
  involve a short form (Md, Mohd, Abu). Counts are in `docs/questions.md`.
- **Guards on dev.** Incomplete customer countries: 0. Uncertain identity: 0. Identity conflict: 0. Hit
  countries unread: 0. Unread birth statements: 0. Blocked contradictions: 4 (the company names above).

## Not done, and why

- **Offline second reader with a language model.** No `OPENROUTER_API_KEY` in this environment, and it
  sends participant data to a model for no safety gain today.
- **Recovering more REVIEWs.** Beyond finding 19, nothing: each recovered clear is a 3-point gain against
  a 60-point exposure.
- **Push to the public repository.** Left to the team; nothing is committed by this pass.
