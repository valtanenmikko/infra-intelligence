import json
import unittest
from unittest.mock import MagicMock

from infra_intelligence.llm.gemini_client import GeminiClient, LlmError


def _resp(status: int, payload: dict | None = None) -> MagicMock:
    r = MagicMock(status_code=status, text="err")
    r.json.return_value = payload or {}
    return r


def _ok(data: dict) -> MagicMock:
    return _resp(200, {
        "candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
        "modelVersion": "gemini-test-001",
    })


class GeminiClientTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.sleep = MagicMock()
        self.now = [0.0]
        self.client = GeminiClient(self.session, "key", "gemini-test", requests_per_minute=6,
                                   sleep=self.sleep, clock=lambda: self.now[0])

    def test_returns_parsed_json_and_usage(self):
        self.session.post.return_value = _ok({"items": []})
        result = self.client.generate_json("prompt", {"type": "OBJECT"}, system="sys")

        self.assertEqual(result.data, {"items": []})
        self.assertEqual((result.model, result.input_tokens, result.output_tokens), ("gemini-test-001", 120, 30))
        url = self.session.post.call_args.args[0]
        kwargs = self.session.post.call_args.kwargs
        self.assertTrue(url.endswith("/models/gemini-test:generateContent"))
        self.assertEqual(kwargs["headers"], {"x-goog-api-key": "key"})
        self.assertNotIn("key", url)  # API key never in the URL (would end up in logs)
        self.assertEqual(kwargs["json"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(kwargs["json"]["generationConfig"]["temperature"], 0)
        self.assertEqual(kwargs["json"]["systemInstruction"]["parts"][0]["text"], "sys")

    def test_throttles_to_requests_per_minute(self):
        self.session.post.return_value = _ok({})
        self.client.generate_json("a", {})
        self.now[0] = 4.0
        self.client.generate_json("b", {})
        self.sleep.assert_called_once_with(6.0)  # 60 / 6 rpm = 10 s interval, 4 s already passed

    def test_retries_rate_limit(self):
        self.session.post.side_effect = [_resp(429), _ok({"ok": True})]
        self.assertEqual(self.client.generate_json("p", {}).data, {"ok": True})
        self.sleep.assert_any_call(15.0)

    def test_client_error_not_retried(self):
        self.session.post.return_value = _resp(400)
        with self.assertRaises(LlmError):
            self.client.generate_json("p", {})
        self.session.post.assert_called_once()

    def test_blocked_response_raises(self):
        self.session.post.return_value = _resp(200, {"candidates": [{"finishReason": "SAFETY"}]})
        with self.assertRaisesRegex(LlmError, "SAFETY"):
            self.client.generate_json("p", {})

    def test_requires_api_key(self):
        with self.assertRaises(ValueError):
            GeminiClient(self.session, "", "m")


if __name__ == "__main__":
    unittest.main()
