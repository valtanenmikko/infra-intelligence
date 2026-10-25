# Databricks notebook source
# MAGIC %md
# MAGIC # 05 · LLM evaluation against withheld ground truth
# MAGIC The extraction prompt never sees TED's structured region (NUTS) or value fields, so they act as labels:
# MAGIC
# MAGIC | Metric | Ground truth |
# MAGIC |---|---|
# MAGIC | `region_*` | TED place of performance (NUTS 3), single-region notices only |
# MAGIC | `value_*` | TED total / estimated value |
# MAGIC
# MAGIC Results are kept per prompt version, so prompt changes can be compared. Region errors are stored for review.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

from dataclasses import asdict

from pyspark.sql import functions as F

from infra_intelligence.config import (
    GOLD_LLM_EVAL_TABLE,
    GOLD_LLM_REGION_ERRORS_TABLE,
    SILVER_LLM_EXTRACTIONS_TABLE,
    SILVER_NOTICES_TABLE,
)
from infra_intelligence.llm.evaluation import region_metrics, value_metrics

# COMMAND ----------

joined = spark.sql(f"""
    SELECT e.prompt_version, e.model, e.publication_number, n.title, e.region AS llm_region, n.regions AS ted_regions,
           e.mentioned_value_eur, coalesce(n.total_value_eur, n.estimated_lot_value_eur) AS ted_value_eur
    FROM {SILVER_LLM_EXTRACTIONS_TABLE} e
    JOIN {SILVER_NOTICES_TABLE} n USING (publication_number)
""").collect()

rows = []
for version in sorted({r.prompt_version for r in joined}):
    subset = [r for r in joined if r.prompt_version == version]
    models = ", ".join(sorted({r.model for r in subset if r.model}))
    metrics = region_metrics((r.llm_region, list(r.ted_regions or [])) for r in subset) + value_metrics(
        (r.mentioned_value_eur, r.ted_value_eur) for r in subset
    )
    rows += [{**asdict(m), "prompt_version": version, "model": models, "notices": len(subset)} for m in metrics]

spark.sql("CREATE SCHEMA IF NOT EXISTS workspace.gold")
(
    spark.createDataFrame(rows, "name STRING, value DOUBLE, n INT, description STRING, prompt_version STRING, model STRING, notices INT")
    .withColumnRenamed("name", "metric")
    .withColumn("evaluated_at", F.current_timestamp())
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(GOLD_LLM_EVAL_TABLE)
)
display(spark.table(GOLD_LLM_EVAL_TABLE).orderBy("prompt_version", "metric"))

# COMMAND ----------

errors = [
    (r.prompt_version, r.publication_number, r.title, r.llm_region, r.ted_regions[0])
    for r in joined
    if r.ted_regions and len(r.ted_regions) == 1 and r.llm_region != r.ted_regions[0]
]
(
    spark.createDataFrame(errors, "prompt_version STRING, publication_number STRING, title STRING, llm_region STRING, ted_region STRING")
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(GOLD_LLM_REGION_ERRORS_TABLE)
)
display(spark.table(GOLD_LLM_REGION_ERRORS_TABLE))
