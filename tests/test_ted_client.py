import unittest
from datetime import date
from unittest.mock import MagicMock

from infra_intelligence.ingest.ted_client import TED_SEARCH_URL, TedApiError, TedClient, build_query


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock(status_code=status, text="err")
    r.json.return_value = payload or {}
    return r


class BuildQueryTest(unittest.TestCase):
    def test_builds_expert_query(self):
        q = build_query(["45233000", "45234000"], "FIN", date(2024, 1, 1))
        self.assertEqual(
            q,
            "buyer-country=FIN AND classification-cpv IN (45233000 45234000) "
            "AND publication-date>=20240101",
        )

    def test_rejects_malformed_cpv(self):
        with self.assertRaises(ValueError):
            build_query(["4523) OR (1=1"], "FIN", date(2024, 1, 1))

    def test_rejects_empty_cpv_list(self):
        with self.assertRaises(ValueError):
            build_query([], "FIN", date(2024, 1, 1))

    def test_rejects_bad_country(self):
        with self.assertRaises(ValueError):
            build_query(["45233000"], "fi", date(2024, 1, 1))


class TedClientSearchTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.sleep = MagicMock()
        self.client = TedClient(self.session, page_size=2, sleep=self.sleep)

    def test_follows_iteration_tokens_until_exhausted(self):
        self.session.post.side_effect = [
            _resp(200, {"notices": [{"publication-number": "1"}, {"publication-number": "2"}], "iterationNextToken": "t1"}),
            _resp(200, {"notices": [{"publication-number": "3"}], "iterationNextToken": "t2"}),
            _resp(200, {"notices": [], "iterationNextToken": "t3"}),
        ]
        ids = [n["publication-number"] for n in self.client.search("q", ["publication-number"])]

        self.assertEqual(ids, ["1", "2", "3"])
        self.assertEqual(self.session.post.call_count, 3)
        second_body = self.session.post.call_args_list[1].kwargs["json"]
        self.assertEqual(second_body["iterationNextToken"], "t1")
        self.assertEqual(second_body["paginationMode"], "ITERATION")
        self.assertEqual(self.session.post.call_args_list[0].args[0], TED_SEARCH_URL)

    def test_stops_when_no_token(self):
        self.session.post.return_value = _resp(200, {"notices": [{"publication-number": "1"}]})
        self.assertEqual(len(list(self.client.search("q", []))), 1)
        self.session.post.assert_called_once()

    def test_strips_links(self):
        self.session.post.return_value = _resp(200, {"notices": [{"publication-number": "1", "links": {"pdf": {}}}]})
        notice = next(self.client.search("q", []))
        self.assertNotIn("links", notice)

    def test_retries_on_rate_limit_then_succeeds(self):
        self.session.post.side_effect = [_resp(429), _resp(200, {"notices": []})]
        self.assertEqual(list(self.client.search("q", [])), [])
        self.assertEqual(self.session.post.call_count, 2)
        self.sleep.assert_called_with(2.0)

    def test_raises_after_max_retries(self):
        self.session.post.return_value = _resp(503)
        with self.assertRaises(TedApiError):
            list(self.client.search("q", []))
        self.assertEqual(self.session.post.call_count, 3)

    def test_does_not_retry_client_errors(self):
        self.session.post.return_value = _resp(400)
        with self.assertRaises(TedApiError):
            list(self.client.search("q", []))
        self.session.post.assert_called_once()

    def test_rejects_invalid_page_size(self):
        with self.assertRaises(ValueError):
            TedClient(self.session, page_size=500)


if __name__ == "__main__":
    unittest.main()
