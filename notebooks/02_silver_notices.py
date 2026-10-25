# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver: typed infrastructure notices, winners and buyers
# MAGIC Rebuilds the Silver tables from Bronze on every run (full refresh: the data is ~1k rows, so a rebuild is
# MAGIC simpler and safer than incremental logic).
# MAGIC
# MAGIC | Table | Grain | Notes |
# MAGIC |---|---|---|
# MAGIC | `silver.notices` | one notice | infra scope only (main CPV); values, bids, deadlines, regions |
# MAGIC | `silver.notice_winners` | notice × winner Y-tunnus | names resolved by business ID |
# MAGIC | `silver.buyers` | buyer Y-tunnus | one display name per buyer (ELY/Elinvoimakeskus renames merged) |
# MAGIC
# MAGIC Parsing logic lives in `src/infra_intelligence/transform` and is unit tested locally.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

import json
from dataclasses import asdict

from infra_intelligence.config import BRONZE_TED_TABLE, CATALOG, SILVER_BUYERS_TABLE, SILVER_NOTICES_TABLE, SILVER_WINNERS_TABLE
from infra_intelligence.reference import BUYER_NAME_OVERRIDES
from infra_intelligence.transform.names import canonical_names
from infra_intelligence.transform.silver import parse_notice, parse_winners, single_winner_pair

# COMMAND ----------

raw = [json.loads(r.raw_json) for r in spark.table(BRONZE_TED_TABLE).select("raw_json").collect()]
notices = [parse_notice(n) for n in raw]
in_scope = [(r, n) for r, n in zip(raw, notices) if n.infra_category]
print(f"Bronze: {len(raw)} | infra scope by main CPV: {len(in_scope)} | dropped: {len(raw) - len(in_scope)}")

# COMMAND ----------

# Entity resolution by Y-tunnus. Names are linked to IDs only from single-winner notices (see single_winner_pair).
company_names = canonical_names(p for r, _ in in_scope if (p := single_winner_pair(r)))
winners = [w for r, _ in in_scope for w in parse_winners(r, company_names)]

buyer_names = {**canonical_names((n.buyer_id, n.buyer_unit) for _, n in in_scope), **BUYER_NAME_OVERRIDES}
buyers = sorted({n.buyer_id for _, n in in_scope if n.buyer_id})

print(f"Winner rows: {len(winners)} | distinct winners: {len({w.winner_id for w in winners})} "
      f"| without resolved name: {sum(1 for w in winners if not w.winner_name)}")
print(f"Buyers: {len(buyers)}")

# COMMAND ----------

NOTICES_SCHEMA = """
    publication_number STRING, publication_date DATE, notice_type STRING, notice_category STRING,
    title STRING, description STRING, buyer_id STRING, buyer_unit STRING,
    main_cpv STRING, infra_category STRING, cpv_codes ARRAY<STRING>, procedure_type STRING, regions ARRAY<STRING>,
    tender_deadline DATE, total_value_eur DOUBLE, estimated_lot_value_eur DOUBLE, lot_count INT,
    tenders_received_min INT, tenders_received_max INT, lowest_tender_eur DOUBLE, highest_tender_eur DOUBLE,
    is_framework BOOLEAN, winner_ids ARRAY<STRING>, winner_names_raw ARRAY<STRING>, winner_size STRING
"""
WINNERS_SCHEMA = "publication_number STRING, winner_id STRING, winner_name STRING, has_legal_form BOOLEAN, is_single_winner BOOLEAN"
BUYERS_SCHEMA = "buyer_id STRING, buyer_name STRING"


def write(rows, schema, table, comment):
    (spark.createDataFrame(rows, schema).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    spark.sql(f"COMMENT ON TABLE {table} IS '{comment}'")


spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.silver")
write([asdict(n) for _, n in in_scope], NOTICES_SCHEMA, SILVER_NOTICES_TABLE,
      "Finnish infrastructure procurement notices from EU TED, filtered by main CPV")
write([asdict(w) for w in winners], WINNERS_SCHEMA, SILVER_WINNERS_TABLE,
      "Contract award winners by Y-tunnus; names resolved from single-winner notices")
write([(b, buyer_names.get(b)) for b in buyers], BUYERS_SCHEMA, SILVER_BUYERS_TABLE,
      "Contracting authorities by Y-tunnus with one display name")

# COMMAND ----------

# MAGIC %md ## Quality checks

# COMMAND ----------

checks = spark.sql(f"""
    SELECT
      count(*)                                                 AS notices,
      count(*) - count(DISTINCT publication_number)            AS duplicate_ids,
      count_if(publication_date IS NULL)                       AS missing_date,
      count_if(notice_category = 'award')                      AS awards,
      count_if(notice_category = 'award' AND size(winner_ids) = 0) AS awards_without_winner,
      count_if(notice_category = 'award' AND total_value_eur IS NULL) AS awards_without_value
    FROM {SILVER_NOTICES_TABLE}
""").first()
display(spark.createDataFrame([checks]))
assert checks.duplicate_ids == 0, "duplicate publication numbers in Silver"
assert checks.missing_date == 0, "notices without publication date"

# COMMAND ----------

display(spark.sql(f"""
    SELECT infra_category, notice_category, count(*) AS notices
    FROM {SILVER_NOTICES_TABLE} GROUP BY ALL ORDER BY infra_category, notices DESC
"""))
