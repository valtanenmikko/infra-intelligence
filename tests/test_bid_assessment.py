import unittest

from infra_intelligence.llm.bid_assessment import (
    build_prompt,
    competition_score,
    expected_bids,
    overall_score,
    parse_assessment,
    parse_assessments,
    parse_resources,
    recommendation,
)

TENDER = {
    "publication_number": "700001-2026",
    "title": "Maanteiden hoitourakka Viinijärvi 2027-2032",
    "buyer_name": "ELY-keskukset / elinvoimakeskukset",
    "infra_category": "Teiden kunnossapito",
    "regions": [],
    "region": "Pohjois-Karjala",
    "contract_start_year": 2027,
    "contract_end_year": 2032,
    "option_years": 2,
    "estimated_value_eur": None,
    "has_price_index_clause": True,
    "scope_summary": "Maanteiden hoito Liperin alueella.",
    "key_requirements": ["Päivystys 24/7"],
    "risks": ["Pitkä sopimuskausi"],
    "buyer_past_top_winners": [{"company": "Destia Oy", "wins": 30}],
    "region_past_top_winners": None,
    "region_past_avg_bids": None,
    "buyer_past_avg_bids": 3.5,
    "buyer_past_bid_awards": 3,
    "category_avg_bids": 3.9,
    "description": "Sopimukseen kuuluvaa tiestöä on yhteensä noin 900 kilometriä, josta soratietä noin 245 km.",
}

LLM_OUTPUT = {
    "fit": 5, "fit_reason": " Ydinliiketoimintaa. ",
    "risk": 3, "risk_reason": "Pitkä kausi, indeksiehto olemassa.",
    "summary": "Kiinnostava hoitourakka.",
    "questions_for_bid_team": ["Kalustotilanne?", "", "Aliurakoitsijat?", "Päivystys?", "Liikaa"],
}


class ExpectedBidsTest(unittest.TestCase):
    def test_shrinks_buyer_history_toward_category(self):
        self.assertEqual(expected_bids(TENDER), 3.7)  # (3 * 3.5 + 3 * 3.9) / 6
        self.assertEqual(expected_bids({**TENDER, "buyer_past_bid_awards": 30}), 3.5)

    def test_regional_history_is_not_used(self):
        self.assertEqual(expected_bids({**TENDER, "region_past_avg_bids": 1.0}), 3.7)

    def test_falls_back_to_available_history(self):
        self.assertEqual(expected_bids({**TENDER, "buyer_past_avg_bids": None}), 3.9)
        self.assertEqual(expected_bids({**TENDER, "buyer_past_bid_awards": 0}), 3.9)
        self.assertEqual(expected_bids({**TENDER, "category_avg_bids": None}), 3.5)
        self.assertIsNone(expected_bids({"publication_number": "x"}))


class ScoringTest(unittest.TestCase):
    def test_competition_score_bands(self):
        self.assertEqual([competition_score(b) for b in (1.0, 2.0, 3.5, 4.2, 9.0, None)], [5, 4, 3, 2, 1, 3])

    def test_overall_score_range(self):
        self.assertEqual(overall_score(1, 1, 1), 0)
        self.assertEqual(overall_score(5, 5, 5), 100)
        self.assertEqual(overall_score(5, 3, 3), 70)

    def test_recommendation_thresholds(self):
        self.assertEqual(recommendation(70, 4), "Tarjoa")
        self.assertEqual(recommendation(50, 3), "Harkitse")
        self.assertEqual(recommendation(30, 3), "Ei tarjota")
        self.assertEqual(recommendation(90, 1), "Ei tarjota")  # no fit overrides everything


class PromptTest(unittest.TestCase):
    def test_prompt_contains_profile_tender_and_history(self):
        p = build_prompt([TENDER])
        self.assertEqual(p.count("Esimerkkiprofiili"), 1)
        self.assertIn("### id: 700001-2026", p)
        self.assertIn("Viinijärvi", p)
        self.assertIn("2027–2032", p)
        self.assertIn("Destia Oy (30)", p)
        self.assertIn("Odotettu tarjousmäärä historian perusteella: 3.7", p)
        self.assertIn("Kuvaus: Sopimukseen kuuluvaa tiestöä on yhteensä noin 900", p)

    def test_prompt_shows_award_criteria(self):
        named = [{"name": "Vertailuhinta", "kind": "price", "share": 0.65}, {"name": "Laatu", "kind": "quality", "share": 0.35}]
        self.assertIn("Vertailuperusteet: Vertailuhinta 65 %, Laatu 35 %", build_prompt([{**TENDER, "award_criteria": named}]))
        self.assertIn("Vertailuperusteet: hinta 80 %, laatu 20 %", build_prompt([{**TENDER, "price_share": 0.8}]))
        self.assertIn("Vertailuperusteet: pelkkä hinta", build_prompt([{**TENDER, "price_share": 1.0}]))
        self.assertIn("Vertailuperusteet: ei tietoa", build_prompt([TENDER]))

    def test_long_description_is_truncated(self):
        p = build_prompt([{**TENDER, "description": "x" * 10_000}])
        self.assertIn("x" * 3000, p)
        self.assertNotIn("x" * 3001, p)

    def test_batch_prompt_has_one_block_per_tender(self):
        p = build_prompt([TENDER, {**TENDER, "publication_number": "700002-2026"}])
        self.assertIn("Arvioi nämä 2 avointa", p)
        self.assertEqual(p.count("### id:"), 2)

    def test_prompt_handles_missing_fields(self):
        p = build_prompt([{"publication_number": "x"}])
        self.assertIn("Sopimuskausi: ei tietoa", p)
        self.assertIn("Alue: ei tietoa", p)


class ParseAssessmentsTest(unittest.TestCase):
    def test_batch_keeps_valid_items_in_input_order(self):
        other = {**TENDER, "publication_number": "700002-2026", "buyer_past_avg_bids": 1.2, "buyer_past_bid_awards": 30}
        items = [
            {**LLM_OUTPUT, "id": "700002-2026"},
            {**LLM_OUTPUT, "id": "700001-2026"},
            {**LLM_OUTPUT, "id": "unknown"},
            {**LLM_OUTPUT, "id": "700001-2026", "fit": 1},  # duplicate: first wins
        ]
        results = parse_assessments({"items": items}, [TENDER, other])
        self.assertEqual([r.publication_number for r in results], ["700001-2026", "700002-2026"])
        self.assertEqual(results[0].fit, 5)
        self.assertEqual(results[1].competition, 5)  # computed from that tender's own history

    def test_invalid_item_is_skipped_not_fatal(self):
        results = parse_assessments({"items": [{**LLM_OUTPUT, "id": "700001-2026", "risk": 9}]}, [TENDER])
        self.assertEqual(results, [])

    def test_missing_items_raises(self):
        with self.assertRaises(ValueError):
            parse_assessments({}, [TENDER])


class ParseResourcesTest(unittest.TestCase):
    def test_valid_figures_are_kept(self):
        r = parse_resources({"road_km": 900, "gravel_road_km": 245, "high_class_winter_km": 130, "cycleway_km": 45.0,
                             "difficulty": "perusurakka", "notes": [" Päivystys 24/7 ", "", "a", "b", "c", "d"]})
        self.assertEqual((r["road_km"], r["gravel_road_km"], r["high_class_winter_km"], r["cycleway_km"]),
                         (900.0, 245.0, 130.0, 45.0))
        self.assertEqual(r["difficulty"], "perusurakka")
        self.assertEqual(r["resource_notes"], ["Päivystys 24/7", "a", "b", "c"])

    def test_parts_above_total_and_invalid_values_are_dropped(self):
        r = parse_resources({"road_km": 900, "gravel_road_km": 2450, "high_class_winter_km": -5, "cycleway_km": True,
                             "difficulty": "helppo", "notes": "ei lista"})
        self.assertEqual(r, {"road_km": 900.0, "gravel_road_km": None, "high_class_winter_km": None,
                             "cycleway_km": None, "difficulty": None, "resource_notes": []})

    def test_missing_resources_give_empty_scope(self):
        r = parse_resources(None)
        self.assertIsNone(r["road_km"])
        self.assertEqual(r["resource_notes"], [])


class ParseAssessmentTest(unittest.TestCase):
    def test_combines_llm_ratings_with_computed_competition(self):
        a = parse_assessment(LLM_OUTPUT, {**TENDER, "buyer_past_bid_awards": 30})
        self.assertEqual((a.fit, a.risk, a.competition, a.expected_bids), (5, 3, 3, 3.5))
        self.assertEqual(a.score, 70)
        self.assertEqual(a.recommendation, "Tarjoa")
        self.assertEqual(a.fit_reason, "Ydinliiketoimintaa.")
        self.assertEqual(a.questions_for_bid_team, ["Kalustotilanne?", "Aliurakoitsijat?", "Päivystys?"])

    def test_resources_are_attached(self):
        a = parse_assessment({**LLM_OUTPUT, "resources": {"road_km": 900, "difficulty": "vaativa urakka"}}, TENDER)
        self.assertEqual((a.road_km, a.difficulty, a.resource_notes), (900.0, "vaativa urakka", []))

    def test_rejects_out_of_range_ratings(self):
        for bad in (0, 6, "5", True, None):
            with self.assertRaises(ValueError):
                parse_assessment({**LLM_OUTPUT, "fit": bad}, TENDER)

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            parse_assessment([], TENDER)


if __name__ == "__main__":
    unittest.main()
