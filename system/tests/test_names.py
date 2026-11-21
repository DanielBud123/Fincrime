"""POLICY.md principle 8 on the name pairs from the practice labels.
Run:  python -m unittest discover -s system/tests   (from the repository root)
Uses an inline slice of name_variants.json so it needs no data folder."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from names import Variants, names_agree, normalize_name  # noqa: E402

V = Variants({
    "groups": [["muhammad", "mohammed", "mohamed"], ["yusuf", "josef", "joseph", "joe"], ["hassan", "hasan"],
               ["joseph", "joe", "jose"], ["john", "jon", "jack"], ["mark", "marc"], ["markus", "marcus"]],
    "company_legal_forms": ["ltd", "limited", "sa", "se", "ag", "inc"],
})


class TestNormalize(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_name("Mohámed  (Mo) Al-Hassan"), ["mohamed", "al", "hassan"])
        self.assertEqual(normalize_name("O'Brien-Smith N/A 123 x [alias]"), ["obrien", "smith"])
        self.assertEqual(normalize_name("TEST unknown XXX"), [])
        self.assertEqual(normalize_name("Pescanova S.A.", company=True, variants=V), ["pescanova"])
        self.assertEqual(normalize_name("N26 Bank AG", company=True, variants=V), ["n26", "bank"])


class TestAgree(unittest.TestCase):
    def check(self, a, b, expected, company=False):
        self.assertEqual(names_agree(a, b, V, company), expected, f"{a} | {b}")

    def test_agree(self):
        self.check("Mohamed Ali Hassan", "Muhammad Hasan", True)               # variants, missing middle name
        self.check("Arben Krasniqi", "Krasniqi, Arben", True)                  # order
        self.check("Abdul Salam Yusuf", "Abdulsalam Yusuf", True)              # written together
        self.check("Carl E. ANDERSEN", "Carl Andersen", True)                  # initial is not a part
        self.check("Elvira Velasco Mooillo", "Elvira Velasco Morillo", True)   # 2 edits on a 7+ part
        self.check("Yusuf Bello", "Joseph Bello", True)                        # joseph sits in two groups
        self.check("Mohamed Hassan", "Hassan", True)                           # single-part alias, shorter fully matched
        self.check("Pescanova S.A.", "Pescanova, Sociedad Anónima", True, company=True)  # label H-02115F
        self.check("Blue Harbour Trading Ltd", "Blue Harbor Trading Limited", True, company=True)

    def test_disagree(self):
        self.check("Ana Petrova", "Anna Petrosyan", False)                     # 3-letter part must be identical
        self.check("Ann Lee", "Anne Lee", False)
        self.check("Jonathan Reyes Whitfield", "John Whitfield", False)        # label H-CF173B
        self.check("MARKUS GERHARD MUELLER", "Mark Mueller", False)            # label H-D9BBCC
        self.check("CHINEDU AZEEZ", "Ridwan, Azeez", False)                    # label H-2808BE
        self.check("SARAH JOHNSON", "Johnson, James Jacob", False)             # label H-380854
        self.check("", "Mohamed Hassan", False)
        # dev hit H-124BB8: 'st'+'logistics' must not match 'logistics' with 2 free edits
        self.check("Starling Logistics Ltd", "ST Logistics (UK) Ltd.", False, company=True)

    def test_joined_parts_keep_their_edit_budget(self):
        self.check("Abdel Rahman Musa", "Abdulrahman Musa", True)              # 1 edit, shortest piece 5 letters


if __name__ == "__main__":
    unittest.main()
