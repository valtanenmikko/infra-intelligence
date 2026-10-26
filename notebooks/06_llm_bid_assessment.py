# Databricks notebook source
# MAGIC %md
# MAGIC # 06 · LLM: go/no-go assessment for open tenders
# MAGIC For each open competition in `gold.open_tenders`, Gemini rates **fit** to an example bidder profile and
# MAGIC **risk**, with reasons. **Competition** comes from historical bid counts, and the score (0–100) and
# MAGIC recommendation from a fixed formula in `bid_assessment.py`, so the LLM never does the arithmetic.
# MAGIC
# MAGIC Each tender is assessed once per `PROMPT_VERSION`, five tenders per request (free tier: 20 requests/day).

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

from dataclasses import asdict

import requests
from pyspark.sql import functions as F

from infra_intelligence.config import GEMINI_MODEL, GEMINI_SECRET_KEY, SECRET_SCOPE
from infra_intelligence.llm.bid_assessment import (
    ASSESSMENT_SCHEMA,
    BATCH_SIZE,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_prompt,
    parse_assessments,
)
from infra_intelligence.llm.gemini_client import GeminiClient, LlmError

TABLE = "workspace.gold.bid_assessments"
dbutils.widgets.text("model", GEMINI_MODEL)
model = dbutils.widgets.get("model")

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {TABLE} (
        publication_number     STRING NOT NULL,
        prompt_version         STRING NOT NULL,
        model                  STRING,
        fit                    INT,
        fit_reason             STRING,
        risk                   INT,
        risk_reason            STRING,
        competition            INT,
        expected_bids          DOUBLE,
        score                  INT,
        recommendation         STRING,
        summary                STRING,
        questions_for_bid_team ARRAY<STRING>,
        _assessed_at           TIMESTAMP
    )
    COMMENT 'Go/no-go assessments of open tenders for the example bidder profile'
""")

tenders = [
    r.asDict(recursive=True)
    for r in spark.sql(f"""
        SELECT o.* FROM workspace.gold.open_tenders o
        LEFT ANTI JOIN {TABLE} a ON a.publication_number = o.publication_number AND a.prompt_version = '{PROMPT_VERSION}'
        ORDER BY o.tender_deadline
    """).collect()
]
print(f"Open tenders to assess: {len(tenders)}")

# COMMAND ----------

client = GeminiClient(requests.Session(), dbutils.secrets.get(SECRET_SCOPE, GEMINI_SECRET_KEY), model,
                      requests_per_minute=4)
rows, errors = [], []
for start in range(0, len(tenders), BATCH_SIZE):
    batch = tenders[start:start + BATCH_SIZE]
    try:
        result = client.generate_json(build_prompt(batch), ASSESSMENT_SCHEMA, system=SYSTEM_PROMPT)
        assessments = parse_assessments(result.data, batch)
    except (LlmError, ValueError) as e:
        errors.append(str(e)[:300])
        print(f"Batch {start // BATCH_SIZE + 1} failed: {e}")
        continue
    for a in assessments:
        rows.append({**asdict(a), "prompt_version": PROMPT_VERSION, "model": result.model, "_assessed_at": None})
        print(f"{a.publication_number}: {a.recommendation} ({a.score})")

if tenders and not rows:
    raise RuntimeError(f"No assessments saved from {len(tenders)} open tenders. Errors: {errors}")

# COMMAND ----------

if rows:
    (
        spark.createDataFrame(rows, spark.table(TABLE).schema)
        .withColumn("_assessed_at", F.current_timestamp())
        .createOrReplaceTempView("assessment_batch")
    )
    spark.sql(f"""
        MERGE INTO {TABLE} t
        USING assessment_batch s ON t.publication_number = s.publication_number AND t.prompt_version = s.prompt_version
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

display(spark.sql(f"""
    SELECT o.title, o.tender_deadline, a.recommendation, a.score, a.fit, a.competition, a.risk, a.summary
    FROM {TABLE} a JOIN workspace.gold.open_tenders o USING (publication_number)
    WHERE a.prompt_version = '{PROMPT_VERSION}'
    ORDER BY a.score DESC
"""))
