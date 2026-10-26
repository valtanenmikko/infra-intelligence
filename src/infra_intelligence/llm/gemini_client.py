"""Minimal Gemini REST client for JSON-schema constrained generation (free tier friendly)."""

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class LlmResult:
    data: Any
    model: str
    input_tokens: int
    output_tokens: int


class JsonLlm(Protocol):
    """Any provider that returns schema-conforming JSON. Lets the pipeline swap models without code changes."""

    def generate_json(self, prompt: str, schema: dict[str, Any], system: str | None = None) -> LlmResult: ...


class LlmError(RuntimeError):
    pass


class GeminiClient:
    def __init__(
        self,
        session: Any,
        api_key: str,
        model: str,
        requests_per_minute: float = 8,
        max_retries: int = 5,
        backoff_s: float = 15.0,
        timeout_s: float = 300,
        thinking_level: str | None = "low",
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is missing")
        self._session = session
        self._api_key = api_key
        self._model = model
        self._min_interval_s = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._timeout_s = timeout_s
        # Gemini 3 models reason before answering by default; extraction needs little of it, and long
        # reasoning over a batch of notices can exceed the request timeout.
        self._thinking_level = thinking_level
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def generate_json(self, prompt: str, schema: dict[str, Any], system: str | None = None) -> LlmResult:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if self._thinking_level:
            body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": self._thinking_level}

        payload = self._post(body)
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            reason = (payload.get("candidates") or [{}])[0].get("finishReason")
            raise LlmError(f"Unexpected Gemini response (finishReason={reason}): {str(payload)[:500]}") from e
        usage = payload.get("usageMetadata") or {}
        return LlmResult(
            data=data,
            model=payload.get("modelVersion", self._model),
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        )

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{GEMINI_BASE_URL}/models/{self._model}:generateContent"
        for attempt in range(1, self._max_retries + 1):
            self._throttle()
            try:
                resp = self._session.post(url, json=body, headers={"x-goog-api-key": self._api_key}, timeout=self._timeout_s)
            except OSError as e:  # requests' timeouts and connection errors subclass OSError
                if attempt == self._max_retries:
                    raise LlmError(f"Gemini request failed after {attempt} attempts: {e}") from e
                self._sleep(self._backoff_s * 2 ** (attempt - 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                raise LlmError(f"Gemini API returned {resp.status_code}: {resp.text[:500]}")
            self._sleep(self._backoff_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")
