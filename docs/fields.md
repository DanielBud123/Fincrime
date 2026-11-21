# Field reference: `dev/*.jsonl`

Real field names and ID formats, from the data room. One record per line.
The browse workbook (`screening-dev-browse.xlsx`) shows the same data with list
fields joined by `; ` and the alert's screened customer flattened into columns.

## IDs

| Prefix | File | Example |
|---|---|---|
| `A-` + 6 hex | alerts | `A-ED1B2D` |
| `H-` + 6 hex | hits | `H-00E181` |
| `CUS-` + 6 digits | customers | `CUS-380174` |
| `ACC-` + 6 hex | accounts, onboarding, alerts.account_ref | `ACC-0CF658` |
| `APP-` + 6 hex | onboarding.kyc_applicant_id, kyc_checks.applicant_id | `APP-0000DB` |
| `KYC-` + 6 hex | kyc_checks | `KYC-00030A` |
| `NOTE-` + 6 hex | notes | `NOTE-00009B` |
| `SR-` + 6 hex | search_results | `SR-7B5B39` |

Evidence in the output may also be a URL or `H-xxxxxx#<field>` (validate.py accepts both).

## alerts.jsonl (440)

`alert_id`, `screened_at` (ISO date), `customer` {`name`, `entity_type` "Individual" | "Company",
`dob` (ISO or year; 188 null), `country` (name; null unless no link), `city`}, `account_ref`,
`login_handle`, `email` (at most one is set; 146 alerts have none), `hit_ids` (list).

Link counts: account 170, login 70, email 54, none 146. Every no-link alert has a DOB and a country.

## hits.jsonl (819)

`hit_id`, `alert_id`, `match_score`, `entity_type` "Individual" | "Company", `name` (often "Surname, Given"),
`first_name`/`middle_name`/`last_name`/`best_matching_name` (usually null), `aliases` (list),
`gender`, `dobs` (list of "YYYY" | "YYYY-MM" | "YYYY-MM-DD"; 152 non-empty), `place_of_birth`
(may be "City, Region, Country" and may hold several places separated by `;`), `life_status`
("Alive" | "Deceased" | null), `deceased_date` ("YYYY-MM" | "YYYY-MM-DD"; 4 set), `nationality`,
`citizenship`, `countries` (lists of names, sometimes full addresses), `addresses` (list; each
ends with the country, then a `[Role]` tag), `identifiers`, `categories` (list), `primary_category`
(null for 345), `subcategories`, `position_or_allegation`, `details` (object), `relationships`,
`profile_notes` (free text; dated reports are lines "According to <source>; <Month D, YYYY>: ..."),
`sources`, `source_urls`.

## customers.jsonl (72,265)

`record_id`, `entity_type`, `full_name`, `preferred_name` (16k set), `login_name` (always null in dev),
`dob` (mixed: ISO, `DD/MM/YYYY` (always day first), "19 May 2004", "May 19, 2004", "May 9, 2004", bare year),
`nationality` (country name or adjective: "Nigeria" / "Nigerian"), `residence_country` (name or ISO2 code),
`city`, `address`, `email` (unique), `phone` ("+CC digits"), `occupation`, `employer`, `registration_number`,
`onboarded_at`, `status`, `last_kyc_refresh`.

## accounts.jsonl (86,659)

`account_id`, `customer_id`, `login_handle` (unique), `phone`, `opened_at`, `status`.
52 accounts have two holders (two rows with the same `account_id`).

## onboarding.jsonl (72,265)

`account_id`, `customer_id`, `kyc_applicant_id` (one per customer), `onboarded_at`.

## kyc_checks.jsonl (54,488)

`check_id`, `applicant_id`, `provider` (Sumsub, Veriff, Persona, Onfido, "Companies registry lookup"),
`verified_name`, `verified_dob` (same mixed formats as customers), `document_type`, `document_number`,
`document_country` (name), `result` ("approved" 49,574 | "rejected" 2,481 | "expired" 2,433), `checked_at`.
4,914 applicants have more than one check; 7 document numbers are shared by two applicants.

## notes.jsonl (31,895)

`note_id`, `requester_email` (= customers.email), `created_at`, `channel` ("kyc" 22,575 | "phone" 5,091 |
"app" 2,146 | "email" 2,083), `text`.
`kyc` notes are identity checks written up by onboarding: name in CAPITALS, a DOB, a check date, a
provider, a document and a country, in ~17,000 different wordings. Other channels hold routine support
notes plus ~2,400 sentences saying where the customer lived and worked ("resided in Austria from 2013 to 2017").

## search_results.jsonl (16,882)

`result_id`, `query` (the name's lower-case words in alphabetical order, accents stripped), `title`,
`snippet`, `source`. Snippets are templated: a name, an age, a role or listing phrase, a country and a
month/year. Listing phrases: "a sanctioned individual", "a politically exposed person", "the subject of
enforcement action", "named in adverse media", "a state-owned enterprise official", "named on a watchlist".

## practice_labels.jsonl (50)

`hit_id`, `alert_id`, `decision`, `reason_codes` (list; any is accepted), `customer_record_ids`
(list of all records of the person, or `["AMBIGUOUS"]`), `evidence` (list), `reference_reason`, `path` (list of steps).
Label mix: 28 DIFFERENT_ENTITY, 12 SAME_ENTITY, 10 REVIEW.

## name_variants.json

`{"description", "groups": [[...], ...], "company_legal_forms": [...]}` — 55 groups of given-name forms, 30 legal forms.
