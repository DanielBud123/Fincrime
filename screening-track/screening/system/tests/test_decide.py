"""The 17 examples from the decision-half brief (CLAUDE.md), plus partial-date
and short-name edge cases. Unshown fields take the brief's example fact card.
Run:  python -m unittest discover -s system/tests   (from screening/)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from decide import decide, decide_hit  # noqa: E402
from names import Variants  # noqa: E402
from schema import CustomerFacts, FactCard, HitFacts  # noqa: E402

V = Variants({"groups": [["muhammad", "mohammed", "mohamed"], ["hassan", "hasan"]],
              "company_legal_forms": ["ltd", "limited", "srl"]})


def customer(**kw):
    c = dict(customer_id="C-00042", entity_type="person", legal_name="Mohamed Ali Hassan", name_verified=True,
             other_names=["Mo Hassan"], dob="1985-03-12", countries=["GB", "EG"], source_ids=["CUST-00042", "KYC-00917"])
    c.update(kw)
    return CustomerFacts(**c)


def hit(**kw):
    # earliest_report_date is None here, not the brief card's "2011-05-02": with it, examples 7 and 8
    # (a company incorporated 2015) would fire TEMPORAL_IMPOSSIBILITY before the rule they illustrate.
    h = dict(hit_id="H-0001", entity_type="person", names=["Muhammad Hasan", "Mohammed Hassan"],
             dobs=["1962", "1962-07-04"], countries=["EG"], earliest_report_date=None, date_of_death=None,
             source_ids=["H-0001", "SR-3310"])
    h.update(kw)
    return HitFacts(**h)


def outcome(cust=None, h=None, screened_at="2024-03-15"):
    card = FactCard(alert_id="A-0001", hit_id="H-0001", screened_at=screened_at,
                    customer=cust or customer(), hit=h or hit())
    d, _ = decide(card, V)
    return d.decision, d.reason_code


COMPANY = dict(entity_type="company", legal_name="Blue Harbour Trading Ltd", other_names=[], dob="2015-06-01", countries=["AL"])


class TestBriefExamples(unittest.TestCase):
    def test_01_dob_mismatch_years_apart(self):
        self.assertEqual(outcome(h=hit(names=["Muhammad Hasan"], dobs=["1962"])), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))

    def test_02_dob_mismatch_same_year_other_month(self):
        self.assertEqual(outcome(h=hit(names=["Mohamed Hassan"], dobs=["1985-07"])), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))

    def test_03_one_year_gap_is_not_a_mismatch(self):
        self.assertEqual(outcome(customer(dob="1985", countries=[]), hit(names=["Mohamed Hassan"], dobs=["1986"], countries=[])),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_04_two_hit_dobs_one_fits(self):
        self.assertEqual(outcome(customer(countries=[]), hit(dobs=["1962", "1985-03"], countries=[])),
                         ("SAME_ENTITY", "NAME_DOB_MATCH"))

    def test_05_name_dob_location_match(self):
        self.assertEqual(outcome(customer(legal_name="Arben Krasniqi", dob="1979-11-02", countries=["AL"]),
                                 hit(names=["Krasniqi, Arben"], dobs=["1979-11-02"], countries=["AL", "XK"])),
                         ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH"))

    def test_06_name_dob_agree_country_differs_is_review(self):
        self.assertEqual(outcome(customer(legal_name="Arben Krasniqi", dob="1979-11-02", countries=["AL"]),
                                 hit(names=["Arben Krasniqi"], dobs=["1979-11-02"], countries=["NG"])),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_07_company_location_mismatch(self):
        self.assertEqual(outcome(customer(**COMPANY), hit(entity_type="company", names=["Blue Harbor Trading Limited"],
                                                          dobs=[], countries=["NG", "GH"])),
                         ("DIFFERENT_ENTITY", "LOCATION_MISMATCH"))

    def test_08_company_name_location_match(self):
        self.assertEqual(outcome(customer(**COMPANY), hit(entity_type="company", names=["Blue Harbor Trading Limited"],
                                                          dobs=[], countries=["AL"])),
                         ("SAME_ENTITY", "NAME_LOCATION_MATCH"))

    def test_09_temporal_too_young(self):
        self.assertEqual(outcome(customer(dob="2001"), hit(dobs=[], earliest_report_date="2010-05-01")),
                         ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))

    def test_10_not_certain_enough_on_age(self):
        self.assertEqual(outcome(customer(dob="1994", countries=[]), hit(dobs=[], countries=[], earliest_report_date="2010-05-01")),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_11_deceased_beats_name_and_dob(self):
        self.assertEqual(outcome(h=hit(dobs=["1985-03-12"], date_of_death="2015-02-01")), ("DIFFERENT_ENTITY", "DECEASED"))

    def test_12_entity_type_mismatch(self):
        self.assertEqual(outcome(customer(legal_name="Elena Marin"), hit(entity_type="company", names=["Elena Marin SRL"])),
                         ("DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH"))

    def test_13_name_mismatch_verified(self):
        self.assertEqual(outcome(customer(legal_name="Ana Petrova", dob="1990-01-01"), hit(names=["Anna Petrosyan"], dobs=["1990-01-01"])),
                         ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED"))

    def test_14_declared_name_cannot_clear(self):
        self.assertEqual(outcome(customer(legal_name="Ana Petrova", name_verified=False, dob="1990-01-01"),
                                 hit(names=["Anna Petrosyan"], dobs=["1990-01-01"])),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_15_placeholders_are_not_name_parts(self):
        # Hit DOB set to agree so the name is the only open question (the card's 1962 would clear on DOB).
        self.assertEqual(outcome(customer(legal_name="NA Hassan"), hit(names=["Mohamed Hassan"], dobs=["1985-03-12"])),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_16_ambiguous_customer_record(self):
        h = hit(names=["Mohamed Hassan"], dobs=["1962-07-04"])
        c1 = customer(customer_id="C-1", legal_name="Mohamed Hassan", dob="1985-03-12", source_ids=["C-1"], record_ids=["C-1"])
        c2 = customer(customer_id="C-2", legal_name="Mohamed Hassan", dob="1962-07-04", source_ids=["C-2"], record_ids=["C-2"])
        d = decide_hit("A-0001", h, [c1, c2], "2024-03-15", V)
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id), ("REVIEW", "AMBIGUOUS_CUSTOMER_RECORD", "AMBIGUOUS"))

    def test_17_no_customer_found(self):
        d = decide_hit("A-0001", hit(), [], "2024-03-15", V)
        self.assertEqual((d.decision, d.reason_code, d.resolved_customer_id, d.evidence_ids),
                         ("REVIEW", "INSUFFICIENT_DATA", None, ["H-0001", "SR-3310"]))


class TestEdgeCases(unittest.TestCase):
    def test_partial_death_date_must_be_certainly_before_screening(self):
        self.assertEqual(outcome(h=hit(dobs=["1985-03-12"], date_of_death="2022-03"))[1], "DECEASED")
        self.assertNotEqual(outcome(h=hit(dobs=["1985-03-12"], date_of_death="2024-03"))[1], "DECEASED")

    def test_company_incorporated_after_report_needs_certainty(self):
        co = customer(**dict(COMPANY, dob="2015"))
        h = dict(entity_type="company", names=["Blue Harbor Trading Limited"], dobs=[], countries=["AL"])
        self.assertEqual(outcome(co, hit(earliest_report_date="2014-12-31", **h)), ("DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY"))
        self.assertEqual(outcome(co, hit(earliest_report_date="2015-06", **h)), ("SAME_ENTITY", "NAME_LOCATION_MATCH"))

    def test_one_part_verified_name_cannot_clear(self):
        self.assertEqual(outcome(customer(legal_name="Madonna", other_names=[], dob="1990-01-01"),
                                 hit(names=["Maria Lopez"], dobs=["1990-01-01"])),
                         ("REVIEW", "INSUFFICIENT_DATA"))

    def test_alias_counts_for_agreement_not_for_clearing(self):
        # Verified name disagrees -> clear, even though the declared alias agrees (POLICY 6: "even if the name on
        # their record does").
        self.assertEqual(outcome(customer(legal_name="Ana Petrova", other_names=["Mohamed Hassan"], dob="1985-03-12"),
                                 hit(names=["Mohamed Hassan"], dobs=["1985-03-12"])),
                         ("DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED"))
        self.assertEqual(outcome(customer(legal_name="Ana Petrova", name_verified=False, other_names=["Mohamed Hassan"]),
                                 hit(names=["Mohamed Hassan"], dobs=["1985-03-12"])),
                         ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH"))

    def test_same_year_same_month_different_day_contradicts(self):
        self.assertEqual(outcome(h=hit(dobs=["1985-03-20"])), ("DIFFERENT_ENTITY", "DOB_MISMATCH"))

    def test_year_only_agrees_with_full_date(self):
        self.assertEqual(outcome(h=hit(dobs=["1985"])), ("SAME_ENTITY", "NAME_DOB_LOCATION_MATCH"))


if __name__ == "__main__":
    unittest.main()
