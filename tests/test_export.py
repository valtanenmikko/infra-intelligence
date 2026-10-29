import unittest
from datetime import date
from unittest.mock import MagicMock

from infra_intelligence.export.databricks_sql import DatabricksSql, SqlError
from infra_intelligence.export.site_data import QUERIES, build_site_data, clean_title


class CleanTitleTest(unittest.TestCase):
    def test_strips_country_and_cpv_prefix(self):
        self.assertEqual(clean_title("Suomi – Rakennustyöt – FINAVIA OYJ: Päällystys – vaihe 2"), "FINAVIA OYJ: Päällystys – vaihe 2")

    def test_leaves_other_titles(self):
        for title in ("Maanteiden hoitourakka", "Sverige – X – Y", None, ""):
            self.assertEqual(clean_title(title), title)


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock(status_code=status, text="err")
    r.json.return_value = payload
    return r


def _result(state: str, columns=(), rows=(), chunks=1, sid="s1") -> dict:
    return {"statement_id": sid, "status": {"state": state, "error": {"message": "boom"}},
            "manifest": {"schema": {"columns": [{"name": c} for c in columns]}, "total_chunk_count": chunks},
            "result": {"data_array": [list(r) for r in rows]}}


class DatabricksSqlTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.sql = DatabricksSql(self.session, "https://h/", "tok", "wh", sleep=MagicMock())

    def test_polls_until_done_and_reads_chunks(self):
        self.session.post.return_value = _resp(_result("PENDING"))
        self.session.get.side_effect = [
            _resp(_result("SUCCEEDED", ["a", "b"], [("1", "x")], chunks=2)),
            _resp({"data_array": [["2", "y"]]}),
        ]
        rows = self.sql.query("SELECT 1")
        self.assertEqual(rows, [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}])
        self.assertEqual(self.session.post.call_args.kwargs["headers"], {"Authorization": "Bearer tok"})
        self.assertEqual(self.session.post.call_args.args[0], "https://h/api/2.0/sql/statements")

    def test_failed_statement_raises(self):
        self.session.post.return_value = _resp(_result("FAILED"))
        with self.assertRaisesRegex(SqlError, "boom"):
            self.sql.query("SELECT 1")

    def test_http_error_raises(self):
        self.session.post.return_value = _resp({}, status=403)
        with self.assertRaises(SqlError):
            self.sql.query("SELECT 1")

    def test_requires_credentials(self):
        with self.assertRaises(ValueError):
            DatabricksSql(self.session, "https://h", "", "wh")


class FakeSql:
    ROWS = {
        "kpis": [{"notices": "811", "awards": "283", "competitions": "460", "open_tenders": "23",
                  "single_winner_value_eur": "1.55E9", "avg_bids": "4.1", "share_low_competition": "0.29",
                  "period": "1/2024–10/2026"}],
        "market_share": [{"category": "Kaikki", "company": "A Oy", "wins": "3", "won_value_eur": None, "share_of_awards": "0.5", "slice_awards": "6"}],
        "competition": [], "regions": [], "buyers": [],
        "open_tenders": [{"id": "1", "title": "Suomi – Teiden korjaus – Maanteiden hoitourakka Oulu 2027-2032", "region": "", "period": "", "region_from_llm": "true", "score": "70",
                          "questions": '["Q?"]', "past_winners": None, "option_years": "2.0"}],
        "price_spread": [{"n": "17", "median_spread": "0.35"}],
        "llm_eval": [{"metric": "region_accuracy", "value": "0.9", "n": "400"}, {"metric": "value_without_ted_value", "value": "0.1", "n": "5"}],
        "bid_backtest": [{"metric": "bids_mae_shrunk", "value": "2.0", "n": "212"}],
        "eu_indicators": [{"n_bids": "222", "single_bid_share": "0.113", "n_price": "243", "price_only_share": "0.683"}],
        "criteria": [{"band": "Pelkkä hinta", "awards": "40", "avg_bids": "5.1", "share_low_competition": "0.2"}],
    }

    def query(self, statement):
        name = next(k for k, q in QUERIES.items() if q == statement)
        return self.ROWS[name]


class BuildSiteDataTest(unittest.TestCase):
    def setUp(self):
        self.data = build_site_data(FakeSql(), date(2026, 10, 26))

    def test_meta_and_kpis(self):
        self.assertEqual(self.data["meta"], {"sample": False, "generated_at": "2026-10-26", "period": "1/2024–10/2026",
                                             "sources": ["EU TED Search API v3", "PRH YTJ avoin data"]})
        self.assertEqual(self.data["kpis"]["notices"], 811)
        self.assertEqual(self.data["kpis"]["single_winner_value_eur"], 1.55e9)
        self.assertNotIn("period", self.data["kpis"])

    def test_types_are_cast(self):
        t = self.data["open_tenders"][0]
        self.assertEqual((t["score"], t["region_from_llm"], t["option_years"]), (70, True, 2.0))
        self.assertEqual((t["questions"], t["past_winners"], t["region"], t["period"]), (["Q?"], [], None, None))
        self.assertIsNone(self.data["market_share"][0]["won_value_eur"])
        self.assertEqual(self.data["price_spread"], {"n": 17, "median_spread": 0.35})

    def test_eval_keeps_labelled_metrics_only(self):
        self.assertEqual(self.data["llm_eval"], [{"metric": "region_accuracy", "value": 0.9, "n": 400, "label": "Maakunta oikein"}])

    def test_eu_indicators_are_one_row(self):
        self.assertEqual(self.data["eu_indicators"], {"n_bids": 222, "single_bid_share": 0.113, "n_price": 243,
                                                      "price_only_share": 0.683})

    def test_criteria_bands_are_cast(self):
        self.assertEqual(self.data["criteria"], [{"band": "Pelkkä hinta", "awards": 40, "avg_bids": 5.1, "share_low_competition": 0.2}])

    def test_bid_backtest_is_keyed_by_metric(self):
        self.assertEqual(self.data["bid_backtest"], {"bids_mae_shrunk": {"value": 2.0, "n": 212}})

    def test_open_tender_title_is_cleaned(self):
        self.assertEqual(self.data["open_tenders"][0]["title"], "Maanteiden hoitourakka Oulu 2027-2032")

    def test_descriptions_are_not_exported(self):
        self.assertNotIn("description", QUERIES["open_tenders"].split("FROM")[0])


if __name__ == "__main__":
    unittest.main()
