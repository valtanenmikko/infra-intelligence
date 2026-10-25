import unittest
from unittest.mock import MagicMock

from infra_intelligence.ingest.prh_client import PRH_COMPANIES_URL, PrhApiError, PrhClient, is_business_id


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock(status_code=status, text="err")
    r.json.return_value = payload or {}
    return r


class IsBusinessIdTest(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertTrue(is_business_id("1007822-3"))
        for value in ["FI10078223", "923 609 016", "1007822", "1007822-3; DROP", "", None]:
            self.assertFalse(is_business_id(value), value)


class PrhClientTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.sleep = MagicMock()
        self.client = PrhClient(self.session, sleep=self.sleep)

    def test_returns_first_company(self):
        self.session.get.return_value = _resp(200, {"totalResults": 1, "companies": [{"businessId": {"value": "1007822-3"}}]})
        self.assertEqual(self.client.get_company("1007822-3"), {"businessId": {"value": "1007822-3"}})
        self.session.get.assert_called_once_with(PRH_COMPANIES_URL, params={"businessId": "1007822-3"}, timeout=30)

    def test_not_in_open_data_returns_none(self):
        self.session.get.return_value = _resp(200, {"totalResults": 0, "companies": []})
        self.assertIsNone(self.client.get_company("3461459-6"))

    def test_404_returns_none(self):
        self.session.get.return_value = _resp(404)
        self.assertIsNone(self.client.get_company("3461459-6"))

    def test_retries_then_raises(self):
        self.session.get.return_value = _resp(503)
        with self.assertRaises(PrhApiError):
            self.client.get_company("1007822-3")
        self.assertEqual(self.session.get.call_count, 3)

    def test_rejects_invalid_id_without_calling_api(self):
        with self.assertRaises(ValueError):
            self.client.get_company("FI10078223")
        self.session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
