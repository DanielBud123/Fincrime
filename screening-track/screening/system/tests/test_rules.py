"""The 17 examples from the team brief plus date, name and extraction checks.
Run:  python -m unittest discover -s system/tests   (from screening/)"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from dates import PartialDate, age_bounds_at, birth_years_from_age, find_dates, parse_iso  # noqa: E402
from decide import decide  # noqa: E402
from hit_facts import dobs_from_text, REPORT_LINE_RE  # noqa: E402
from names import Variants, names_agree, normalize_name  # noqa: E402
from schema import CustomerFacts, FactCard, HitFacts  # noqa: E402

VARIANTS_PATH = os.path.join(HERE, "..", "..", "dev", "name_variants.json")
V = Variants(json.load(open(VARIANTS_PATH, encoding="utf-8"))) if os.path.exists(VARIANTS_PATH) else Variants(
    {"groups": [["muhammad", "mohammed", "mohammad", "mohamed"], ["hassan", "hasan"], ["thomas", "tom"]],
     "company_legal_forms": ["ltd", "limited", "sa", "inc", "llc"]})


def card(cust=None, hit=None, screened_at="2024-03-15"):
    c = dict(customer_id="C-1", entity_type="person", legal_name="Mohamed Ali Hassan", name_verified=True,
             other_names=[], dob="1985-03-12", countries=["GB", "EG"], source_ids=["C-1"], record_ids=["C-1"],
             name_source_id="KYC-1", dob_source_id="KYC-1", real_name_parts=3)
    c.update(cust or {})
    c["real_name_parts"] = max(len(normalize_name(c["legal_name"], c["entity_type"] == "company", V)),
                               *(len(normalize_name(n)) for n in c["other_names"]), 0) if "real_name_parts" not in (cust or {}) else c["real_name_parts"]
    h = dict(hit_id="H-1", entity_type="person", names=["Muhammad Hasan", "Mohammed Hassan"], dobs=["1962", "1962-07-04"],
             countries=["EG"], earliest_report_date=None, date_of_death=None, source_ids=[])
    h.update(hit or {})
    return FactCard(alert_id="A-1", hit_id="H-1", screened_at=screened_at, customer=CustomerFacts(**c), hit=HitFacts(**h))


def outcome(c):
    d, _ = decide(c, V)
    return d.decision, d.reason_code


class TestBriefExamples(unittest.TestCase):
    def test_01_dob_mismatch_years_apart(self):
        self.assertEqual(outcome(card(hit=dict(names=["Muhammad Hasan"], dobs=["1962"]))), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))

    def test_02_dob_mismatch_same_year_other_month(self):
        self.assertEqual(outcome(card(hit=dict(names=["Mohamed Hassan"], dobs=["1985-07"]))), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))

    def test_03_one_year_gap_is_review(self):
        self.assertEqual(outcome(card(dict(dob="1985", countries=[]), dict(names=["Mohamed Hassan"], dobs=["1986"], countries=[]))),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_04_two_hit_dobs_one_fits(self):
        self.assertEqual(outcome(card(dict(countries=[]), dict(names=["Mohamed Hassan"], dobs=["1962", "1985-03"], countries=[]))),
                         ("SAME_ENTITY", "NAME_DOB_MATCH"))

    def test_05_name_dob_location(self):
        self.assertEqual(outcome(card(dict(legal_name="Arben Krasniqi", dob="1979-11-02", countries=["AL"]),
                                      dict(names=["Krasniqi, Arben"], dobs=["1979-11-02"], countries=["AL", "XK"]))),
                         ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH"))

    def test_06_name_dob_agree_country_differs_is_review(self):
        self.assertEqual(outcome(card(dict(legal_name="Arben Krasniqi", dob="1979-11-02", countries=["AL"]),
                                      dict(names=["Arben Krasniqi"], dobs=["1979-11-02"], countries=["NG"]))),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_07_company_location_mismatch(self):
        self.assertEqual(outcome(card(dict(entity_type="company", legal_name="Blue Harbour Trading Ltd", dob="2015-06-01", countries=["AL"]),
                                      dict(entity_type="company", names=["Blue Harbor Trading Limited"], dobs=[], countries=["NG", "GH"]))),
                         ("DIFFERENT_ENTITY", "LOCATION_MISMATCH"))

    def test_08_company_name_location_match(self):
        self.assertEqual(outcome(card(dict(entity_type="company", legal_name="Blue Harbour Trading Ltd", dob="2015-06-01", countries=["AL"]),
                                      dict(entity_type="company", names=["Blue Harbor Trading Limited"], dobs=[], countries=["AL"]))),
                         ("SAME_ENTITY", "NAME_LOCATION_MATCH"))

    def test_09_temporal_too_young(self):
        self.assertEqual(outcome(card(dict(dob="2001", countries=[]), dict(names=["Mohamed Hassan"], dobs=[], countries=[], earliest_report_date="2010-05-01"))),
                         ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))

    def test_10_temporal_not_certain(self):
        self.assertEqual(outcome(card(dict(dob="1994", countries=[]), dict(names=["Mohamed Hassan"], dobs=[], countries=[], earliest_report_date="2010-05-01"))),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_11_deceased(self):
        self.assertEqual(outcome(card(hit=dict(names=["Mohamed Hassan"], dobs=["1985-03-12"], date_of_death="2015-02-01"))),
                         ("DIFFERENT_ENTITY", "DECEASED"))

    def test_12_entity_type(self):
        self.assertEqual(outcome(card(dict(legal_name="Elena Marin"), dict(entity_type="company", names=["Elena Marin SRL"]))),
                         ("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH"))

    def test_13_name_mismatch_verified(self):
        self.assertEqual(outcome(card(dict(legal_name="Ana Petrova", dob="1990-01-01", countries=[]), dict(names=["Anna Petrosyan"], dobs=["1990-01-01"], countries=[]))),
                         ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED"))

    def test_14_declared_name_cannot_clear(self):
        self.assertEqual(outcome(card(dict(legal_name="Ana Petrova", name_verified=False, dob="1990-01-01", countries=[]),
                                      dict(names=["Anna Petrosyan"], dobs=["1990-01-01"], countries=[]))),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_15_placeholder_name_cannot_confirm(self):
        self.assertEqual(outcome(card(dict(legal_name="NA Hassan", countries=[]), dict(names=["Mohamed Hassan"], dobs=["1985-03-12"], countries=[]))),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_17_no_customer_handled_by_pipeline(self):
        from explain import explain_no_customer
        d = explain_no_customer("A-1", "H-1", "Nobody", "none")
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id), ("REVIEW", "INSUFFICIENT_DATA", None))


class TestDates(unittest.TestCase):
    def test_formats(self):
        for raw, iso in [("2026-11-06", "2026-11-06"), ("19/05/2004", "2004-05-19"), ("February 19, 2002", "2002-02-19"),
                         ("9 May 2004", "2004-05-09"), ("1996", "1996"), ("1962-09", "1962-09"), ("N/A", None), ("31/02/2001", None)]:
            self.assertEqual(parse_iso(raw), iso, raw)

    def test_age_rules(self):
        self.assertEqual(birth_years_from_age(45, PartialDate(2019, 3)), [1973, 1974])
        self.assertEqual(age_bounds_at(PartialDate(2001), PartialDate(2010, 5, 1))[1], 9)
        self.assertEqual(age_bounds_at(PartialDate(1994), PartialDate(2010, 5, 1))[1], 16)

    def test_find_dates_in_text(self):
        found = [m.date.iso() for m in find_dates("born December 13, 1977, verified on 2023-02-19; aged 45 in March 2019")]
        self.assertEqual(found, ["1977-12-13", "2023-02-19", "2019-03"])


class TestNames(unittest.TestCase):
    def test_rule_8(self):
        self.assertTrue(names_agree("Mohamed Ali Hassan", "Muhammad Hasan", V))
        self.assertTrue(names_agree("Arben Krasniqi", "Krasniqi, Arben", V))
        self.assertTrue(names_agree("Abdul Salam Yusuf", "Abdulsalam Yusuf", V))
        self.assertTrue(names_agree("Carl E. Andersen", "Carl Andersen", V))
        self.assertTrue(names_agree("Elvira Velasco Mooillo", "Elvira Velasco Morillo", V))
        self.assertFalse(names_agree("Ana Petrova", "Anna Petrosyan", V))
        self.assertFalse(names_agree("Jonathan Reyes Whitfield", "John Whitfield", V))
        self.assertFalse(names_agree("Ann Lee", "Anne Lee", V))          # 3-letter parts must be identical
        self.assertTrue(names_agree("Pescanova SA", "Pescanova, Sociedad Anónima", V, company=True))
        self.assertEqual(normalize_name("N26 Bank SE", company=True, variants=V), ["n26", "bank"])


class TestHitExtraction(unittest.TestCase):
    def test_age_sentences(self):
        cases = {
            "November 1998 saw Elvira Velasco Morillo, a 30-year-old, face charges.": ["1967", "1968"],
            "When investigators conducted questioning of Michael Earl Tilley in January 2023, he was 46.": ["1976", "1977"],
            "A regulator's notice from May 2002 listed Aleksandar Raković, 29, a politically exposed person in Serbia.": ["1972", "1973"],
            "In February 2010, at the age of 33, Jérôme Kerviel was named in adverse media in France.": ["1976", "1977"],
            "Mark Edward Whitacre was born on 1 May 1957.": ["1957-05-01"],
            "Johan Peter Arne Lindqvist was born in 1966.": ["1966"],
            "Sterling Bank paid a NGN 52.97 000 000 fine in 2013.": [],
            "In October 2025 police recovered goods worth PKR 11,000,000, including PKR 3,100,000 in cash.": [],
            "The company, 45, Main Street, was fined in May 2019.": [],
        }
        for text, exp in cases.items():
            self.assertEqual([d.iso() for d in dobs_from_text(text)], exp, text)

    def test_report_line(self):
        notes = "According to premiumtimesng.com; June 10, 2014: Sterling Bank ...\n\nAccording to the Federal Bureau of Prisons, information as of December 13, 2017:\nName: X"
        self.assertEqual([m.group(1) for m in REPORT_LINE_RE.finditer(notes)], ["June 10, 2014"])



class TestCustomerNotes(unittest.TestCase):
    def test_residence_wording(self):
        from customer_facts import residence_countries
        self.assertEqual(residence_countries({"text": "The client confirmed their employment and residency in Denmark from 2016 to 2018."}), ["DK"])
        self.assertEqual(residence_countries({"text": "Confirmed address in Portugal."}), ["PT"])
        self.assertEqual(residence_countries({"text": "Customer asked how long an international transfer to Germany takes."}), [])
        self.assertEqual(residence_countries({"text": "Customer sent money to family in Nigeria."}), [])

    def test_identity_note_parsing(self):
        from customer_facts import _name_from_note, _dob_from_note, NEGATIVE_RE
        from dates import parse_date
        note = "On 2024-03-21, Onfido verified the driving licence for TASLIMA RAHIM ISLAM (DOB 1994-05-04), originating from Bangladesh."
        self.assertEqual(_name_from_note(note), "TASLIMA RAHIM ISLAM")
        self.assertEqual(_dob_from_note(note, parse_date("2024-03-21")).iso(), "1994-05-04")
        self.assertIsNone(_name_from_note("Persona: ANA LOPEZ and JUAN LOPEZ verified 2024-01-02."))
        self.assertIsNone(_dob_from_note("Onfido verified ANA LOPEZ, 1980-05-01, passport Spain, 2023-12-31.", parse_date("2024-01-02")))
        self.assertTrue(NEGATIVE_RE.search("Identity check for ANA LOPEZ failed on 2024-01-02: document expired."))

if __name__ == "__main__":
    unittest.main()
