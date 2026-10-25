import unittest
from datetime import date

from infra_intelligence.reference import cpv_category, notice_category
from infra_intelligence.transform.companies import CompanyRecord
from infra_intelligence.transform.silver import parse_notice, parse_winners, single_winner_pair

AWARD = {
    "publication-number": "254711-2024",
    "publication-date": "2024-04-26Z",
    "notice-type": "can-standard",
    "notice-title": {"fin": "Suomi – Ratatyöt – Esimerkkiurakka", "eng": "Finland – Railway works"},
    "description-lot": {"fin": ["Osa 1 kuvaus", "Osa 2 kuvaus"]},
    "buyer-name": {"fin": ["Väylävirasto"]},
    "buyer-identifier": ["1010547-1"],
    "main-classification-proc": ["45234100"],
    "classification-cpv": ["45234100", "45234100", "45000000"],
    "procedure-type": "open",
    "place-of-performance": ["FI19B", "FIN", "FI197"],
    "total-value": 851371.18,
    "total-value-cur": ["EUR"],
    "received-submissions-type-code": ["tenders", "t-esubm", "tenders"],
    "received-submissions-type-val": ["5", "5", "2"],
    "tender-value-lowest": ["851371.18"],
    "tender-value-highest": ["1644800"],
    "result-lot-identifier": ["LOT-0001", "LOT-0002"],
    "framework-agreement-lot": ["none", "none"],
    "winner-name": {"fin": ["Rautatieto oy"]},
    "winner-identifier": ["2412066-4", "2412066-4"],
    "winner-size": ["sme"],
}

FRAMEWORK = {
    "publication-number": "64885-2024",
    "notice-type": "can-standard",
    "framework-agreement-lot": ["fa-wo-rc"],
    "winner-name": {"fin": ["A Oy", "B Oy", "Mikko Pörsti"]},
    "winner-identifier": ["1111111-1", "2222222-2"],
    "winner-size": ["small", "micro"],
}


class ParseNoticeTest(unittest.TestCase):
    def setUp(self):
        self.n = parse_notice(AWARD)

    def test_core_fields(self):
        self.assertEqual(self.n.publication_date, date(2024, 4, 26))
        self.assertEqual(self.n.notice_category, "award")
        self.assertEqual(self.n.title, "Suomi – Ratatyöt – Esimerkkiurakka")
        self.assertEqual(self.n.description, "Osa 1 kuvaus\n\nOsa 2 kuvaus")
        self.assertEqual(self.n.buyer_id, "1010547-1")
        self.assertEqual(self.n.infra_category, "Rautatiet")
        self.assertEqual(self.n.cpv_codes, ["45234100", "45000000"])

    def test_regions_merge_nuts_versions_and_skip_country_code(self):
        self.assertEqual(self.n.regions, ["Pirkanmaa"])

    def test_competition_metrics_use_only_total_tender_counts(self):
        self.assertEqual((self.n.tenders_received_min, self.n.tenders_received_max), (2, 5))
        self.assertEqual(self.n.lot_count, 2)
        self.assertEqual((self.n.lowest_tender_eur, self.n.highest_tender_eur), (851371.18, 1644800.0))

    def test_single_winner(self):
        self.assertEqual(self.n.winner_ids, ["2412066-4"])
        self.assertEqual(self.n.winner_size, "sme")
        self.assertFalse(self.n.is_framework)

    def test_electronic_submissions_used_when_total_missing(self):
        n = parse_notice({**AWARD, "received-submissions-type-code": ["t-esubm", "t-sme"],
                          "received-submissions-type-val": ["4", "3"]})
        self.assertEqual((n.tenders_received_min, n.tenders_received_max), (4, 4))

    def test_non_eur_value_is_dropped(self):
        n = parse_notice({**AWARD, "total-value-cur": ["NOK"]})
        self.assertIsNone(n.total_value_eur)

    def test_minimal_notice_does_not_fail(self):
        n = parse_notice({"publication-number": "1-2024"})
        self.assertIsNone(n.publication_date)
        self.assertIsNone(n.infra_category)
        self.assertEqual(n.notice_category, "other")
        self.assertEqual((n.lot_count, n.regions, n.winner_ids), (1, [], []))

    def test_framework_winner_size_not_attributed(self):
        n = parse_notice(FRAMEWORK)
        self.assertTrue(n.is_framework)
        self.assertIsNone(n.winner_size)


def _company(business_id: str, name: str, sole_trader: bool = False) -> CompanyRecord:
    return CompanyRecord(business_id, name, "Osakeyhtiö", sole_trader, None, None, None)


class WinnersTest(unittest.TestCase):
    def test_single_winner_pair_is_trusted(self):
        self.assertEqual(single_winner_pair(AWARD), ("2412066-4", "Rautatieto oy"))

    def test_multi_winner_names_are_not_paired_by_position(self):
        self.assertIsNone(single_winner_pair(FRAMEWORK))

    def test_prh_name_wins_over_learned_name(self):
        rows = parse_winners(FRAMEWORK, {"1111111-1": "Old Name Oy"}, {"1111111-1": _company("1111111-1", "A Oy")})
        self.assertEqual((rows[0].winner_name, rows[0].is_registered_company), ("A Oy", True))

    def test_id_missing_from_prh_is_not_publishable(self):
        rows = parse_winners(FRAMEWORK, {"2222222-2": "B Oy"}, {})
        self.assertEqual((rows[1].winner_id, rows[1].winner_name, rows[1].is_registered_company), ("2222222-2", "B Oy", False))
        self.assertFalse(rows[1].is_single_winner)

    def test_sole_trader_is_not_publishable(self):
        rows = parse_winners(FRAMEWORK, {}, {"1111111-1": _company("1111111-1", "Mikko Pörsti", sole_trader=True)})
        self.assertFalse(rows[0].is_registered_company)

    def test_foreign_id_uses_legal_form(self):
        raw = {**AWARD, "winner-identifier": ["FI07551649"], "winner-name": {"fin": ["Nordic Rail AS"]}}
        [row] = parse_winners(raw, {}, {})
        self.assertTrue(row.is_registered_company)

    def test_single_winner_falls_back_to_own_cleaned_name(self):
        [row] = parse_winners(AWARD, {}, {})
        self.assertEqual((row.winner_name, row.is_single_winner), ("Rautatieto Oy", True))


class ReferenceTest(unittest.TestCase):
    def test_cpv_category_longest_prefix(self):
        self.assertEqual(cpv_category("45233252"), "Tiet ja kadut")
        self.assertEqual(cpv_category("45230000"), "Tie- ja ratarakentaminen, muu")
        self.assertEqual(cpv_category("90620000"), "Talvihoito")
        self.assertIsNone(cpv_category("45210000"))  # building construction is out of scope
        self.assertIsNone(cpv_category(None))

    def test_notice_category(self):
        self.assertEqual(notice_category("can-modif"), "modification")
        self.assertEqual(notice_category("cn-standard"), "competition")
        self.assertEqual(notice_category("pin-only"), "prior_information")


if __name__ == "__main__":
    unittest.main()
