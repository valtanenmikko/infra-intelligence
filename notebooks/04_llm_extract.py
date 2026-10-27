# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · LLM: structured facts from tender descriptions
# MAGIC Gemini reads each notice's title, buyer and description and returns schema-validated JSON:
# MAGIC location (municipalities, region), contract period, work types, scope summary, requirements, risks and
# MAGIC price-index terms.
# MAGIC
# MAGIC - **Cached:** each notice is processed once per `PROMPT_VERSION`; changing the prompt re-processes everything.
# MAGIC - **Free-tier friendly:** Gemini Flash Lite (500 requests/day) with an automatic fallback model, 10 notices
# MAGIC   per request. `scope=priority` limits the run to open competitions, awards lacking a region and an
# MAGIC   evaluation sample, for when only a small quota is available.
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
    EXTRACTION_MODELS,
    EXTRACTION_RPM,
    GEMINI_SECRET_KEY,
    SECRET_SCOPE,
    SILVER_BUYERS_TABLE,
    SILVER_LLM_EXTRACTIONS_TABLE,
    SILVER_NOTICES_TABLE,
)
from infra_intelligence.llm.extraction import EXTRACTION_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_prompt, parse_extractions
from infra_intelligence.llm.gemini_client import GeminiClient, LlmError

# Defaults process everything pending (~82 requests on the first run, a few per day after that).
dbutils.widgets.text("max_notices", "1000")
dbutils.widgets.text("batch_size", "10")
dbutils.widgets.text("eval_sample", "50")
dbutils.widgets.dropdown("scope", "all", ["priority", "all"])
dbutils.widgets.text("models", ",".join(EXTRACTION_MODELS))
max_notices = int(dbutils.widgets.get("max_notices"))
batch_size = int(dbutils.widgets.get("batch_size"))
eval_sample = int(dbutils.widgets.get("eval_sample"))
scope = dbutils.widgets.get("scope")
models = [m.strip() for m in dbutils.widgets.get("models").split(",") if m.strip()]
model = models[0]

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

# With scope=priority the LLM is spent only where it adds value:
#   0 = open competitions (input for go/no-go)
#   1 = awards without a TED region (LLM region enables regional history)
#   2 = a fixed random sample of single-region notices (evaluation against the withheld TED region)
eval_done = spark.sql(f"""
    SELECT count(*) AS n FROM {SILVER_LLM_EXTRACTIONS_TABLE} e JOIN {SILVER_NOTICES_TABLE} n USING (publication_number)
    WHERE e.prompt_version = '{PROMPT_VERSION}' AND size(n.regions) = 1
""").first()["n"]
eval_remaining = max(eval_sample - eval_done, 0)

pending = spark.sql(f"""
    WITH candidates AS (
      SELECT n.publication_number, n.title, b.buyer_name, n.description,
             CASE WHEN n.notice_category = 'competition' AND n.tender_deadline >= current_date() THEN 0
                  WHEN n.notice_category = 'award' AND size(n.regions) = 0 THEN 1
                  WHEN size(n.regions) = 1 THEN 2
                  ELSE 3 END AS priority
      FROM {SILVER_NOTICES_TABLE} n
      LEFT JOIN {SILVER_BUYERS_TABLE} b USING (buyer_id)
      LEFT ANTI JOIN {SILVER_LLM_EXTRACTIONS_TABLE} e
        ON e.publication_number = n.publication_number AND e.prompt_version = '{PROMPT_VERSION}'
    ),
    ranked AS (
      SELECT *, row_number() OVER (PARTITION BY priority ORDER BY xxhash64(publication_number)) AS rn
      FROM candidates
    )
    SELECT publication_number, title, buyer_name, description, priority
    FROM ranked
    WHERE '{scope}' = 'all' OR priority IN (0, 1) OR (priority = 2 AND rn <= {eval_remaining})
    ORDER BY priority, rn
    LIMIT {max_notices}
""").collect()
notices = [r.asDict() for r in pending]
by_priority = {p: sum(1 for n in notices if n["priority"] == p) for p in range(4)}
print(f"Pending for {PROMPT_VERSION} (scope={scope}, model {model}): {len(notices)} {by_priority}")

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


client = GeminiClient(requests.Session(), dbutils.secrets.get(SECRET_SCOPE, GEMINI_SECRET_KEY), models,
                      requests_per_minute=EXTRACTION_RPM)

# Preflight: a tiny real generation call (with the client's retries for temporary 429/503). Model metadata
# can exist even when generation is refused, e.g. for a model withdrawn for new users.
try:
    client.generate_json("Reply with ok=true.", {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}})
except LlmError as e:
    raise RuntimeError(f"Gemini preflight failed for {models}: {e}") from e
print(f"Using model {client.active_model}")

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
