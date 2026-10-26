# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · LLM: structured facts from tender descriptions
# MAGIC Gemini reads each notice's title, buyer and description and returns schema-validated JSON:
# MAGIC location (municipalities, region), contract period, work types, scope summary, requirements, risks and
# MAGIC price-index terms.
# MAGIC
# MAGIC - **Cached:** each notice is processed once per `PROMPT_VERSION`; changing the prompt re-processes everything.
# MAGIC - **Free-tier friendly:** 10 notices per request, throttled, `max_notices` per run. Open competitions go first.
# MAGIC - **Resumable:** every batch is written immediately, so a quota stop loses nothing.
# MAGIC - **Evaluable:** TED regions and values are withheld from the model (see `05_llm_eval`).

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

from dataclasses import asdict

import requests
from pyspark.sql import functions as F

from infra_intelligence.config import (
    GEMINI_MODEL,
    GEMINI_SECRET_KEY,
    SECRET_SCOPE,
    SILVER_BUYERS_TABLE,
    SILVER_LLM_EXTRACTIONS_TABLE,
    SILVER_NOTICES_TABLE,
)
from infra_intelligence.llm.extraction import EXTRACTION_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_prompt, parse_extractions
from infra_intelligence.llm.gemini_client import GEMINI_BASE_URL, GeminiClient, LlmError

dbutils.widgets.text("max_notices", "400")
dbutils.widgets.text("batch_size", "10")
dbutils.widgets.text("model", GEMINI_MODEL)
max_notices = int(dbutils.widgets.get("max_notices"))
batch_size = int(dbutils.widgets.get("batch_size"))
model = dbutils.widgets.get("model")

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {SILVER_LLM_EXTRACTIONS_TABLE} (
        publication_number     STRING NOT NULL,
        prompt_version         STRING NOT NULL,
        model                  STRING,
        municipalities         ARRAY<STRING>,
        region                 STRING,
        contract_start_year    INT,
        contract_end_year      INT,
        option_years           DOUBLE,
        work_types             ARRAY<STRING>,
        scope_summary          STRING,
        key_requirements       ARRAY<STRING>,
        risks                  ARRAY<STRING>,
        has_price_index_clause BOOLEAN,
        mentioned_value_eur    DOUBLE,
        input_tokens           INT,
        output_tokens          INT,
        _extracted_at          TIMESTAMP
    )
    COMMENT 'LLM-extracted facts per notice and prompt version'
""")

# COMMAND ----------

pending = spark.sql(f"""
    SELECT n.publication_number, n.title, b.buyer_name, n.description
    FROM {SILVER_NOTICES_TABLE} n
    LEFT JOIN {SILVER_BUYERS_TABLE} b USING (buyer_id)
    LEFT ANTI JOIN {SILVER_LLM_EXTRACTIONS_TABLE} e
      ON e.publication_number = n.publication_number AND e.prompt_version = '{PROMPT_VERSION}'
    ORDER BY
      CASE WHEN n.notice_category = 'competition' AND n.tender_deadline >= current_date() THEN 0
           WHEN n.notice_category = 'award' THEN 1 ELSE 2 END,
      n.publication_date DESC
    LIMIT {max_notices}
""").collect()
notices = [r.asDict() for r in pending]
print(f"Pending notices for {PROMPT_VERSION}: {len(notices)} (max {max_notices} per run), model {model}")

# COMMAND ----------

SCHEMA = spark.table(SILVER_LLM_EXTRACTIONS_TABLE).schema


def save(records, result):
    per_record_in = result.input_tokens // max(len(records), 1)
    per_record_out = result.output_tokens // max(len(records), 1)
    rows = [
        {**asdict(r), "prompt_version": PROMPT_VERSION, "model": result.model,
         "input_tokens": per_record_in, "output_tokens": per_record_out, "_extracted_at": None}
        for r in records
    ]
    (
        spark.createDataFrame(rows, SCHEMA)
        .withColumn("_extracted_at", F.current_timestamp())
        .createOrReplaceTempView("llm_batch")
    )
    spark.sql(f"""
        MERGE INTO {SILVER_LLM_EXTRACTIONS_TABLE} t
        USING llm_batch s ON t.publication_number = s.publication_number AND t.prompt_version = s.prompt_version
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)


api_key = dbutils.secrets.get(SECRET_SCOPE, GEMINI_SECRET_KEY)
session = requests.Session()

# Preflight: fail fast with a clear message if the key or model name is wrong
check = session.get(f"{GEMINI_BASE_URL}/models/{model}", headers={"x-goog-api-key": api_key}, timeout=30)
if check.status_code != 200:
    raise RuntimeError(f"Gemini model check failed ({check.status_code}): {check.text[:300]}")

client = GeminiClient(session, api_key, model)
saved, failed_batches, tokens_in, tokens_out = 0, 0, 0, 0
errors = []
for start in range(0, len(notices), batch_size):
    batch = notices[start:start + batch_size]
    ids = [n["publication_number"] for n in batch]
    try:
        result = client.generate_json(build_prompt(batch), EXTRACTION_SCHEMA, system=SYSTEM_PROMPT)
        records = parse_extractions(result.data, ids)
    except (LlmError, ValueError) as e:
        failed_batches += 1
        errors.append(str(e)[:300])
        print(f"Batch {start // batch_size + 1} failed: {e}")
        if failed_batches >= 3:
            print("Stopping after 3 failed batches (likely quota); the rest is picked up next run.")
            break
        continue
    if records:
        save(records, result)
    saved += len(records)
    tokens_in += result.input_tokens
    tokens_out += result.output_tokens
    print(f"Batch {start // batch_size + 1}: {len(records)}/{len(batch)} saved")

print(f"Saved {saved} | failed batches {failed_batches} | tokens in {tokens_in:,} out {tokens_out:,}")
if notices and saved == 0:
    raise RuntimeError(f"No extractions saved from {len(notices)} pending notices. Errors: {errors}")

# COMMAND ----------

display(spark.sql(f"""
    SELECT prompt_version, model, count(*) AS notices, count(region) AS with_region,
           count(contract_end_year) AS with_period, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens
    FROM {SILVER_LLM_EXTRACTIONS_TABLE} GROUP BY ALL
"""))
