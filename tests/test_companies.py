import unittest
from datetime import date

from infra_intelligence.transform.companies import parse_company


def _desc(fi: str) -> list[dict]:
    return [{"languageCode": "3", "description": "English"}, {"languageCode": "1", "description": fi}]


RAW = {
    "businessId": {"value": "0738421-1"},
    "registrationDate": "1989-07-12",
    "names": [
        {"name": "Pylon Rakennus Oy", "type": "1", "registrationDate": "2015-01-26"},
        {"name": "Rakennusyhtiö Muhonen Oy", "type": "1", "registrationDate": "2011-10-11", "endDate": "2015-01-26"},
        {"name": "Rakennusyhtiö Muhonen", "type": "3", "registrationDate": "2015-01-26"},
    ],
    "companyForms": [{"type": "16", "descriptions": _desc("Osakeyhtiö"), "registrationDate": "1994-12-14"}],
    "mainBusinessLine": {"type": "41000", "descriptions": _desc("Talonrakentaminen")},
}


class ParseCompanyTest(unittest.TestCase):
    def test_current_official_name_form_and_industry(self):
        c = parse_company(RAW)
        self.assertEqual(c.business_id, "0738421-1")
        self.assertEqual(c.name, "Pylon Rakennus Oy")
        self.assertEqual(c.company_form, "Osakeyhtiö")
        self.assertFalse(c.is_sole_trader)
        self.assertEqual((c.industry_code, c.industry), ("41000", "Talonrakentaminen"))
        self.assertEqual(c.registered_on, date(1989, 7, 12))

    def test_sole_trader(self):
        raw = {**RAW, "companyForms": [{"type": "26", "descriptions": _desc("Yksityinen elinkeinonharjoittaja")}]}
        self.assertTrue(parse_company(raw).is_sole_trader)

    def test_minimal_record(self):
        c = parse_company({"businessId": {"value": "1234567-1"}})
        self.assertEqual((c.name, c.company_form, c.is_sole_trader, c.registered_on), (None, None, False, None))


if __name__ == "__main__":
    unittest.main()
