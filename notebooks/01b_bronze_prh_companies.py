# Databricks notebook source
# MAGIC %md
# MAGIC # 01b · Bronze: PRH company register records for tender winners
# MAGIC Looks up every winner business ID (Y-tunnus) found in TED notices from the PRH YTJ open data API and
# MAGIC stores the raw response. Works as a cache: only new IDs, and IDs not refreshed in `REFRESH_AFTER_DAYS`, are fetched.
# MAGIC
# MAGIC IDs missing from the open data (`found = false`) are kept too, so they are not re-queried on every run.
# MAGIC They are typically sole traders, i.e. private persons.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

import json

import requests

from infra_intelligence.config import BRONZE_PRH_TABLE, BRONZE_TED_TABLE
from infra_intelligence.ingest.prh_client import PrhClient, is_business_id

REFRESH_AFTER_DAYS = 90

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {BRONZE_PRH_TABLE} (
        business_id STRING NOT NULL,
        found       BOOLEAN,
        raw_json    STRING,
        _fetched_at TIMESTAMP
    )
    COMMENT 'Raw PRH YTJ open data records for TED winner business IDs'
""")

# COMMAND ----------

candidates = spark.sql(f"""
    WITH ids AS (
        SELECT DISTINCT explode(from_json(raw_json:['winner-identifier'], 'array<string>')) AS business_id
        FROM {BRONZE_TED_TABLE}
    )
    SELECT ids.business_id
    FROM ids LEFT JOIN {BRONZE_PRH_TABLE} p USING (business_id)
    WHERE p.business_id IS NULL OR p._fetched_at < current_timestamp() - INTERVAL {REFRESH_AFTER_DAYS} DAYS
""").collect()
to_fetch = sorted(r.business_id for r in candidates if is_business_id(r.business_id))
print(f"IDs to fetch: {len(to_fetch)} (skipped {len(candidates) - len(to_fetch)} non-Finnish IDs)")

# COMMAND ----------

client = PrhClient(requests.Session())
rows = []
for business_id in to_fetch:
    company = client.get_company(business_id)
    rows.append((business_id, company is not None, json.dumps(company, ensure_ascii=False) if company else None))
print(f"Fetched {len(rows)} | found in open data: {sum(1 for r in rows if r[1])}")

# COMMAND ----------

if rows:
    from pyspark.sql import functions as F

    (
        spark.createDataFrame(rows, "business_id STRING, found BOOLEAN, raw_json STRING")
        .withColumn("_fetched_at", F.current_timestamp())
        .createOrReplaceTempView("prh_batch")
    )
    display(spark.sql(f"""
        MERGE INTO {BRONZE_PRH_TABLE} t
        USING prh_batch s ON t.business_id = s.business_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """))
