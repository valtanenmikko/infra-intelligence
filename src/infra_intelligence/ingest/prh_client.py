"""Client for the Finnish Patent and Registration Office (PRH) YTJ open data API v3 (no API key required)."""

import re
import time
from typing import Any

from infra_intelligence.ingest.ted_client import RETRYABLE_STATUS

PRH_COMPANIES_URL = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"

_BUSINESS_ID_RE = re.compile(r"^\d{7}-\d$")
_FI_VAT_RE = re.compile(r"^FI(\d{7})(\d)$")


def normalize_business_id(value: str) -> str:
    """Convert a Finnish VAT number to the Y-tunnus it contains ("FI21630263" -> "2163026-3").

    Buyers report winners with either format; other values are returned trimmed but unchanged.
    """
    value = value.strip()
    m = _FI_VAT_RE.match(value.replace(" ", ""))
    return f"{m.group(1)}-{m.group(2)}" if m else value


class PrhApiError(RuntimeError):
    pass


def is_business_id(value: str | None) -> bool:
    """True for a Finnish business ID (Y-tunnus), e.g. "1007822-3". Foreign VAT numbers are excluded."""
    return bool(value and _BUSINESS_ID_RE.match(value))


class PrhClient:
    def __init__(
        self,
        session: Any,
        max_retries: int = 3,
        backoff_s: float = 2.0,
        pause_s: float = 0.2,
        timeout_s: float = 30,
        sleep=time.sleep,
    ) -> None:
        self._session = session
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._pause_s = pause_s
        self._timeout_s = timeout_s
        self._sleep = sleep

    def get_company(self, business_id: str) -> dict[str, Any] | None:
        """Return the raw company record, or None if the ID is not in the open data.

        Sole traders (private persons) are typically not published as open data, so None is expected for them.
        """
        if not is_business_id(business_id):
            raise ValueError(f"Invalid business ID: {business_id!r}")
        for attempt in range(1, self._max_retries + 1):
            resp = self._session.get(PRH_COMPANIES_URL, params={"businessId": business_id}, timeout=self._timeout_s)
            if resp.status_code == 200:
                self._sleep(self._pause_s)
                companies = resp.json().get("companies") or []
                return companies[0] if companies else None
            if resp.status_code == 404:
                return None
            if resp.status_code not in RETRYABLE_STATUS or attempt == self._max_retries:
                raise PrhApiError(f"PRH API returned {resp.status_code}: {resp.text[:500]}")
            self._sleep(self._backoff_s * 2 ** (attempt - 1))
        raise AssertionError("unreachable")
