import unittest

from infra_intelligence.transform.names import canonical_names, clean_company_name, has_legal_form


class CleanCompanyNameTest(unittest.TestCase):
    def test_drops_business_unit_after_legal_form(self):
        self.assertEqual(clean_company_name("Destia Oy, Kunnossapitopalvelut"), "Destia Oy")

    def test_keeps_comma_when_head_is_not_a_company(self):
        name = "Helsingin kaupunki, kaupunkiympäristön toimiala"
        self.assertEqual(clean_company_name(name), name)

    def test_normalises_legal_form_casing(self):
        self.assertEqual(clean_company_name("Murron maansiirto oy"), "Murron maansiirto Oy")
        self.assertEqual(clean_company_name("Koneurakointi Jarkko Kosunen OYJ"), "Koneurakointi Jarkko Kosunen Oyj")

    def test_unescapes_html_and_collapses_whitespace(self):
        self.assertEqual(clean_company_name("  MD Svets &amp;  Service Ab "), "MD Svets & Service Ab")


class HasLegalFormTest(unittest.TestCase):
    def test_company_names(self):
        for name in ["Destia Oy", "YIT Suomi Oyj", "Keijo Ala-Kantti Ky", "Peab Industri Oy", "Tmi Virtanen"]:
            self.assertTrue(has_legal_form(name), name)

    def test_personal_names_are_not_companies(self):
        for name in ["Mikko Pörsti", "Koneurakointi Petri Sauvaniemi", "Hamnström Robert Jan", None, ""]:
            self.assertFalse(has_legal_form(name), name)

    def test_legal_form_must_be_a_whole_word(self):
        self.assertFalse(has_legal_form("Oyster Koneurakointi"))


class CanonicalNamesTest(unittest.TestCase):
    def test_most_frequent_cleaned_name_wins(self):
        pairs = [
            ("0111-1", "Destia Oy, Kunnossapitopalvelut"),
            ("0111-1", "Destia Oy, Energiapalvelut"),
            ("0111-1", "DESTIA OY"),
        ]
        self.assertEqual(canonical_names(pairs), {"0111-1": "Destia Oy"})

    def test_tie_breaks_by_shortest_name(self):
        pairs = [("1", "Pimara Väyläpalvelut Oy"), ("1", "Pimara Oy")]
        self.assertEqual(canonical_names(pairs)["1"], "Pimara Oy")

    def test_skips_missing_values(self):
        self.assertEqual(canonical_names([("", "X Oy"), ("2", "")]), {})


if __name__ == "__main__":
    unittest.main()
