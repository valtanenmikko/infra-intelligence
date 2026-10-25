"""Client for the public EU TED Search API v3 (no API key required)."""

import re
import time
from collections.abc import Iterable, Iterator
from datetime import date
from typing import Any, Protocol

TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_CPV_RE = re.compile(r"^\d{8}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{3}$")


class HttpSession(Protocol):
    def post(self, url: str, json: dict[str, Any], timeout: float) -> Any: ...


class TedApiError(RuntimeError):
    pass


def build_query(cpv_codes: Iterable[str], country: str, published_from: date) -> str:
    """Build a TED expert query. Inputs are validated because they end up in the query string."""
    codes = list(cpv_codes)
    if not codes:
        raise ValueError("At least one CPV code is required")
    bad = [c for c in codes if not _CPV_RE.match(c)]
    if bad:
        raise ValueError(f"Invalid CPV codes: {bad}")
    if not _COUNTRY_RE.match(country):
        raise ValueError(f"Invalid ISO 3166-1 alpha-3 country code: {country!r}")
    return (
        f"buyer-country={country} "
        f"AND classification-cpv IN ({' '.join(codes)}) "
        f"AND publication-date>={published_from:%Y%m%d}"
    )


class TedClient:
    def __init__(
        self,
        session: HttpSession,
        page_size: int = 250,
        max_retries: int = 3,
        backoff_s: float = 2.0,
        pause_s: float = 0.5,
        timeout_s: float = 120,
        sleep=time.sleep,
    ) -> None:
        if not 1 <= page_size <= 250:
            raise ValueError("page_size must be between 1 and 250")
        self._session = session
        self._page_size = page_size
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._pause_s = pause_s
        self._timeout_s = timeout_s
        self._sleep = sleep

    def search(self, query: str, fields: list[str]) -> Iterator[dict[str, Any]]:
        """Yield every matching notice, following iteration-mode pagination."""
        body: dict[str, Any] = {
            "query": query,
            "fields": fields,
            "limit": self._page_size,
            "paginationMode": "ITERATION",
        }
        while True:
            page = self._post(dict(body))
            notices = page.get("notices") or []
            for notice in notices:
                notice.pop("links", None)  # per-language URL lists, derivable from publication-number
                yield notice
            token = page.get("iterationNextToken")
            if not notices or not token:
                return
            body["iterationNextToken"] = token
            self._sleep(self._pause_s)

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, self._max_retries + 1):
            resp = self._session.post(TED_SEARCH_URL, json=body, timeout=self._timeout_s)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                raise TedApiError(f"TED API returned {resp.status_code}: {resp.text[:500]}")
            self._sleep(self._backoff_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")
