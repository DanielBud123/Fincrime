"""Independent edge cases for the screening readers.

Written outside Claude Code, from the SOP and from how a payments company's
support desk, KYC providers (Sumsub/Veriff/Persona/Onfido) and watchlist
providers actually write. Run from screening-track/screening/:

    python tools/independent_cases.py

Every case lists the answers that are ACCEPTABLE. Anything else is reported.
Two severities:
  WRONG FACT  - the reader produced a fact that is not acceptable (can clear a hit: cost 60)
  MISSED      - the reader returned unknown where a fact was readable (cost 2-3)
Fix WRONG FACT cases first. A MISSED case is only worth fixing if the reading
would be certain under every interpretation.

Wiring notes (the cases themselves are as written by the independent author):
- sections E and F are connected to hit_facts.earliest_report_date and
  hit_facts.result_is_about_hit;
- "approved?" in section C asks the real status reader (customer_facts.note_check),
  because approval is decided from negative, hedging and positive wording together,
  not from NEGATIVE_RE alone.
"""
import json
import sys

sys.path.insert(0, "system/src")

from dates import parse_date                                   # noqa: E402
from names import Variants, names_agree                        # noqa: E402
from hit_facts import dobs_from_text, earliest_report_date, hit_countries, result_is_about_hit  # noqa: E402
from customer_facts import APPROVED, _name_from_note, _dob_from_note, note_check, residence_countries  # noqa: E402


def _earliest_report(text):
    d = earliest_report_date({"profile_notes": text})
    return d.iso() if d else None


REPORT_DATES_FN = _earliest_report
RESULT_ABOUT_FN = lambda row, hit: result_is_about_hit(row, hit, hit_countries(hit))   # noqa: E731

V = Variants(json.load(open("dev/name_variants.json", encoding="utf-8")))

report = {"WRONG FACT": [], "MISSED": [], "PASS": 0, "SKIP": 0}


def years_of(result):
    """Normalise whatever dobs_from_text returns to a sorted list of years."""
    out = set()
    for r in result or []:
        y = getattr(r, "year", None)
        if y is None:
            try:
                y = int(str(r)[:4])
            except ValueError:
                continue
        out.add(int(y))
    return sorted(out)


def check(group, text, got, acceptable, wrong_if_not_in_acceptable=True):
    """acceptable: list of acceptable answers. Unknown ([] / None) is always
    SAFE: if it is not acceptable it is a MISSED, never a WRONG FACT."""
    if got in acceptable:
        report["PASS"] += 1
        return
    is_unknown = got in ([], None, "", False)
    sev = "MISSED" if is_unknown or not wrong_if_not_in_acceptable else "WRONG FACT"
    report[sev].append((group, text, got, acceptable))


# ---------------------------------------------------------------------------
# A. Ages and birth dates in watchlist profile paragraphs  (dobs_from_text)
#    SOP: an age at a date gives TWO possible birth years. Unknown stays unknown.
# ---------------------------------------------------------------------------
A = [
    # must read
    ("Formal charges were brought against Elvira Velasco Morillo, aged 30, in November 1998.", [[1967, 1968]]),
    ("Sentenced in March 2019 at the age of 45 to six years' imprisonment.", [[1973, 1974]]),
    ("Raković, 29, a politically exposed person, was named in a report dated 4 June 2021.", [[1991, 1992]]),
    ("A 30-year-old man was arrested in Lagos on 5 May 2020.", [[1989, 1990]]),
    ("Born on 12 March 1962 in Cairo.", [[1962]]),
    ("Mohamed Ali (born 14 March 1988) was named in the indictment.", [[1988]]),
    ("Born c. 1960.", [[1960]]),
    ("Born in 1966; died in 2020.", [[1966]]),
    ("Date of birth: 05/11/1998.", [[1998]]),
    ("Age: 55 (as of 2024).", [[1968, 1969]]),
    ("Appointed CEO at age 45 in 2010; resigned in 2020.", [[1964, 1965]]),
    ("Aged 45 in March 2019.", [[1973, 1974]]),
    # should read, unknown is tolerable (MISSED)
    ("(b. 1960)", [[1960]]),
    ("now 61 (2024)", [[1962, 1963]]),
    ("DOB 1998/11/05", [[1998]]),                       # year is certain even if day/month order is not
    # ambiguous: unknown OR the one consistent reading; anything else is a wrong fact
    ("Born between 1970 and 1972.", [[], [1970, 1971, 1972]]),
    ("Aged 45 at the time of the 2019 conviction, he was 52 when released in 2026.", [[], [1973, 1974]]),
    ("He was 46 when questioned in January 2023; his brother, 52, was also named.", [[], [1976, 1977]]),
    ("Her son, born 1995, was also charged; she was 48 at the time (2019).", [[], [1970, 1971]]),
    # must stay unknown
    ("The fine of PKR 11,000,000 was imposed in 2025.", [[]]),
    ("Case No. 45/2019 concerns the subject.", [[]]),
    ("Sentenced to 30 years in prison in 2015.", [[]]),
    ("He received a 30-year sentence in 2020.", [[]]),
    ("The 45-count indictment was unsealed in 2020.", [[]]),
    ("Director since 2001; previously at the firm from 1990 to 1999.", [[]]),
    ("Born 05.11.98.", [[]]),                             # two-digit year: century unknown
    ("In his forties at the time of the 2015 scandal.", [[]]),
    ("He is 45.", [[]]),                                  # no date anywhere
    ("The company, founded in 1998, employs 45 people.", [[]]),
    ("Sanctioned on 24 February 2022; believed to be in his early 60s.", [[]]),
    ("Contact +44 7700 900045, last seen 2021.", [[]]),
    ("Fined EUR 45,000 in 2019.", [[]]),
    ("Section 45 of the Act was applied in 2019.", [[]]),
    ("Served 12 years as mayor until 2019.", [[]]),
    ("Owns 45% of the company since 2015.", [[]]),
]
for text, acc in A:
    check("A dobs_from_text", text, years_of(dobs_from_text(text)), acc)

# ---------------------------------------------------------------------------
# B. Residence countries from support notes  (residence_countries)
#    SOP: countries tied to the customer include "places the notes say they lived".
#    This reader is load-bearing: a missed residence country can turn a REVIEW
#    into an unsafe LOCATION_MISMATCH clear; a false one can hide a real mismatch.
# ---------------------------------------------------------------------------
B = [
    # must add
    ("Customer relocated to Kenya in 2015 and updated their address.", [["KE"]]),
    ("Address on file: 12 Marina Road, Lagos, Nigeria.", [["NG"]]),
    ("Spent 2010-2014 in Canada on a work visa.", [["CA"]]),
    ("Originally from Bangladesh, moved to the UK in 2008.", [["BD", "GB"], ["GB", "BD"]]),
    ("Holds a residence permit for Italy.", [["IT"]]),
    ("Previously lived in Serbia; now resident in Austria.", [["RS", "AT"], ["AT", "RS"]]),
    ("Employment and residency in the United States from 2012 to 2016.", [["US"]]),
    ("The customer has been resident in Portugal since 2019.", [["PT"]]),
    ("Grew up in Ghana and moved to Ireland for university.", [["GH", "IE"], ["IE", "GH"]]),
    ("Registered address: Hauptstrasse 5, Berlin, Germany.", [["DE"]]),
    # should add via a city/state table; unknown tolerable
    ("Customer confirmed they are based in Dubai for work.", [["AE"]]),
    ("The client's home is in Madrid.", [["ES"]]),
    ("Returned to Ghana after ten years in London.", [["GH", "GB"], ["GB", "GH"], ["GH"]]),
    ("Lived in Texas before moving to Mexico.", [["US", "MX"], ["MX", "US"], ["MX"]]),
    ("Based in Lagos.", [["NG"]]),
    # must NOT add
    ("Customer asked about fees for transfers to Nigeria.", [[]]),
    ("Sent money to family in Pakistan.", [[]]),
    ("Holidayed in Spain; card declined at a hotel.", [[]]),
    ("Called from a Swiss number about a blocked payment.", [[]]),
    ("Payment to a merchant in France was flagged.", [[]]),
    ("Customer reported a lost card while travelling in Thailand.", [[]]),
    ("Supplier in China asked for proof of payment.", [[]]),
    ("Customer is considering moving to Portugal next year.", [[]]),
    ("Will relocate to Germany in 2027.", [[]]),
    ("Customer's mother in Kenya is a joint account holder.", [[]]),
    ("Document issued in Italy was uploaded for review.", [[]]),
    ("Customer watched the match against Brazil and asked about the exchange rate.", [[]]),
    ("Customer disputes a charge from a Turkish airline.", [[]]),
    ("Customer asked whether the card works in Japan.", [[]]),
    ("Salary paid by a Nigerian employer into the account.", [[]]),
    # the person lives in IE, the employer is NG: NG alone is a wrong fact
    ("Customer works for a Nigerian company remotely from Ireland.", [["IE"], []]),
]
for text, acc in B:
    check("B residence_countries", text, list(residence_countries({"text": text, "channel": "support"})), acc)

# ---------------------------------------------------------------------------
# C. KYC / onboarding notes  (_name_from_note, _dob_from_note, approval)
#    SOP: an approved check "recorded only in a note" counts; rejected/expired
#    checks are not evidence. A misread name here produces a false
#    NAME_MISMATCH_VERIFIED clear.
# ---------------------------------------------------------------------------
def approved(text, created):
    note = {"note_id": "NOTE-000000", "created_at": created, "channel": "kyc", "text": text}
    return note_check(note, "CUS-000000").status == APPROVED


C = [
    # (text, note_date, acceptable names (lowercased, None allowed), acceptable dob iso, acceptable approved)
    ("Sumsub completed identity verification for NILS MARTIN, born December 13, 1977, using a national ID issued in Germany on 2023-02-19.",
     "2023-02-19", ["nils martin"], ["1977-12-13"], [True]),
    ("Veriff verified Ana Lopez (DOB 1980-05-01) on 2024-01-02.",
     "2024-01-02", ["ana lopez"], ["1980-05-01"], [True]),
    ("Sumsub check passed on 2024-06-01 for THOMAS HUGHES; DOB 15 December 2001.",
     "2024-06-01", ["thomas hughes"], ["2001-12-15"], [True]),
    ("Cleared KYC: passport (Nigeria) for CHINEDU BALOGUN, 2000-03-16, checked 2023-11-14.",
     "2023-11-14", ["chinedu balogun"], ["2000-03-16"], [True]),
    ("Onfido verified passport for JEAN-PIERRE DE LA CRUZ, born 2 February 1985, issued 2015, valid until 2025-02-01, on 2024-03-03.",
     "2024-03-03", ["jean-pierre de la cruz", "jean pierre de la cruz"], ["1985-02-02"], [True]),
    ("Persona: document authenticated for VAN DER BERG, PIETER, born 1979-11-08, on 2024-02-02.",
     "2024-02-02", ["van der berg, pieter", "van der berg pieter", "pieter van der berg"], ["1979-11-08"], [True]),
    ("Successfully onboarded with passport for Ana Lopez of Lopez Trading Ltd, DOB 1980-05-01, on 2024-01-02.",
     "2024-01-02", ["ana lopez", None], ["1980-05-01"], [True]),
    # must be treated as NOT approved
    ("Identity verification for MARCO ROMANO was not completed; document image blurry, re-upload requested.",
     "2024-01-02", ["marco romano", None], [None], [False]),
    ("Persona check for AMINA YUSUF (DOB 03/04/1990) returned a low-confidence match; manual review required.",
     "2024-01-02", ["amina yusuf", None], ["1990-04-03", None], [False]),
    ("Document for ANA LOPEZ expired on 2023-05-01; check declined.",
     "2024-01-02", ["ana lopez", None], [None], [False]),
    ("Verification pending for OMAR HUSSAIN (DOB 1987-06-20).",
     "2024-01-02", ["omar hussain", None], ["1987-06-20", None], [False]),
    ("ID check for ANA LOPEZ: name did not match the record; declined.",
     "2024-01-02", ["ana lopez", None], [None], [False]),
    ("KYC refresh for ANA LOPEZ scheduled for 2025-01-02.",
     "2024-12-01", ["ana lopez", None], [None], [False]),
    ("Awaiting resubmission of the driving licence for ANA LOPEZ.",
     "2024-12-01", ["ana lopez", None], [None], [False]),
    ("Veriff could not verify the selfie for ANA LOPEZ; case closed as unverified.",
     "2024-12-01", ["ana lopez", None], [None], [False]),
    # must yield no name / no DOB (ambiguous)
    ("Veriff verified the driving licence for ANA LOPEZ and her husband CARLOS LOPEZ on 2024-01-02.",
     "2024-01-02", [None], [None], [True]),
    ("Veriff verified ANA LOPEZ on 2024-01-02; DOB 05/11/98.",
     "2024-01-02", ["ana lopez"], [None], [True]),
    ("Sumsub verified ANA LOPEZ on 2024-01-02; previous check 2021-03-03; document issued 2019-06-06.",
     "2024-01-02", ["ana lopez"], [None], [True]),
]
for text, d, names_ok, dobs_ok, appr_ok in C:
    created = parse_date(d)
    name = _name_from_note(text)
    name_l = name.lower() if name else None
    check("C _name_from_note", text, name_l, names_ok)
    dob = _dob_from_note(text, created)
    check("C _dob_from_note", text, dob.iso() if dob else None, dobs_ok)
    check("C approved?", text, approved(text, d), appr_ok, wrong_if_not_in_acceptable=True)

# ---------------------------------------------------------------------------
# D. Names  (names_agree)  - SOP principle 8, literal
#    Too loose -> wrong confirm (cost 3). Too strict -> wrong NAME_MISMATCH_VERIFIED clear (cost 60).
#    So a False where True is expected is the dangerous direction here.
# ---------------------------------------------------------------------------
D = [
    # (customer, hit, company, acceptable)
    ("Mohamed Ali Hassan", "Muhammad Hasan", False, [True]),
    ("Li Wei", "Wei Li", False, [True]),
    ("Lee Wei", "Li Wei", False, [False]),                       # <4 letters must be identical
    ("Jon Smith", "John Smith", False, [True]),
    ("J. Smith", "John Smith", False, [True]),                   # initial dropped; shorter fully matched
    ("Ann Lee", "Anne Lee", False, [False]),
    ("Abdul Salam Yusuf", "Abdulsalam Yusuf", False, [True]),
    ("Mohamed El-Sayed", "Mohamed Elsayed", False, [True]),
    ("Mohammed Al Fayed", "Mohamed Alfayed", False, [True]),
    ("Maria de la Cruz", "Maria Cruz", False, [True]),
    ("Siti Nurhaliza binti Ahmad", "Siti Nurhaliza", False, [True]),
    ("Chen Wei", "Chen Wei Ming", False, [True]),
    ("David Bowman", "BOWMAN David", False, [True]),
    ("Michael Earl Tilley", "Michael Tilley", False, [True]),
    ("José María García", "Jose Maria Garcia", False, [True]),
    ("Katherine Jones", "Catherine Jones", False, [True]),       # 9 letters, 1 edit
    ("Robert Brown", "Roberto Browne", False, [True]),           # 1 edit each within budget
    ("Tom Okafor", "Thomas Okafor", False, [True]),
    ("Smith", "John Smith", False, [True]),                      # hit single-part alias may agree (decide blocks <2-part customers)
    ("Jonathan Reyes Whitfield", "John Whitfield", False, [False]),
    ("Ana Petrova", "Anna Petrosyan", False, [False]),
    ("Sarah Johnson", "Johnson, James Jacob", False, [False]),
    ("Markus Gerhard Mueller", "Mark Mueller", False, [False]),
    ("Pescanova SA", "Pescanova, Sociedad Anónima", True, [True]),
    ("Blue Harbour Trading Ltd", "Blue Harbor Trading Limited", True, [True]),
    ("ERJM LIMITED", "ERJM Ltd", True, [True]),
    ("Stadtwerke München GmbH", "Stadtwerke Muenchen", True, [True, False]),   # ü -> ue transliteration: SOP silent; report
    # office-hours questions (report only): SOP-literal answer is False, a human would say True
    ("MD AMIN", "Mohammad Amin", False, [False, True]),
    ("Ivan Petrov", "Иван Петров", False, [False, True]),
    ("Steve Jobs", "Stephen Jobs", False, [False, True]),
]
for a, b, comp, acc in D:
    check("D names_agree", f"{a!r} ~ {b!r}", names_agree(a, b, V, company=comp), acc)

# ---------------------------------------------------------------------------
# E. Dated reports in hit profile notes  (exact shape "According to …; Month D, YYYY: …")
# ---------------------------------------------------------------------------
E = [
    ("According to the Daily Nation; September 10, 2025: the subject was charged with fraud.", ["2025-09-10"]),
    ("According to Reuters; 10 September 2025: arrested at the airport.", ["2025-09-10"]),
    ("According to court records; March 2019: sentenced to six years.", ["2019-03", None]),
    ("According to Reuters; 2025: named in an investigation.", ["2025", None]),
    ("According to Reuters (September 10, 2025): arrested.", [None]),
    ("Reported by Reuters on September 10, 2025: arrested.", [None]),
    ("Career: Member of Parliament (July 22, 2019 - 2027).", [None]),
    ("According to the BBC; January 5, 2021: charged.\nAccording to AFP; July 4, 2019: first named.", ["2019-07-04"]),
]
if REPORT_DATES_FN:
    for text, acc in E:
        got = REPORT_DATES_FN(text)
        got = getattr(got, "iso", lambda: got)() if got is not None and not isinstance(got, (list, str)) else got
        check("E report dates", text, got, acc)
else:
    report["SKIP"] += len(E)

# ---------------------------------------------------------------------------
# F. Search results  (result_is_about_hit)  - PEP hit, countries ["ES"], name Elvira Velasco Morillo
#    SOP: a result is about the hit only if it describes the SAME KIND of listing
#    (exact phrase per category) in a country TIED TO THE HIT. Namesakes abound.
# ---------------------------------------------------------------------------
F_HIT = {"name": "Elvira Velasco Morillo", "primary_category": "PEP", "countries": ["ES"], "nationality": [], "citizenship": [], "addresses": [], "place_of_birth": None}
F = [
    ({"query": "elvira morillo velasco", "title": "Profile", "snippet": "Elvira Velasco Morillo, a politically exposed person in Spain, born 5 March 1968.", "source": "news.example"}, [True]),
    ({"query": "elvira morillo velasco", "title": "Profile", "snippet": "Elvira Velasco Morillo, a politically exposed person in Argentina, born 1975.", "source": "news.example"}, [False]),
    ({"query": "elvira morillo velasco", "title": "Profile", "snippet": "Elvira Velasco, named in adverse media in Spain, born 1970.", "source": "news.example"}, [False]),
    ({"query": "elvira morillo velasco", "title": "Profile", "snippet": "Elvira Velasco Morillo, politically exposed, Spain, born 1968.", "source": "news.example"}, [False]),
    ({"query": "elvira morillo velasco", "title": "Profile", "snippet": "Luis Velasco Morillo, a politically exposed person in Spain, born 1950.", "source": "news.example"}, [False]),
    ({"query": "elvira morillo velasco spain", "title": "Profile", "snippet": "A politically exposed person, born 1968.", "source": "spain-news.example"}, [False]),  # country only in query/source
]
if RESULT_ABOUT_FN:
    for row, acc in F:
        check("F result_is_about_hit", row["snippet"], bool(RESULT_ABOUT_FN(row, F_HIT)), acc)
else:
    report["SKIP"] += len(F)

# ---------------------------------------------------------------------------
# G. Date reader  (parse_date)
# ---------------------------------------------------------------------------
G = [
    ("19/05/2004", ["2004-05-19"]), ("2026-11-06", ["2026-11-06"]), ("February 19, 2002", ["2002-02-19"]),
    ("1996", ["1996"]), ("1962-09", ["1962-09"]), ("31/02/2001", [None]), ("05.11.98", [None]),
    ("1998/11/05", ["1998-11-05", "1998", None]), ("Sept. 10, 2025", ["2025-09-10"]), ("5th November 1998", ["1998-11-05"]),
    ("N/A", [None]), ("0000-00-00", [None]), ("1899-12-31", [None, "1899-12-31"]), ("2030-01-01", ["2030-01-01", None]),
]
for text, acc in G:
    d = parse_date(text)
    check("G parse_date", text, d.iso() if d else None, acc)

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
print(f"\nPASS {report['PASS']}   WRONG FACT {len(report['WRONG FACT'])}   MISSED {len(report['MISSED'])}   SKIPPED {report['SKIP']}\n")
for sev in ("WRONG FACT", "MISSED"):
    if report[sev]:
        print(f"=== {sev} ===")
        for group, text, got, acc in report[sev]:
            print(f"[{group}] {text}\n    got {got!r}  acceptable {acc!r}")
        print()
if report["SKIP"]:
    print("Set REPORT_DATES_FN and RESULT_ABOUT_FN at the top of this file to run sections E and F.")
