"""Hardening tests: readers against rewordings, and rules the practice labels never exercised.

Every reader has two lists: sentences it must read, and look-alikes it must
leave unknown. A wrong fact can clear a hit (cost 60); an unknown costs a
review (2-3). So the second list matters more than the first.

Run:  python -m unittest discover -s system/tests   (from the repository root)
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import dates  # noqa: E402
from customer_facts import (APPROVED, REJECTED, UNCLEAR, _dob_from_note, _name_from_note, is_identity_note,  # noqa: E402
                            note_check, read_support_note, row_status)
from dates import PartialDate, detect_numeric_order, find_dates, parse_date, parse_exact, parse_iso  # noqa: E402
from decide import decide  # noqa: E402
from explain import explain, explain_ambiguous, explain_no_customer  # noqa: E402
from hit_facts import (hit_entity_type, is_birth_sentence_paragraph, read_birth_facts, report_dates,  # noqa: E402
                       result_is_about_hit)
from names import Variants, names_agree, names_certainly_disagree  # noqa: E402
from schema import CustomerFacts, FactCard, HitFacts  # noqa: E402

VARIANTS_PATH = os.path.join(HERE, "..", "..", "dev", "name_variants.json")
V = Variants(json.load(open(VARIANTS_PATH, encoding="utf-8"))) if os.path.exists(VARIANTS_PATH) else Variants(
    {"groups": [["muhammad", "mohammed", "mohammad", "mohamed"], ["hassan", "hasan"],
                ["yusuf", "yousef", "joseph", "joe"], ["joseph", "joe", "jose"]],
     "company_legal_forms": ["ltd", "limited", "sa", "inc", "llc", "ag", "gmbh"]})


def years(text):
    got, unread = read_birth_facts(text)
    return [d.iso() for d in got], unread


# ---------------------------------------------------------------------------
# Phase 2: readers
# ---------------------------------------------------------------------------

class TestBirthAndAgeReader(unittest.TestCase):
    MUST_READ = {
        "Formal charges were brought against Elvira Velasco Morillo, aged 30, in November 1998.": ["1967", "1968"],
        "At the time Fabrizio Rossi faced charges in March 1999, he was 24.": ["1974", "1975"],
        "Yahaya Abubakar Abdullahi was born in 1952.": ["1952"],
        "Emmanuel Asamoa Owusu-Ansah was born on 17 July 1939.": ["1939-07-17"],
        "In January 2025, investigators questioned 38-year-old Tomasz Paweł Drozd.": ["1986", "1987"],
        "Pere Punti reached 37 years of age by November 1981, the time he was charged.": ["1943", "1944"],
        "Questioned in April 2006, Alexander Ostrowsky was 42 years old.": ["1963", "1964"],
        "Adam Tomasz Drozd, at age 31, had charges filed against him in December 2005.": ["1973", "1974"],
        "A 1996 media profile from October described Oleksii Hryhoriev, 21, as a sanctioned individual in Russia.": ["1974", "1975"],
        "She turned 50 in May 2010.": ["1959", "1960"],
        "Born 4 July 1962 in Cairo, he was later listed.": ["1962-07-04"],
        "The 45-year-old was arrested in May 2019.": ["1973", "1974"],
        "He was 46 when questioned in January 2023.": ["1976", "1977"],
        "John Smith was aged 45 when sentenced in March 2019.": ["1973", "1974"],
        "The age of Tomasz Paweł Drozd was 38 when he was questioned in January 2025.": ["1986", "1987"],
        "A regulator's notice from May 2002 listed Aleksandar Raković, 29, a politically exposed person in Serbia.": ["1972", "1973"],
        "Javier Garcia, a 40 named on a watchlist in Nigeria, appeared in a regulator's notice in March 1988.": ["1947", "1948"],
        "In February 2010, at the age of 33, Jérôme Kerviel was named in adverse media in France.": ["1976", "1977"],
        "May 2019 news reports profiled 33 year old MARCOS ROBERTO COSTA, who is a politically exposed person in Brazil.": ["1985", "1986"],
        "During December 2012, Jean-Philippe Laurent faced charges while at the age of 43.": ["1968", "1969"],
        "Thomas P Walsh was 25 when taken into custody during February 1986.": ["1960", "1961"],
        "Regarding the June 2006 investigation, Tomasz Drozd was 27 at the time he was questioned.": ["1978", "1979"],
        "Mark E Phillips, at 24, was taken into custody in May 1999.": ["1974", "1975"],
        "An indictment naming Frank Murud was issued in October 2004, when the subject was 48.": ["1955", "1956"],
        "In June 2006, when questioning by investigators took place, Tomasz Drozd was 27.": ["1978", "1979"],
        "John Smith was 32 at the time of his arrest in 2004.": ["1971", "1972"],
        "now 61 (2024)": ["1962", "1963"],
        "Sentenced in March 2019 at the age of 45 to six years' imprisonment.": ["1973", "1974"],
        "Appointed CEO at age 45 in 2010; resigned in 2020.": ["1964", "1965"],
        "Her son, born 1995, was also charged; she was 48 at the time (2019).": ["1970", "1971"],
        "DOB 1998/11/05": ["1998-11-05"],
    }
    # (sentence, whether the reader must also report that it states a birth/age it could not use)
    MUST_STAY_UNKNOWN = [
        ("He was in his forties when arrested in March 2019.", True),
        ("Aged forty-five in March 2019.", True),
        ("Born c. 1960 in Cairo.", True),
        ("He was born circa 1960.", True),
        ("He was born between 1970 and 1972.", True),
        ("He was born in the 1960s.", True),
        ("Aged between 40 and 45 in 2019.", True),
        ("John Smith, 45, and his son, 12, were arrested in May 2019.", True),
        ("In 2019, the 45-year-old was sentenced for a 2015 fraud.", True),
        ("He celebrated his 60th birthday in 2019.", True),
        ("At 52, in June 2011, he was indicted.", True),
        ("The fine was 50 in 2019.", True),                 # not a person: flagged, never read as an age
        ("The penalty was 25 when issued in March 2019.", True),
        ("Bail was 50 when set in March 2019.", True),      # a sentence-opening capital is not a name
        ("Thomas Walsh was 50,000 short when audited in March 2019.", False),
        ("PKR 11,000,000 was recovered in October 2025.", False),
        ("Case No. 45/2019 was filed in May 2019.", False),
        ("He completed 45 years of service in 2019.", False),
        ("He received a 30-year sentence in 2019.", False),
        ("The firm, 45, Main Street, was fined in May 2019.", False),
        ("Call +44 7700 900123 for details in 2019.", False),
        ("He faced 45 counts of fraud in 2019.", False),
        ("Under Section 45 of the 2010 Act he was fined in 2019.", False),
        ("45 people were arrested in 2019.", False),
        ("A 45% stake was sold in 2019.", False),
        ("The route was 46 kilometres from the border in 2019.", False),
        ("Sterling Bank paid a NGN 52.97 000 000 fine in 2013.", False),
        ("He was born in Cairo and later moved to London.", False),
        ("He was born in Cairo. In 1990 the family moved to London.", False),   # the year is not a birth year
    ]

    def test_must_read(self):
        for text, expected in self.MUST_READ.items():
            got, unread = years(text)
            self.assertEqual(got, expected, text)
            self.assertFalse(unread, text)

    def test_must_stay_unknown(self):
        for text, flagged in self.MUST_STAY_UNKNOWN:
            got, unread = years(text)
            self.assertEqual(got, [], text)
            if flagged:
                self.assertTrue(unread, f"should be reported as unread: {text}")

    def test_only_a_sentence_about_the_person_is_read(self):
        self.assertTrue(is_birth_sentence_paragraph("Yahaya Abubakar Abdullahi was born in 1952."))
        record = "Name: James, Richard\nAlias: Robert James\nDIN: 08A4967\nSex: M\nDOB: 6/20/1955\nHeight: 5' 10\""
        self.assertFalse(is_birth_sentence_paragraph(record))          # a provider's record dump
        self.assertFalse(is_birth_sentence_paragraph("DOB: 6/20/1955"))
        self.assertFalse(is_birth_sentence_paragraph(
            "According to thenation.com.pk; October 20, 2013: In October 2013, Omar Hussain, 34, was arrested."))


class TestDates(unittest.TestCase):
    def test_numeric_order_is_taken_from_the_data(self):
        self.assertEqual(detect_numeric_order(["19/05/2004", "02/03/2001"]), "dmy")
        self.assertEqual(detect_numeric_order(["05/19/2004", "02/03/2001"]), "mdy")
        self.assertEqual(detect_numeric_order(["19/05/2004", "05/19/2004"]), "mixed")
        self.assertEqual(detect_numeric_order(["02/03/2001", "1996", None]), "dmy")    # no evidence: the bank's convention

    def test_mixed_sources_keep_only_what_is_certain(self):
        try:
            dates.set_numeric_order("mixed", "default")
            self.assertEqual(parse_iso("19/05/2004"), "2004-05-19")
            self.assertEqual(parse_iso("05/19/2004"), "2004-05-19")
            self.assertEqual(parse_iso("02/03/2001"), "2001")          # day and month unknown
            dates.set_numeric_order("mdy", "default")
            self.assertEqual(parse_iso("02/03/2001"), "2001-02-03")
        finally:
            dates.set_numeric_order("dmy", "default")
        self.assertEqual(parse_iso("02/03/2001"), "2001-03-02")

    def test_watchlist_text_never_inherits_the_bank_convention(self):
        self.assertEqual([m.date.iso() for m in find_dates("DOB: 6/20/1955", source="hit")], ["1955-06-20"])
        self.assertEqual([m.date.iso() for m in find_dates("DOB: 02/03/1955", source="hit")], ["1955"])

    def test_unreadable_shapes(self):
        for raw in ["05.11.98", "the 1960s", "N/A", "unknown", "31/02/2001", "0000-00-00"]:
            self.assertIsNone(parse_iso(raw), raw)
        self.assertEqual(parse_iso("1998/11/05"), "1998-11-05")     # year first is year-month-day whatever the separator
        self.assertEqual(parse_iso("1998.11.05"), "1998-11-05")
        self.assertEqual([m.text for m in find_dates("paid USD 2000 on Flight 1995 since 1998", bare_years="context")], ["1998"])


class TestReportLines(unittest.TestCase):
    def dates_of(self, text):
        return [d.iso() for d in report_dates({"profile_notes": text})]

    def test_only_the_sop_shape_counts(self):
        for line in ["According to premiumtimesng.com; September 10, 2025: text",
                     "According to the U.S. Federal Trade Commission; 10 September 2025: text",
                     "According to https://example.com/a; Sept. 10, 2025: text",
                     "According to X; 2025-09-10: text"]:
            self.assertEqual(self.dates_of(line), ["2025-09-10"], line)
        for line in ["According to X (September 10, 2025): text",
                     "Reported on September 10, 2025 by X: text",
                     "According to X; 2025: text",
                     "According to X; September 2025: text",
                     "According to X; as of May 15, 2019: text",
                     "According to the Federal Bureau of Prisons, information as of December 13, 2017:",
                     "In line with X; September 10, 2025: text"]:
            self.assertEqual(self.dates_of(line), [], line)


class TestSearchResultQualification(unittest.TestCase):
    def about(self, category, snippet, codes=("RU",), **extra):
        hit = {"name": "Petrov, Ivan", "primary_category": category, "categories": [category]}
        return result_is_about_hit({"title": "Ivan Petrov - report", "snippet": snippet, **extra}, hit, list(codes))

    def test_listing_phrase_and_country_must_both_be_in_the_result(self):
        self.assertTrue(self.about("PEP", "Ivan Petrov, 40, a politically exposed person in Russia, was listed in March 2019."))
        self.assertFalse(self.about("PEP", "Ivan Petrov, 40, politically exposed in Russia, was listed in March 2019."))
        self.assertTrue(self.about("Sanctions", "Ivan Petrov, 40, a sanctioned individual in Russia."))
        self.assertFalse(self.about("Sanctions", "Ivan Petrov, 40, is subject to sanctions in Russia."))
        self.assertFalse(self.about("Enforcement", "Ivan Petrov, 40, a law enforcement officer in Russia."))
        self.assertFalse(self.about("Adverse Media", "This site aggregates adverse media. Ivan Petrov, 40, lives in Russia."))
        self.assertTrue(self.about("Adverse Media", "Ivan Petrov, 40, was named in adverse media in Russia."))
        self.assertTrue(self.about("Registration", "Ivan Petrov, 40, named on a watchlist in Russia."))

    def test_a_relative_with_the_same_surname_is_not_the_hit(self):
        hit = {"name": "Elvira Velasco Morillo", "primary_category": "PEP", "categories": ["PEP"]}
        mine = {"title": "Profile", "snippet": "Elvira Velasco Morillo, a politically exposed person in Spain, born 5 March 1968."}
        theirs = {"title": "Profile", "snippet": "Luis Velasco Morillo, a politically exposed person in Spain, born 1950."}
        self.assertTrue(result_is_about_hit(mine, hit, ["ES"]))
        self.assertFalse(result_is_about_hit(theirs, hit, ["ES"]))
        reordered = {"title": "MORILLO, Elvira Velasco", "snippet": "Listed as a politically exposed person in Spain."}
        self.assertTrue(result_is_about_hit(reordered, hit, ["ES"]))

    def test_country_in_query_or_source_does_not_count(self):
        self.assertFalse(self.about("PEP", "Ivan Petrov, 40, a politically exposed person, was listed in March 2019.",
                                    query="ivan petrov russia", source="russia-news.example"))
        self.assertFalse(self.about("PEP", "Ivan Petrov, 40, a politically exposed person in Serbia."))
        self.assertFalse(self.about("PEP", "Ivan Petrov, 40, a politically exposed person in Russia.", codes=()))


def reading(text):
    r = read_support_note({"text": text})
    return r.confident, r.possible, r.unresolved


class TestResidenceNotes(unittest.TestCase):
    MUST_ADD = {
        "Customer relocated to Kenya in 2015.": ["KE"],
        "Has been resident in Portugal since 2019.": ["PT"],
        "Address on file is in Lagos, Nigeria.": ["NG"],
        "Customer confirmed they are based in Dubai.": ["AE"],
        "Spent 2010 to 2014 in Canada for work.": ["CA"],
        "Grew up in Serbia.": ["RS"],
        "Originally from Bangladesh.": ["BD"],
        "Holds a residence permit for Italy.": ["IT"],
        "Registered address: Berlin, Germany.": ["DE"],
        "The client's home is in Madrid.": ["ES"],
        "Lived in Texas until 2010.": ["US"],
        "Previously lived in Norway.": ["NO"],
        "Austria served as the base for the client's work and home life for the duration of 2012 and 2014.": ["AT"],
        "The client confirmed their employment and residency in Denmark from 2016 to 2018.": ["DK"],
        "Confirmed address in Portugal.": ["PT"],
        "Originally from Bangladesh, moved to the UK in 2008.": ["BD", "GB"],     # UK and US in capitals are countries
        "Lived in the US from 2001 to 2009.": ["US"],
        # a past tense is never a plan, and an enquiry is not a hypothetical
        "In relation to the transfer inquiry, the individual noted they lived and worked in Spain from 2008 to 2011.": ["ES"],
        "From May 2011 the client lived in Kenya.": ["KE"],
        # wording outside any cue list still counts when the note is not about something else
        "The customer provided information confirming they were established professionally and personally in Serbia from 2014 through 2018.": ["RS"],
        "From 2011 through 2016, the client was an inhabitant and employee in Kenya.": ["KE"],
        "Client was situated and active in the workforce in Romania from 2018 to 2020.": ["RO"],
        "The client's time in Norway spanned 2011 to 2015.": ["NO"],
    }
    MUST_NOT_ADD = [
        "Sent money to family in Nigeria.",
        "Holidayed in Spain.",
        "Called from a Swiss number.",
        "Payment to a merchant in France.",
        "Opened a Swiss bank account.",
        "Flight to Turkey booked.",
        "Transfer to the United Kingdom declined.",
        "Customer asked about fees for Nigeria transfers.",
        "Supplier in China paid.",
        "Watched the match against Brazil.",
        "Will relocate to Canada next year.",
        "Considered moving to Spain.",
        "Customer asked how long an international transfer to Germany takes.",
        "Customer asked whether the card works in Japan.",                 # the card works, not the customer
        "Salary paid by a Nigerian employer into the account.",            # the employer is Nigerian, not the home
        "Customer works for a Nigerian company remotely from Ireland.",
        "Please contact us about the transfer to Kenya.",                  # "us" is not the US
    ]

    def test_must_add(self):
        for text, expected in self.MUST_ADD.items():
            confident, _, _ = reading(text)
            self.assertEqual(sorted(confident), sorted(expected), text)

    def test_returned_and_left(self):
        confident, _, _ = reading("Returned to Ghana after ten years in London.")
        self.assertEqual(sorted(confident), ["GB", "GH"])

    def test_must_not_add_but_still_remembered(self):
        for text in self.MUST_NOT_ADD:
            confident, possible, _ = reading(text)
            self.assertEqual(confident, [], text)
            self.assertTrue(possible, f"a mentioned country must stay a possibility: {text}")

    def test_unresolved_place_is_reported(self):
        confident, possible, unresolved = reading("Lived in Springfield for years.")
        self.assertEqual((confident, possible, unresolved), ([], [], True))
        self.assertFalse(reading("Customer reported a lost card. Card frozen and a replacement ordered to the address on file.")[2])


class TestIdentityNotes(unittest.TestCase):
    def status(self, text):
        return note_check({"note_id": "NOTE-000001", "created_at": "2024-01-02", "channel": "kyc", "text": text}, "CUS-000001").status

    NOT_APPROVED = [
        "Verification was not completed for ANA LOPEZ (DOB 1980-05-01).",
        "ANA LOPEZ (DOB 1980-05-01) could not be matched against the passport from Spain.",
        "Document under review for ANA LOPEZ, DOB 1980-05-01.",
        "Awaiting resubmission from ANA LOPEZ, DOB 1980-05-01.",
        "The check for ANA LOPEZ, DOB 1980-05-01, is to be re-run.",
        "ANA LOPEZ partially verified, DOB 1980-05-01.",
        "The name did not match the record for ANA LOPEZ, DOB 1980-05-01.",
        "The check returned a low-confidence result for ANA LOPEZ, DOB 1980-05-01.",
        "Manual review required for ANA LOPEZ, DOB 1980-05-01.",
        "The document expired before ANA LOPEZ, DOB 1980-05-01, completed the flow.",
        "The applicant ANA LOPEZ, DOB 1980-05-01, abandoned the flow.",
        "Blurry image, re-upload requested from ANA LOPEZ, DOB 1980-05-01.",
        "Identity check for ANA LOPEZ failed on 2024-01-02: document expired.",
        "Sumsub rejected the passport of ANA LOPEZ, DOB 1980-05-01.",
        "Verification pending for ANA LOPEZ, DOB 1980-05-01.",
    ]
    APPROVED_NOTES = [
        "ANA LOPEZ cleared KYC, DOB 1980-05-01, passport from Spain.",
        "ANA LOPEZ passed identity verification with a passport from Spain.",
        "ID confirmed for ANA LOPEZ, DOB 1980-05-01.",
        "ANA LOPEZ successfully onboarded with a passport from Spain.",
        "Verification complete for ANA LOPEZ (DOB 1980-05-01).",
        "Document authenticated for ANA LOPEZ.",
        "GEORGE KING, born 14 January 1993, underwent Sumsub verification on 2023-03-14 using a national ID from the United Kingdom.",
        "Identity verification via Persona for THUAN THI LE (DOB May 19, 1978) concluded on 2023-05-27 using a Vietnam national ID.",
    ]

    def test_soft_rejections_are_not_approvals(self):
        for text in self.NOT_APPROVED:
            self.assertNotEqual(self.status(text), APPROVED, text)

    def test_approvals_in_other_words(self):
        for text in self.APPROVED_NOTES:
            self.assertEqual(self.status(text), APPROVED, text)

    def test_row_results(self):
        self.assertEqual(row_status("approved"), APPROVED)
        self.assertEqual(row_status("rejected"), REJECTED)
        self.assertEqual(row_status("expired"), REJECTED)
        self.assertEqual(row_status("pending"), UNCLEAR)
        self.assertEqual(row_status(None), UNCLEAR)

    def test_names(self):
        self.assertEqual(_name_from_note("Veriff verified Ana Lopez (DOB 1980-05-01) on 2024-01-02."), "Ana Lopez")
        self.assertEqual(_name_from_note("Veriff verified Ana van der Berg (DOB 1980-05-01)."), "Ana van der Berg")
        self.assertEqual(_name_from_note("PASSPORT VERIFIED FOR ANA LOPEZ, UNITED KINGDOM."), "ANA LOPEZ")
        self.assertEqual(_name_from_note("Onfido verified JORDAN SMITH (DOB 1980-05-01)."), "JORDAN SMITH")   # Jordan is a name too
        self.assertIsNone(_name_from_note("Persona: ANA LOPEZ and JUAN GARCIA verified 2024-01-02."))
        self.assertIsNone(_name_from_note("Verified for Ana Lopez of Lopez Trading Ltd."))                     # two candidates
        self.assertIsNone(_name_from_note("Result: ok"))

    def test_surname_first_keeps_the_given_name(self):
        # Dropping "PIETER" would leave a surname-only name that falsely mismatches "Pieter Berg".
        self.assertEqual(_name_from_note("Persona: document authenticated for VAN DER BERG, PIETER, born 1979-11-08, on 2024-02-02."),
                         "VAN DER BERG PIETER")
        self.assertEqual(_name_from_note("Verified LOPEZ, ANA MARIA (DOB 1980-05-01)."), "LOPEZ ANA MARIA")
        self.assertEqual(_name_from_note("On 2024-03-16, Persona validated the national ID of TEMITOPE NWOSU, DOB 22/09/1956, from Nigeria."),
                         "TEMITOPE NWOSU")
        self.assertEqual(_name_from_note("Verified ANA LOPEZ, NIGERIA, on 2024-01-02."), "ANA LOPEZ")     # a country is not a given name
        self.assertIsNone(_name_from_note("Verified ANA LOPEZ, CARLOS GARCIA on 2024-01-02."))            # two people

    def test_dob_versus_document_and_check_dates(self):
        created = parse_date("2024-01-02")
        cases = {
            "On 2024-06-19, Onfido verified a United Kingdom passport for GRACE TURNER, who was born on 27/06/1969.": "1969-06-27",
            "Result for MARTINEZ CHRISTIAN, DOB 04/10/1995: Persona verified passport from Mexico on 2023-01-10.": "1995-10-04",
            "MARTIN LEE has been cleared through Veriff on 2024-03-04; the verification relied on a Singapore national ID, DOB 10/06/1981.": "1981-06-10",
            "The national ID belonging to JAVIER BIANCHI (19/12/2003) from Germany was verified via Veriff on 2024-12-17.": "2003-12-19",
            "ID verification (Persona, 2024-01-02) approved. Document: passport (France). Name on document: ANA LOPEZ. Date of birth on document: 1 May 1980.": "1980-05-01",
            "Passport issued 2019-03-01, valid until 2029-03-01; ANA LOPEZ born 1 May 1980.": "1980-05-01",
            "JAHID ISLAM had his national ID verified through Persona on 2024-10-06. The record shows the holder was born in Bangladesh on 13/07/1983.": "1983-07-13",
            "Verification of ANA LOPEZ was finalized via Onfido on 2024-11-09 and confirms a date of birth of 1974.": "1974",
            "Identity check for JAN HANSEN successfully processed. Data points confirmed: 03/05/1976 DOB via national ID from Germany using Onfido on 2025-07-19.": "1976-05-03",
            "Sumsub confirmed MIKAEL DUBOIS's identity on 2024-04-16. His date of birth is set at 13/10/1967.": "1967-10-13",
            "Sumsub verified the United Kingdom passport for ANA LOPEZ, DOB 1999, on 2025-10-17.": "1999",   # a year alone, right after "DOB"
        }
        for text, expected in cases.items():
            d = _dob_from_note(text, created)
            self.assertEqual(d.iso() if d else None, expected, text)
        for text in ["Onfido verified ANA LOPEZ, 1980-05-01, passport Spain, 2023-12-31.",     # two unanchored dates
                     "ANA LOPEZ verified, DOB 05/11/98.",                                       # two-digit year
                     "ANA LOPEZ verified on 2024-01-02, passport valid until 2030-05-01.",      # no birth date at all
                     "ANA LOPEZ verified, DOB 2020-05-01.",                                     # a small child: implausible
                     "Sumsub verified ANA LOPEZ on 2024-01-02; previous check 2010-03-03; document issued 2019-06-06.",
                     "RASEL KHAN was verified on 2024-06-04 with a national ID dated 1952-01-21.",    # could be an issue date
                     "ANA LOPEZ verified on 2024-01-02; she gave birth on 2010-05-01.",               # her child's birth, not hers
                     "DOB in system updated on 2010-01-02 for ANA LOPEZ.",                             # not a birth date
                     "KYC refresh for ANA LOPEZ scheduled for 2025-01-02."]:
            self.assertIsNone(_dob_from_note(text, created), text)

    def test_which_notes_are_identity_checks(self):
        self.assertTrue(is_identity_note({"channel": "kyc", "text": "anything"}))
        self.assertTrue(is_identity_note({"channel": "phone", "text": "Onfido verified the passport of ANA LOPEZ."}))
        self.assertFalse(is_identity_note({"channel": "email", "text": "Customer updated their mobile number after changing provider. Verified through the app."}))
        self.assertFalse(is_identity_note({"channel": "phone", "text": "The client lived in France from 2010 to 2019."}))


class TestNames(unittest.TestCase):
    def test_a_part_listed_in_two_groups_matches_both(self):
        self.assertTrue(names_agree("Yusuf Ali", "Joseph Ali", V))
        self.assertTrue(names_agree("Joe Garcia", "Jose Garcia", V))
        self.assertFalse(names_agree("Yusuf Garcia", "Jose Garcia", V))      # never listed together

    def test_agreement_does_not_depend_on_the_order_of_the_names(self):
        # 'st'+'logistics' written together once matched 'logistics' with two free edits, but only in one order,
        # so a verified-name clear depended on which name was passed first (dev hit H-124BB8).
        pairs = [("Starling Logistics Ltd", "ST Logistics (UK) Ltd.", True, False),
                 ("Abdel Rahman Musa", "Abdulrahman Musa", False, True),
                 ("Abdul Salam Yusuf", "Abdulsalam Yusuf", False, True),
                 ("Mohamed Ali Hassan", "Muhammad Hasan", False, True),
                 ("Jonathan Reyes Whitfield", "John Whitfield", False, False)]
        for a, b, company, expected in pairs:
            self.assertEqual(names_agree(a, b, V, company=company), expected, f"{a} ~ {b}")
            self.assertEqual(names_agree(b, a, V, company=company), expected, f"{b} ~ {a}")

    def test_a_clearing_mismatch_must_hold_under_every_reading(self):
        self.assertTrue(names_certainly_disagree("Jonathan Reyes Whitfield", "John Whitfield", V))
        self.assertTrue(names_certainly_disagree("MARKUS GERHARD MUELLER", "Mark Mueller", V))
        self.assertTrue(names_certainly_disagree("SARAH JOHNSON", "Johnson, James Jacob", V))
        self.assertFalse(names_certainly_disagree("Sean O'Brien", "Sean Brien", V))
        self.assertFalse(names_certainly_disagree("Ana Lopez", "Александар Раковић", V))     # nothing to compare
        self.assertFalse(names_certainly_disagree("Bluegrass Craft Coffee Roasters LLC", "Blue Grass Holdings Limited", V, company=True))


# ---------------------------------------------------------------------------
# Phase 3: rules the labels never exercised
# ---------------------------------------------------------------------------

def card(cust=None, hit=None, screened_at="2024-03-15"):
    c = dict(customer_id="CUS-000001", entity_type="person", legal_name="Mohamed Ali Hassan", name_verified=True,
             other_names=[], dob="1985-03-12", countries=["GB", "EG"], source_ids=["CUS-000001"],
             record_ids=["CUS-000001"], name_source_id="KYC-000001", dob_source_id="KYC-000001",
             country_sources={"GB": ["CUS-000001"], "EG": ["KYC-000001"]}, real_name_parts=3)
    c.update(cust or {})
    h = dict(hit_id="H-000001", entity_type="person", names=["Mohamed Hassan"], dobs=[], countries=[],
             earliest_report_date=None, date_of_death=None, source_ids=[])
    h.update(hit or {})
    return FactCard(alert_id="A-000001", hit_id="H-000001", screened_at=screened_at,
                    customer=CustomerFacts(**c), hit=HitFacts(**h))


def outcome(c):
    d, a = decide(c, V)
    return d.decision, d.reason_code


def full(c):
    d, a = decide(c, V)
    return explain(c, d, a)


class TestDeceased(unittest.TestCase):
    def test_full_date_before_screening_clears(self):
        self.assertEqual(outcome(card(hit=dict(date_of_death="2015-02-01"))), ("DIFFERENT_ENTITY", "DECEASED"))

    def test_year_only_death_in_the_screening_year_does_not_clear(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(date_of_death="2024"))), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_year_only_death_in_an_earlier_year_clears(self):
        self.assertEqual(outcome(card(hit=dict(date_of_death="2023"))), ("DIFFERENT_ENTITY", "DECEASED"))

    def test_death_after_screening_does_not_clear(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(date_of_death="2025-01-01"))), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_no_date_of_death_does_not_clear(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(date_of_death=None))), ("REVIEW", "INSUFFICIENT_DATA"))


class TestEntityType(unittest.TestCase):
    def test_both_directions(self):
        self.assertEqual(outcome(card(hit=dict(entity_type="company", names=["Hassan Trading Ltd"]))),
                         ("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH"))
        self.assertEqual(outcome(card(dict(entity_type="company", legal_name="Hassan Trading Ltd"), dict(entity_type="person"))),
                         ("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH"))

    def test_unknown_type_never_clears(self):
        self.assertIsNone(hit_entity_type({"entity_type": None}))
        self.assertIsNone(hit_entity_type({"entity_type": "Vessel"}))
        c = card(dict(entity_type="company", legal_name="Hassan Trading Ltd", countries=[]),
                 dict(entity_type=None, names=["Hassan Trading"]))
        self.assertEqual(outcome(c)[0], "REVIEW")


class TestTemporal(unittest.TestCase):
    def test_exactly_fifteen_clears_exactly_sixteen_does_not(self):
        fifteen = card(dict(dob="2001", countries=[]), dict(earliest_report_date="2016-12-31"))
        self.assertEqual(outcome(fifteen), ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))     # oldest possible: 15
        sixteen = card(dict(dob="2001", countries=[]), dict(earliest_report_date="2017-01-01"))
        self.assertEqual(outcome(sixteen), ("REVIEW", "INSUFFICIENT_DATA"))                    # could have been 16

    def test_company_incorporation(self):
        co = dict(entity_type="company", legal_name="Hassan Trading Ltd", countries=[])
        hit = dict(entity_type="company", names=["Hassan Trading Limited"])
        self.assertEqual(outcome(card({**co, "dob": "2020-03-01"}, {**hit, "earliest_report_date": "2020-02-15"})),
                         ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))
        self.assertEqual(outcome(card({**co, "dob": "2020-02"}, {**hit, "earliest_report_date": "2020-02-15"}))[0], "REVIEW")
        self.assertEqual(outcome(card({**co, "dob": "2021"}, {**hit, "earliest_report_date": "2020"})),
                         ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))
        self.assertEqual(outcome(card({**co, "dob": "2020"}, {**hit, "earliest_report_date": "2020"}))[0], "REVIEW")

    def test_uncertain_customer_date_never_clears_on_time(self):
        c = card(dict(dob="2007", countries=[], dob_certain=False, identity_gaps=["the date on the latest check could not be read"]),
                 dict(earliest_report_date="2010-05-01"))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))


class TestDob(unittest.TestCase):
    def test_one_year_apart_is_never_a_mismatch_and_never_a_match(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1986"]))), ("REVIEW", "INSUFFICIENT_DATA"))
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1984-03-12"]))), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_partial_dates(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1985"]))), ("SAME_ENTITY", "NAME_DOB_MATCH"))
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1985-07"]))), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1984", "1985"]))), ("SAME_ENTITY", "NAME_DOB_MATCH"))
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1962", "1985-03"]))), ("SAME_ENTITY", "NAME_DOB_MATCH"))

    def test_unknown_on_either_side_never_contradicts(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=[]))), ("REVIEW", "INSUFFICIENT_DATA"))
        self.assertEqual(outcome(card(dict(dob=None, countries=[]), dict(dobs=["1962"]))), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_an_incomplete_hit_picture_never_clears_on_dob(self):
        c = card(dict(countries=[]), dict(dobs=["1962"], dobs_complete=False, dob_gaps=["one listed date could not be read"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_an_uncertain_customer_dob_never_clears(self):
        c = card(dict(countries=[], dob_certain=False, identity_gaps=["the latest check could not be read"]), dict(dobs=["1962"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))


class TestLocation(unittest.TestCase):
    def test_name_and_dob_agree_countries_differ_is_review(self):
        self.assertEqual(outcome(card(hit=dict(dobs=["1985-03-12"], countries=["NG"]))), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_name_agrees_dob_unknown_countries_differ_clears(self):
        d = full(card(hit=dict(countries=["NG"])))
        self.assertEqual((d.decision, d.reason_code), ("DIFFERENT_ENTITY", "LOCATION_MISMATCH"))
        self.assertEqual(sorted(d.evidence_ids), ["CUS-000001", "KYC-000001"])

    def test_no_country_on_one_side_never_clears(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(countries=["NG"])))[0], "REVIEW")
        self.assertEqual(outcome(card(hit=dict(countries=[])))[0], "REVIEW")      # "International"/"Europe" map to nothing

    def test_an_incomplete_picture_never_clears_on_location(self):
        gaps = dict(countries_complete=False, location_gaps=["NOTE-000009 says where the customer lived but names no country we can read"])
        self.assertEqual(outcome(card(gaps, dict(countries=["NG"]))), ("REVIEW", "INSUFFICIENT_DATA"))
        hit_gap = dict(countries=["NG"], countries_complete=False, country_gaps=["a country value on the hit could not be read (Lagos)"])
        self.assertEqual(outcome(card(hit=hit_gap)), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_a_country_merely_mentioned_blocks_the_clear(self):
        c = card(dict(possible_countries=["NG"], possible_country_sources={"NG": ["NOTE-000009"]}), dict(countries=["NG"]))
        d = full(c)
        self.assertEqual((d.decision, d.reason_code), ("REVIEW", "INSUFFICIENT_DATA"))
        self.assertIn("NOTE-000009", d.explanation)
        self.assertEqual(outcome(card(dict(possible_countries=["FR"]), dict(countries=["NG"]))),
                         ("DIFFERENT_ENTITY", "LOCATION_MISMATCH"))                  # mentioned, but not the hit's country


class TestName(unittest.TestCase):
    def test_verified_name_disagrees_even_if_the_declared_name_agrees(self):
        c = card(dict(legal_name="Sarah Johnson", other_names=["Jacob Johnson"], countries=[]),
                 dict(names=["Johnson, James Jacob"]))
        self.assertEqual(outcome(c), ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED"))

    def test_declared_name_alone_never_clears(self):
        c = card(dict(legal_name="Sarah Johnson", name_verified=False, countries=[]), dict(names=["Johnson, James Jacob"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_one_real_part_neither_confirms_nor_clears(self):
        c = card(dict(legal_name="NA Hassan", real_name_parts=1, countries=[]), dict(names=["Peter Brown"], dobs=["1985-03-12"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))
        c = card(dict(legal_name="NA Hassan", real_name_parts=1, countries=[]), dict(names=["Mohamed Hassan"], dobs=["1985-03-12"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_single_part_alias_can_agree(self):
        c = card(dict(countries=[]), dict(names=["Peter Brown", "Hassan"], dobs=["1985-03-12"]))
        self.assertEqual(outcome(c), ("SAME_ENTITY", "NAME_DOB_MATCH"))

    def test_uncertain_identity_never_clears_on_name(self):
        c = card(dict(legal_name="Sarah Johnson", countries=[], name_certain=False,
                      identity_gaps=["the outcome of identity check NOTE-000002 could not be read"]),
                 dict(names=["Peter Brown"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_a_name_written_only_in_another_script_is_not_comparable(self):
        c = card(dict(countries=[]), dict(names=["Александар Раковић"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))


class TestConfirmation(unittest.TestCase):
    def test_person(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(dobs=["1985-03-12"]))), ("SAME_ENTITY", "NAME_DOB_MATCH"))
        self.assertEqual(outcome(card(hit=dict(dobs=["1985-03-12"], countries=["EG"]))), ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH"))

    def test_company(self):
        co = dict(entity_type="company", legal_name="Hassan Trading Ltd", dob="2015-06-01", countries=["AL"],
                  country_sources={"AL": ["CUS-000001"]})
        hit = dict(entity_type="company", names=["Hassan Trading Limited"], countries=["AL"])
        self.assertEqual(outcome(card(co, hit)), ("SAME_ENTITY", "NAME_LOCATION_MATCH"))
        self.assertEqual(outcome(card(co, {**hit, "earliest_report_date": "2010-01-01"})),
                         ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))           # a contradiction beats the match
        self.assertEqual(outcome(card(co, {**hit, "countries": []}))[0], "REVIEW")  # a company is not confirmed on name alone

    def test_a_blocked_contradiction_is_never_confirmed(self):
        c = card(dict(legal_name="Sarah Johnson", other_names=["Mohamed Hassan"], countries=[], name_certain=False,
                      identity_gaps=["approved checks of the same day disagree"]),
                 dict(names=["Mohamed Hassan"], dobs=["1985-03-12"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))

    def test_identity_in_doubt_is_never_confirmed(self):
        c = card(dict(countries=[], identity_conflict=True, identity_gaps=["the outcome of identity check NOTE-000002 could not be read"]),
                 dict(dobs=["1985-03-12"]))
        self.assertEqual(outcome(c), ("REVIEW", "INSUFFICIENT_DATA"))


class TestSeveralPeopleAndOrder(unittest.TestCase):
    def decided(self, c):
        d, a = decide(c, V)
        return explain(c, d, a), c

    def test_same_decision_for_everyone(self):
        one = self.decided(card(hit=dict(countries=["NG"])))
        two = self.decided(card(dict(customer_id="CUS-000002", record_ids=["CUS-000002"], countries=["FR"],
                                     country_sources={"FR": ["CUS-000002"]}), dict(countries=["NG"])))
        d = explain_ambiguous("A-000001", "H-000001", [one, two])
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id), ("DIFFERENT_ENTITY", "LOCATION_MISMATCH", "AMBIGUOUS"))
        self.assertIn("CUS-000002", d.evidence_ids)
        self.assertIn("CUS-000001", d.evidence_ids)

    def test_different_decisions(self):
        one = self.decided(card(hit=dict(countries=["NG"])))
        two = self.decided(card(dict(customer_id="CUS-000002", record_ids=["CUS-000002"], countries=["NG"],
                                     country_sources={"NG": ["CUS-000002"]}), dict(countries=["NG"])))
        d = explain_ambiguous("A-000001", "H-000001", [one, two])
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id), ("REVIEW", "AMBIGUOUS_CUSTOMER_RECORD", "AMBIGUOUS"))

    def test_nobody_found(self):
        d = explain_no_customer("A-000001", "H-000001", "Nobody", "none")
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id), ("REVIEW", "INSUFFICIENT_DATA", None))

    def test_two_clear_rules_first_in_sop_order_names_the_code_both_are_cited(self):
        c = card(dict(legal_name="Sarah Johnson"), dict(names=["Peter Brown"], dobs=["1962"], countries=["NG"]))
        d = full(c)
        self.assertEqual((d.decision, d.reason_code), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))
        self.assertIn("linked only to", d.explanation)
        self.assertIn("verified name", d.explanation)
        self.assertEqual(sorted(d.evidence_ids), ["CUS-000001", "KYC-000001"])

    def test_one_reliable_contradiction_is_enough(self):
        c = card(dict(legal_name="Sarah Johnson", name_certain=False, identity_gaps=["a check could not be read"]),
                 dict(names=["Peter Brown"], countries=["NG"]))
        self.assertEqual(outcome(c), ("DIFFERENT_ENTITY", "LOCATION_MISMATCH"))

    def test_reason_is_two_to_four_sentences_and_never_empty(self):
        for c in [card(hit=dict(countries=["NG"])), card(dict(countries=[]), dict(dobs=["1985-03-12"])),
                  card(dict(countries=[]), dict(dobs=[])),
                  card(dict(countries_complete=False, location_gaps=["a note could not be read"]), dict(countries=["NG"]))]:
            d = full(c)
            self.assertTrue(d.explanation.strip())
            self.assertLessEqual(d.explanation.count(". ") + 1, 5)


if __name__ == "__main__":
    unittest.main()
