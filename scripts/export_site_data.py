"""Export Gold tables to site/data/site.json.

Usage: DATABRICKS_HOST=... DATABRICKS_TOKEN=... DATABRICKS_WAREHOUSE_ID=... python scripts/export_site_data.py
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from infra_intelligence.export.databricks_sql import DatabricksSql  # noqa: E402
from infra_intelligence.export.site_data import build_site_data  # noqa: E402


def main() -> None:
    sql = DatabricksSql(
        requests.Session(),
        host=os.environ.get("DATABRICKS_HOST", ""),
        token=os.environ.get("DATABRICKS_TOKEN", ""),
        warehouse_id=os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
    )
    data = build_site_data(sql, date.today())
    out = ROOT / "site" / "data" / "site.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}: {len(data['open_tenders'])} open tenders, {len(data['market_share'])} market rows")


if __name__ == "__main__":
    main()
