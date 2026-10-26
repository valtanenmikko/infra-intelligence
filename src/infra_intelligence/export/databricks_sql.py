"""Minimal client for the Databricks SQL Statement Execution API (used outside Databricks, e.g. in CI)."""

import time
from typing import Any

TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELED", "CLOSED"}


class SqlError(RuntimeError):
    pass


class DatabricksSql:
    def __init__(self, session: Any, host: str, token: str, warehouse_id: str,
                 poll_s: float = 3.0, max_polls: int = 100, sleep=time.sleep) -> None:
        if not (host and token and warehouse_id):
            raise ValueError("host, token and warehouse_id are required")
        self._session = session
        self._base = host.rstrip("/") + "/api/2.0/sql/statements"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._warehouse_id = warehouse_id
        self._poll_s = poll_s
        self._max_polls = max_polls
        self._sleep = sleep

    def query(self, statement: str) -> list[dict[str, Any]]:
        """Run a statement and return rows as dicts keyed by column name (values as JSON strings/None)."""
        body = {"warehouse_id": self._warehouse_id, "statement": statement, "wait_timeout": "30s",
                "format": "JSON_ARRAY", "disposition": "INLINE"}
        r = self._check(self._session.post(self._base, json=body, headers=self._headers, timeout=60))
        for _ in range(self._max_polls):
            if r["status"]["state"] in TERMINAL_STATES:
                break
            self._sleep(self._poll_s)
            r = self._check(self._session.get(f"{self._base}/{r['statement_id']}", headers=self._headers, timeout=60))
        state = r["status"]["state"]
        if state != "SUCCEEDED":
            raise SqlError(f"Statement {state}: {(r['status'].get('error') or {}).get('message', '')[:500]}")
        columns = [c["name"] for c in r["manifest"]["schema"]["columns"]]
        rows = list((r.get("result") or {}).get("data_array") or [])
        for chunk in range(1, r["manifest"].get("total_chunk_count", 1)):
            part = self._check(self._session.get(f"{self._base}/{r['statement_id']}/result/chunks/{chunk}",
                                                 headers=self._headers, timeout=60))
            rows += part.get("data_array") or []
        return [dict(zip(columns, row)) for row in rows]

    @staticmethod
    def _check(resp: Any) -> dict[str, Any]:
        if resp.status_code != 200:
            raise SqlError(f"Databricks API returned {resp.status_code}: {resp.text[:500]}")
        return resp.json()
