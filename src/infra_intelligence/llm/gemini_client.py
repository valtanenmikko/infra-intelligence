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


class _ModelUnavailable(Exception):
    """The model cannot serve requests right now (overloaded, quota exhausted, unknown): try the next one."""


class GeminiClient:
    """Calls the first available model in `models`.

    Free-tier models are often overloaded (503) or out of daily quota (429). After retries the client falls back to
    the next model and stays there for the rest of the run, so a bad model costs its retry time only once.
    """

    def __init__(
        self,
        session: Any,
        api_key: str,
        models: str | list[str],
        requests_per_minute: float = 8,
        max_retries: int = 3,
        backoff_s: float = 10.0,
        timeout_s: float = 300,
        thinking_level: str | None = "low",
        sleep=time.sleep,
        clock=time.monotonic,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is missing")
        self._models = [models] if isinstance(models, str) else list(models)
        if not self._models:
            raise ValueError("At least one model is required")
        self._session = session
        self._api_key = api_key
        self._active = 0
        self._min_interval_s = 60.0 / requests_per_minute
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._timeout_s = timeout_s
        # Gemini 3 models reason before answering by default; extraction needs little of it, and long
        # reasoning over a batch of notices can exceed the request timeout.
        self._thinking_level = thinking_level
        self._no_thinking: set[str] = set()  # models that rejected thinkingConfig
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    @property
    def active_model(self) -> str:
        return self._models[min(self._active, len(self._models) - 1)]

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

        payload, model = self._post(body)
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            reason = (payload.get("candidates") or [{}])[0].get("finishReason")
            raise LlmError(f"Unexpected Gemini response from {model} (finishReason={reason}): {str(payload)[:500]}") from e
        usage = payload.get("usageMetadata") or {}
        return LlmResult(
            data=data,
            model=payload.get("modelVersion", model),
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        )

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self._min_interval_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _post(self, body: dict[str, Any]) -> tuple[dict[str, Any], str]:
        failures = []
        while self._active < len(self._models):
            model = self._models[self._active]
            try:
                return self._post_model(model, body), model
            except _ModelUnavailable as e:
                failures.append(f"{model}: {e}")
                self._active += 1
        raise LlmError(f"All models unavailable: {failures}")

    def _post_model(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
        attempt = 0
        while attempt < self._max_retries:
            attempt += 1
            request = self._with_thinking(model, body)
            self._throttle()
            try:
                resp = self._session.post(url, json=request, headers={"x-goog-api-key": self._api_key}, timeout=self._timeout_s)
            except OSError as e:  # requests' timeouts and connection errors subclass OSError
                if attempt == self._max_retries:
                    raise _ModelUnavailable(f"request failed after {attempt} attempts: {e}") from e
                self._sleep(self._backoff_s * 2 ** (attempt - 1))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 400 and "thinking" in resp.text.lower() and model not in self._no_thinking:
                self._no_thinking.add(model)  # this model has no thinking config; retry without it
                attempt -= 1
                continue
            if resp.status_code == 404:
                raise _ModelUnavailable(f"404 {resp.text[:200]}")
            if resp.status_code not in RETRYABLE_STATUS:
                raise LlmError(f"Gemini API returned {resp.status_code} for {model}: {resp.text[:500]}")
            if attempt == self._max_retries:
                raise _ModelUnavailable(f"{resp.status_code} {resp.text[:200]}")
            self._sleep(self._backoff_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _with_thinking(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._thinking_level or model in self._no_thinking:
            return body
        config = {**body["generationConfig"], "thinkingConfig": {"thinkingLevel": self._thinking_level}}
        return {**body, "generationConfig": config}
