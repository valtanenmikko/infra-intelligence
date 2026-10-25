import unittest

from infra_intelligence.llm.evaluation import region_metrics, value_metrics
from infra_intelligence.llm.extraction import EXTRACTION_SCHEMA, REGIONS, build_prompt, parse_extractions

NOTICE = {
    "publication_number": "1-2026",
    "title": "Maanteiden hoitourakka Viinijärvi 2027-2032",
    "buyer_name": "ELY-keskukset / elinvoimakeskukset",
    "description": "Urakka-alue sijaitsee Liperin ja Outokummun alueella. " + "x" * 5000,
    "regions": ["Pohjois-Karjala"],
    "total_value_eur": 12_000_000,
}

GOOD_ITEM = {
    "id": "1-2026",
    "municipalities": ["Liperi", "Outokumpu", "Liperi", " "],
    "region": "Pohjois-Karjala",
    "contract_start_year": 2027,
    "contract_end_year": 2032,
    "option_years": 2,
    "work_types": ["talvihoito", "sorateiden hoito"],
    "scope_summary": "  Maanteiden hoito Liperin alueella.  ",
    "key_requirements": ["Päivystys 24/7"],
    "risks": ["Pitkä sopimuskausi"],
    "has_price_index_clause": True,
    "mentioned_value_eur": None,
}


class BuildPromptTest(unittest.TestCase):
    def test_contains_text_but_withholds_ground_truth_fields(self):
        prompt = build_prompt([NOTICE])
        self.assertIn("### id: 1-2026", prompt)
        self.assertIn("Viinijärvi", prompt)
        self.assertNotIn("Pohjois-Karjala", prompt)  # TED region is held out for evaluation
        self.assertNotIn("12000000", prompt)

    def test_truncates_long_descriptions(self):
        self.assertLess(len(build_prompt([NOTICE])), 4500)


class SchemaTest(unittest.TestCase):
    def test_region_enum_is_finnish_names(self):
        enum = EXTRACTION_SCHEMA["properties"]["items"]["items"]["properties"]["region"]["enum"]
        self.assertEqual(enum, REGIONS)
        self.assertIn("Ahvenanmaa", enum)
        self.assertEqual(len(enum), 19)


class ParseExtractionsTest(unittest.TestCase):
    def test_valid_item(self):
        [r] = parse_extractions({"items": [GOOD_ITEM]}, ["1-2026"])
        self.assertEqual(r.municipalities, ["Liperi", "Outokumpu"])
        self.assertEqual((r.region, r.contract_start_year, r.contract_end_year, r.option_years), ("Pohjois-Karjala", 2027, 2032, 2.0))
        self.assertEqual(r.scope_summary, "Maanteiden hoito Liperin alueella.")
        self.assertTrue(r.has_price_index_clause)

    def test_drops_unknown_and_duplicate_ids_and_keeps_input_order(self):
        items = [{**GOOD_ITEM, "id": "2-2026"}, GOOD_ITEM, {**GOOD_ITEM, "id": "999"}, {**GOOD_ITEM, "region": None}]
        records = parse_extractions({"items": items}, ["1-2026", "2-2026"])
        self.assertEqual([r.publication_number for r in records], ["1-2026", "2-2026"])
        self.assertEqual(records[0].region, "Pohjois-Karjala")  # first occurrence wins

    def test_invalid_values_become_null(self):
        bad = {**GOOD_ITEM, "region": "Ruotsi", "contract_start_year": 2032, "contract_end_year": 2027,
               "option_years": 99, "mentioned_value_eur": True, "has_price_index_clause": "kyllä", "scope_summary": ""}
        [r] = parse_extractions({"items": [bad]}, ["1-2026"])
        self.assertEqual((r.region, r.contract_start_year, r.contract_end_year, r.option_years), (None, None, None, None))
        self.assertIsNone(r.mentioned_value_eur)
        self.assertIsNone(r.has_price_index_clause)
        self.assertIsNone(r.scope_summary)

    def test_lists_are_capped(self):
        [r] = parse_extractions({"items": [{**GOOD_ITEM, "risks": [f"r{i}" for i in range(9)]}]}, ["1-2026"])
        self.assertEqual(len(r.risks), 5)

    def test_missing_items_raises(self):
        with self.assertRaises(ValueError):
            parse_extractions({"foo": []}, ["1-2026"])


class EvaluationTest(unittest.TestCase):
    def test_region_metrics_score_single_region_notices_only(self):
        pairs = [("Lappi", ["Lappi"]), ("Kainuu", ["Lappi"]), (None, ["Lappi"]), ("Lappi", ["Lappi", "Kainuu"]), ("Lappi", [])]
        m = {x.name: x for x in region_metrics(pairs)}
        self.assertEqual(m["region_coverage"].n, 3)
        self.assertAlmostEqual(m["region_coverage"].value, 2 / 3)
        self.assertAlmostEqual(m["region_precision"].value, 1 / 2)
        self.assertAlmostEqual(m["region_accuracy"].value, 1 / 3)

    def test_value_metrics(self):
        pairs = [(100.0, 102.0), (100.0, 150.0), (50.0, None), (None, 10.0)]
        m = {x.name: x for x in value_metrics(pairs)}
        self.assertEqual((m["value_match"].value, m["value_match"].n), (0.5, 2))
        self.assertAlmostEqual(m["value_without_ted_value"].value, 1 / 3)

    def test_empty_inputs(self):
        self.assertIsNone(region_metrics([])[0].value)


if __name__ == "__main__":
    unittest.main()
