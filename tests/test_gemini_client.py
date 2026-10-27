import json
import unittest
from unittest.mock import MagicMock

from infra_intelligence.llm.gemini_client import GeminiClient, LlmError


def _resp(status: int, payload: dict | None = None, text: str = "err") -> MagicMock:
    r = MagicMock(status_code=status, text=text)
    r.json.return_value = payload or {}
    return r


def _ok(data: dict, model: str = "gemini-test-001") -> MagicMock:
    return _resp(200, {
        "candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
        "modelVersion": model,
    })


def _url_model(call) -> str:
    return call.args[0].rsplit("/models/", 1)[1].split(":")[0]


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
        self.assertEqual(kwargs["json"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})

    def test_thinking_config_can_be_disabled(self):
        client = GeminiClient(self.session, "key", "m", thinking_level=None, sleep=self.sleep)
        self.session.post.return_value = _ok({})
        client.generate_json("p", {})
        self.assertNotIn("thinkingConfig", self.session.post.call_args.kwargs["json"]["generationConfig"])

    def test_model_without_thinking_support_is_retried_without_it(self):
        self.session.post.side_effect = [_resp(400, text="Unknown field thinkingConfig"), _ok({"ok": True}), _ok({})]
        self.assertEqual(self.client.generate_json("p", {}).data, {"ok": True})
        self.assertNotIn("thinkingConfig", self.session.post.call_args_list[1].kwargs["json"]["generationConfig"])
        self.client.generate_json("p", {})  # remembered for later calls
        self.assertNotIn("thinkingConfig", self.session.post.call_args_list[2].kwargs["json"]["generationConfig"])

    def test_throttles_to_requests_per_minute(self):
        self.session.post.return_value = _ok({})
        self.client.generate_json("a", {})
        self.now[0] = 4.0
        self.client.generate_json("b", {})
        self.sleep.assert_called_once_with(6.0)  # 60 / 6 rpm = 10 s interval, 4 s already passed

    def test_retries_rate_limit(self):
        self.session.post.side_effect = [_resp(429), _ok({"ok": True})]
        self.assertEqual(self.client.generate_json("p", {}).data, {"ok": True})
        self.sleep.assert_any_call(10.0)

    def test_retries_network_timeouts(self):
        self.session.post.side_effect = [TimeoutError("read timed out"), _ok({"ok": True})]
        self.assertEqual(self.client.generate_json("p", {}).data, {"ok": True})

    def test_single_model_exhausted_raises(self):
        self.session.post.side_effect = ConnectionError("down")
        with self.assertRaisesRegex(LlmError, "All models unavailable"):
            self.client.generate_json("p", {})
        self.assertEqual(self.session.post.call_count, 3)

    def test_client_error_not_retried_or_fallen_back(self):
        client = GeminiClient(self.session, "key", ["a", "b"], sleep=self.sleep)
        self.session.post.return_value = _resp(400, text="bad schema")
        with self.assertRaises(LlmError):
            client.generate_json("p", {})
        self.session.post.assert_called_once()

    def test_blocked_response_raises(self):
        self.session.post.return_value = _resp(200, {"candidates": [{"finishReason": "SAFETY"}]})
        with self.assertRaisesRegex(LlmError, "SAFETY"):
            self.client.generate_json("p", {})

    def test_requires_api_key_and_models(self):
        with self.assertRaises(ValueError):
            GeminiClient(self.session, "", "m")
        with self.assertRaises(ValueError):
            GeminiClient(self.session, "key", [])


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.client = GeminiClient(self.session, "key", ["primary", "backup"], sleep=MagicMock())

    def test_overloaded_model_falls_back_and_stays_there(self):
        self.session.post.side_effect = [_resp(503), _resp(503), _resp(503), _ok({"n": 1}, "backup-001"), _ok({"n": 2})]
        first = self.client.generate_json("p", {})
        self.assertEqual((first.data, first.model), ({"n": 1}, "backup-001"))
        self.client.generate_json("p", {})
        self.assertEqual([_url_model(c) for c in self.session.post.call_args_list],
                         ["primary"] * 3 + ["backup", "backup"])
        self.assertEqual(self.client.active_model, "backup")

    def test_unknown_model_falls_back_immediately(self):
        self.session.post.side_effect = [_resp(404), _ok({})]
        self.client.generate_json("p", {})
        self.assertEqual([_url_model(c) for c in self.session.post.call_args_list], ["primary", "backup"])

    def test_all_models_failing_reports_each(self):
        self.session.post.return_value = _resp(429, text="quota exceeded")
        with self.assertRaisesRegex(LlmError, "primary.*backup"):
            self.client.generate_json("p", {})


if __name__ == "__main__":
    unittest.main()
