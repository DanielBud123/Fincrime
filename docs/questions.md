# Open questions (take to office hours; do not guess)

Decisions we took in code are marked **(we do X)**. The first section is new from the hardening pass and
holds the questions that move the score most.

## Highest value: each of these is a 60-point question

1. **Report lines dated only by month or year.** Dev has 642 lines "According to …; September 10, 2025:",
   but also 32 like "…; June 2014:", 9 like "…; 2016:" and 6 like "…; as of May 15, 2019:". Do the
   month-only and year-only lines count as dated reports for the under-16 and incorporation rules?
   Example: H-009799, "According to United States-Financial Industry Regulatory Authority; December 1998:",
   customer born 1993. **(we count only full dates; that hit is a REVIEW)**
2. **A date of birth inside a provider's record dump.** H-2C6B2E and H-FE02A6: the profile's first paragraph
   is "Name: James, Richard / Alias: … / DOB: 6/20/1955 / Height: …", and a planted search result puts the
   birth year at 1955 or 1956. The customer was born 19 November 1955. Is the profile's "DOB:" line the
   hit's date of birth (then the answer is DIFFERENT_ENTITY on month), or does only a sentence count (then
   the search result applies and the answer is SAME_ENTITY)? **(we read only a one-line sentence about the
   person, so SAME_ENTITY)**
3. **Short forms that are not in `name_variants.json`.** Md, Mohd, Muhd for Mohammad; Abu; Jr and Sr. A
   verified "MD AMIN" against a hit "Mohammad Amin" does not agree and clears. 10 of our 123 verified-name
   clears involve such a form; 40 involve a part under 4 letters. **(we follow the SOP text)**
4. **A verified name that shares nothing with the declared name.** NOTE-0344BB, filed under Hadiza Adewale,
   verifies "EMEKA EMEKA NWOSU" with her exact date of birth; KYC-AA315D verifies "ZAINAB CHINEDU ADEYEMI"
   for the record "Park Bello". Is that the customer's verified legal name? **(yes when it is a KYC row, or
   a note carrying the customer's exact date of birth or a shared name part; otherwise the note is treated
   as someone else's and not used)**
5. **Records with no date of birth in an unlinked search.** "A date of birth equal to the screened one in
   every part both give": a record with no date of birth fits on that point. Confirmed? Example: alert
   A-BB31D5 then has three fitting people instead of two. **(yes, they fit)**
6. **An identity check whose outcome is not stated.** A note such as "X underwent Sumsub verification on
   2023-03-14 using a national ID" has no "approved" or "passed". Is it an approved check? **(yes when it
   names the person and gives the date of birth and says nothing negative)**

7. **An approximate birth year.** "Born c. 1960": is 1960 the hit's birth year for the "more than 1 year
   outside" test, or is the date unknown? A customer born in 1962 would be cleared on the first reading.
   **(unknown)**
8. **A search result about a relative.** A result that carries the hit's listing phrase and country but
   names someone with the same surname and a different given name: about the hit? **(no: the result must
   contain every word of one of the hit's names)**

## Scoring and format
- Does `evidence` get penalised for citing the hit's own record (`H-xxxxxx`) or a `H-xxxxxx#field` reference? The
  practice labels never cite hit ids, only CUS/KYC/NOTE/SR. **(we cite only customer-side records and SR ids,
  plus `H-xxxxxx#deceased_date` for DECEASED, which has no label example)**
- For REVIEW / INSUFFICIENT_DATA the labels cite the records behind the agreeing country. Confirmed?
  **(we do that; failing an agreeing country, the identity source and the linked record)**
- When several people fit and all lead to the same decision, the labels cite every person's records. Confirmed?
  **(we do that, with `customer_record_id` = AMBIGUOUS as POLICY.md principle 3 says)**

## Customer side
- Do account phone numbers count for the "same phone and full DOB" merge, or only the phone on the customer record?
  All 13 label merges work with the customer-record phone. **(we use customer-record phones only)**
- A link that leads to a dead reference (account/login/email not found): search by screened details, or REVIEW
  with null? Dev has none. **(we fall back to the screened-details search)**
- Joint holders where no holder fits every screened detail: keep both (→ ambiguous) or none? Dev has none: all 58
  joint alerts have exactly one full fit. **(we keep both)**
- Does a support note that names a country without a "lived" or "worked" word count as a place they lived?
  On dev every country-naming support note is a residence note, in 2,400 wordings. **(yes, unless the note is
  a plan or is plainly about a transfer, a trip, a relative or an employer; then the country is kept as a
  possibility, and a location clear is refused when the hit is tied to it)**
- An onboarding note that says a document is "dated 1952-01-21": date of birth or issue date? Three dev notes.
  **(unknown; clears that would rest on it are refused)**
- Should the document country of older approved checks count, or only the latest approved check's?
  **(all approved checks' countries count)**
- A support note that says where the customer lived with a city or a state ("moved to Texas"): does the
  country count? **(yes, through a general table of cities and US states; a place we cannot map blocks the
  location clear)**

## Hit side
- A `life_status` of "Deceased" with no `deceased_date`: can DECEASED ever fire? **(no: it needs a date before screening)**
- Should "born"/age sentences outside the first paragraph of `profile_notes` count? **(no, first paragraph only)**
- When several qualifying search results give different ages, do all their years count as the hit's possible years?
  **(yes, union; only every DOB contradicting clears)**
- When the `dobs` field is filled, does a sentence in the first paragraph add further dates? The labels say
  "the hit's listed date of birth". **(no: field first, else paragraph, else search)**
- Nationality fields holding "City, Region, Country": last part only, confirmed? **(yes)**
- A country field value that is not a country we know (a city alone, an unusual spelling): ignore it, or treat
  the hit's countries as incomplete? **(incomplete: no location clear)**
- A hit whose `entity_type` is missing or neither person nor company: can ENTITY_TYPE_MISMATCH fire? **(no)**

## Rules (for the decision half)
- Rule 8 vs team brief: the SOP says single letters are initials and not parts, parts under 4 letters must be
  identical, 4–6 letters allow 1 edit, 7+ allow 2, and names agree when ≥2 parts match OR every part of the
  shorter name matches. **(we follow the SOP wording)**
- A part listed in two variant groups (joseph, joe): does it match the members of both? **(yes; the groups are
  not chained, so yusuf does not match jose)**
- Does a customer alias (preferred name) count toward agreement? **(yes for agreement; the verified legal name
  alone decides NAME_MISMATCH_VERIFIED)**
- Which reason code when two clear rules fire? **(labels accept any; we use the SOP order: type, death, time,
  DOB, verified name, location)**
- Company legal forms not in the list (Pty, Sociedad Anónima, S.r.l.s., Holdings): are they name parts?
  **(yes for agreement, per the SOP; but a verified-name clear must also hold with them dropped)**
