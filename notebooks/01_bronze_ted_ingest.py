# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze: TED infrastructure notices
# MAGIC Fetches Finnish infrastructure procurement notices from the EU TED Search API
# MAGIC and stores them unmodified (raw JSON) in a Delta table.
# MAGIC
# MAGIC - **First run:** backfill from `BACKFILL_FROM`
# MAGIC - **Later runs:** incremental from the latest stored publication date minus an overlap window
# MAGIC - **Idempotent:** `MERGE` on `publication_number`, so re-runs never create duplicates; changed notices are updated
# MAGIC - **`full_refresh` widget:** re-read everything, e.g. after adding fields to `TED_FIELDS`

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

import json
from datetime import timedelta

import requests
from pyspark.sql import functions as F

from infra_intelligence.config import (
    BACKFILL_FROM,
    BRONZE_TED_TABLE,
    BUYER_COUNTRY,
    CATALOG,
    INCREMENTAL_OVERLAP_DAYS,
    INFRA_CPV_CODES,
    TED_FIELDS,
)
from infra_intelligence.ingest.ted_client import TedClient, build_query

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.bronze")
spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {BRONZE_TED_TABLE} (
        publication_number STRING NOT NULL,
        publication_date   DATE,
        notice_type        STRING,
        raw_json           STRING,
        _ingested_at       TIMESTAMP
    )
    COMMENT 'Raw EU TED notices for Finnish infrastructure CPV codes'
""")

# COMMAND ----------

# full_refresh=true re-reads everything since BACKFILL_FROM, e.g. after adding fields to TED_FIELDS
dbutils.widgets.dropdown("full_refresh", "false", ["false", "true"])
full_refresh = dbutils.widgets.get("full_refresh") == "true"

latest = spark.sql(f"SELECT max(publication_date) AS d FROM {BRONZE_TED_TABLE}").first()["d"]
published_from = latest - timedelta(days=INCREMENTAL_OVERLAP_DAYS) if latest and not full_refresh else BACKFILL_FROM
query = build_query(INFRA_CPV_CODES.keys(), BUYER_COUNTRY, published_from)
print(f"Fetching notices published since {published_from}\n{query}")

# COMMAND ----------

client = TedClient(requests.Session())
rows = [
    (
        n["publication-number"],
        n.get("publication-date", "")[:10],  # e.g. "2024-01-03Z" -> "2024-01-03"
        n.get("notice-type"),
        json.dumps(n, ensure_ascii=False, sort_keys=True),  # stable text so MERGE detects real changes
    )
    for n in client.search(query, TED_FIELDS)
]
print(f"Fetched {len(rows)} notices")

# COMMAND ----------

if rows:
    (
        spark.createDataFrame(rows, "publication_number STRING, publication_date STRING, notice_type STRING, raw_json STRING")
        .withColumn("publication_date", F.to_date("publication_date"))
        .withColumn("_ingested_at", F.current_timestamp())
        .dropDuplicates(["publication_number"])
        .createOrReplaceTempView("ted_batch")
    )
    result = spark.sql(f"""
        MERGE INTO {BRONZE_TED_TABLE} t
        USING ted_batch s ON t.publication_number = s.publication_number
        WHEN MATCHED AND t.raw_json <> s.raw_json THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)
    display(result)

# COMMAND ----------

display(spark.sql(f"""
    SELECT year(publication_date) AS year, notice_type, count(*) AS notices
    FROM {BRONZE_TED_TABLE}
    GROUP BY ALL ORDER BY year, notices DESC
"""))
