-- Databricks notebook source
-- MAGIC %md
-- MAGIC # 03 · Gold: business-ready market tables
-- MAGIC Each table answers one business question for an infrastructure contractor's bid and strategy team.
-- MAGIC
-- MAGIC | Table | Question |
-- MAGIC |---|---|
-- MAGIC | `award_facts`, `award_winners` | Shared base: one row per contract award / per award × winner |
-- MAGIC | `market_share` | Who wins, how often and for how much, by year and category? |
-- MAGIC | `competition` | How many bids do tenders attract? Where is competition thin? |
-- MAGIC | `competition_by_region` | Same by region |
-- MAGIC | `buyer_profiles` | What does each buyer procure, and does one contractor dominate? |
-- MAGIC | `open_tenders` | Which tenders are open now, and what does history say about them? |
-- MAGIC | `price_spread` | How far apart are the lowest and highest bids? |
-- MAGIC | `monthly_activity` | Market activity over time |
-- MAGIC
-- MAGIC **Rules**
-- MAGIC - Contract values are attributed to a company only for single-winner awards; framework values cannot be split.
-- MAGIC - Winners that are not registered companies (likely private persons) are grouped as *Muut toimijat*.
-- MAGIC - Bid counts: `bids_received` = most contested lot. Single-bid / low-competition flags use it, so a
-- MAGIC   multi-lot tender only counts as low competition when no lot got more bids (lot-level counts are not
-- MAGIC   reliably linked to lots in the source).

-- COMMAND ----------

CREATE SCHEMA IF NOT EXISTS workspace.gold;

-- COMMAND ----------

-- Notices with the latest LLM extraction. effective_regions = TED NUTS regions, or the LLM-inferred region when
-- TED only says "Finland" (typical for state road maintenance contracts, where the place is only in the title).
CREATE OR REPLACE TABLE workspace.gold.notices_enriched
COMMENT 'Silver notices + latest LLM extraction; effective_regions falls back to the LLM region'
AS WITH llm AS (
  SELECT * FROM workspace.silver.llm_extractions
  QUALIFY row_number() OVER (PARTITION BY publication_number ORDER BY _extracted_at DESC) = 1
)
SELECT
  n.*,
  CASE WHEN size(n.regions) > 0 THEN n.regions
       WHEN l.region IS NOT NULL THEN array(l.region)
       ELSE n.regions END                              AS effective_regions,
  size(n.regions) = 0 AND l.region IS NOT NULL        AS region_from_llm,
  l.municipalities,
  l.contract_start_year,
  l.contract_end_year,
  l.option_years,
  l.work_types,
  l.scope_summary,
  l.key_requirements,
  l.risks,
  l.has_price_index_clause,
  l.prompt_version                                    AS llm_prompt_version
FROM workspace.silver.notices n
LEFT JOIN llm l USING (publication_number);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.award_facts
COMMENT 'One row per infrastructure contract award notice'
AS SELECT
  n.publication_number,
  n.publication_date,
  year(n.publication_date)        AS year,
  n.infra_category,
  n.title,
  n.buyer_id,
  b.buyer_name,
  n.effective_regions             AS regions,
  n.is_framework,
  size(n.winner_ids)              AS winner_count,
  n.total_value_eur               AS contract_value_eur,
  n.tenders_received_max          AS bids_received,
  n.price_share,
  n.tenders_received_max <= 1     AS is_single_bid,
  n.tenders_received_max <= 2     AS is_low_competition,
  n.lowest_tender_eur,
  n.highest_tender_eur
FROM workspace.gold.notices_enriched n
LEFT JOIN workspace.silver.buyers b USING (buyer_id)
WHERE n.notice_category = 'award';

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.award_winners
COMMENT 'Award x winner; names of likely private persons replaced with Muut toimijat'
AS SELECT
  w.publication_number,
  CASE WHEN w.is_registered_company THEN w.winner_name ELSE 'Muut toimijat' END AS company,
  w.is_registered_company,
  w.is_single_winner,
  CASE WHEN w.is_registered_company THEN c.industry END AS company_industry
FROM workspace.silver.notice_winners w
LEFT JOIN workspace.silver.companies c ON c.business_id = w.winner_id;

-- COMMAND ----------

-- share_of_awards = awards won / all awards in the slice (the figure a reader expects; can sum above 1 because a
-- framework has several winners). share_of_wins = share of winner rows (sums to exactly 1; used for the check).
CREATE OR REPLACE TABLE workspace.gold.market_share
COMMENT 'Wins and single-winner contract value per company; year_label/category_label = Kaikki for totals'
AS WITH awards_in_slice AS (
  SELECT
    coalesce(CAST(year AS STRING), 'Kaikki') AS year_label,
    coalesce(infra_category, 'Kaikki')       AS category_label,
    count(*)                                 AS slice_awards
  FROM workspace.gold.award_facts
  GROUP BY GROUPING SETS ((year, infra_category), (year), (infra_category), ())
),
wins AS (
  SELECT a.year, a.infra_category, w.company, a.publication_number,
         CASE WHEN w.is_single_winner THEN a.contract_value_eur END AS won_value_eur
  FROM workspace.gold.award_facts a
  JOIN workspace.gold.award_winners w USING (publication_number)
),
agg AS (
  SELECT
    coalesce(CAST(year AS STRING), 'Kaikki') AS year_label,
    coalesce(infra_category, 'Kaikki')       AS category_label,
    company,
    count(DISTINCT publication_number)       AS wins,
    sum(won_value_eur)                       AS won_value_eur
  FROM wins
  GROUP BY GROUPING SETS ((year, infra_category, company), (year, company), (infra_category, company), (company))
)
SELECT
  agg.*,
  s.slice_awards,
  agg.wins / s.slice_awards                   AS share_of_awards,
  agg.wins / sum(agg.wins) OVER w             AS share_of_wins,
  agg.won_value_eur / sum(agg.won_value_eur) OVER w AS share_of_value,
  rank() OVER (PARTITION BY agg.year_label, agg.category_label ORDER BY agg.wins DESC, agg.won_value_eur DESC NULLS LAST) AS rank
FROM agg
JOIN awards_in_slice s USING (year_label, category_label)
WINDOW w AS (PARTITION BY agg.year_label, agg.category_label);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.competition
COMMENT 'Bid counts per category and year; Kaikki = total'
AS SELECT
  coalesce(infra_category, 'Kaikki')                    AS category_label,
  coalesce(CAST(year AS STRING), 'Kaikki')              AS year_label,
  count(*)                                              AS awards,
  count(bids_received)                                  AS awards_with_bid_data,
  round(avg(bids_received), 1)                          AS avg_bids,
  median(bids_received)                                 AS median_bids,
  avg(CAST(is_single_bid AS INT))                       AS share_single_bid,
  avg(CAST(is_low_competition AS INT))                  AS share_low_competition
FROM workspace.gold.award_facts
GROUP BY GROUPING SETS ((infra_category, year), (infra_category), (year), ());

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.competition_by_region
COMMENT 'Awards, bids and contract value per region (an award can cover several regions)'
AS SELECT
  coalesce(region, 'Ei aluetietoa')                     AS region,
  count(*)                                              AS awards,
  round(avg(bids_received), 1)                          AS avg_bids,
  avg(CAST(is_low_competition AS INT))                  AS share_low_competition,
  sum(CASE WHEN winner_count = 1 THEN contract_value_eur END) AS single_winner_value_eur
FROM workspace.gold.award_facts
LATERAL VIEW OUTER explode(regions) r AS region
GROUP BY 1;

-- COMMAND ----------

-- Does the weight of price in the award criteria change how many bids a tender attracts?
CREATE OR REPLACE TABLE workspace.gold.competition_by_criteria
COMMENT 'Bids and low-competition share by the price share of the award criteria'
AS SELECT
  CASE WHEN price_share >= 1   THEN 'Pelkkä hinta'
       WHEN price_share >= 0.7 THEN 'Hinta 70–99 %'
       WHEN price_share >= 0.5 THEN 'Hinta 50–69 %'
       ELSE 'Hinta alle 50 %' END                         AS criteria_band,
  CASE WHEN price_share >= 1 THEN 1 WHEN price_share >= 0.7 THEN 2 WHEN price_share >= 0.5 THEN 3 ELSE 4 END AS band_order,
  count(*)                                              AS awards,
  round(avg(bids_received), 1)                          AS avg_bids,
  avg(CAST(is_low_competition AS INT))                  AS share_low_competition
FROM workspace.gold.award_facts
WHERE price_share IS NOT NULL AND bids_received IS NOT NULL
GROUP BY 1, 2;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.buyer_profiles
COMMENT 'Per buyer: procurement volume, main category, competition and the most frequent winners'
AS WITH notices AS (
  SELECT b.buyer_name, n.*
  FROM workspace.silver.notices n JOIN workspace.silver.buyers b USING (buyer_id)
),
stats AS (
  SELECT
    buyer_name,
    count(*)                                            AS notices,
    count_if(notice_category = 'competition')           AS competitions,
    count_if(notice_category = 'award')                 AS awards,
    sum(CASE WHEN notice_category = 'award' THEN total_value_eur END) AS awarded_value_eur,
    mode(infra_category)                                AS main_category,
    round(avg(CASE WHEN notice_category = 'award' THEN tenders_received_max END), 1) AS avg_bids
  FROM notices GROUP BY buyer_name
),
winner_counts AS (
  SELECT a.buyer_name, w.company, count(*) AS wins
  FROM workspace.gold.award_facts a JOIN workspace.gold.award_winners w USING (publication_number)
  WHERE w.is_registered_company
  GROUP BY ALL
),
top_winners AS (
  SELECT
    buyer_name,
    slice(transform(array_sort(collect_list(struct(-wins AS neg, company, wins))), x -> named_struct('company', x.company, 'wins', x.wins)), 1, 3) AS top_winners,
    max(wins) AS top_winner_wins
  FROM winner_counts GROUP BY buyer_name
)
SELECT s.*, t.top_winners, round(t.top_winner_wins / nullif(s.awards, 0), 2) AS top_winner_share
FROM stats s LEFT JOIN top_winners t USING (buyer_name);

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.open_tenders
COMMENT 'Competitions open today with history: same buyer + category, and same category + region'
AS WITH open AS (
  SELECT n.* EXCEPT (regions), n.effective_regions AS regions, b.buyer_name
  FROM workspace.gold.notices_enriched n LEFT JOIN workspace.silver.buyers b USING (buyer_id)
  WHERE n.notice_category = 'competition' AND n.tender_deadline >= current_date()
    -- A result notice for the same procedure means it was awarded or cancelled, even if the deadline is ahead
    AND NOT EXISTS (SELECT 1 FROM workspace.gold.notices_enriched r
                    WHERE r.procedure_id = n.procedure_id AND r.notice_category = 'award'
                      AND r.publication_date >= n.publication_date)
  -- Buyers sometimes republish the same competition as a new notice; keep only the latest one per procedure
  QUALIFY row_number() OVER (PARTITION BY coalesce(n.procedure_id, concat_ws('|', n.buyer_id, n.title, n.tender_deadline))
                             ORDER BY n.publication_date DESC, n.publication_number DESC) = 1
),
-- Past awards comparable to each open tender, tagged by how they match. Regional history matters for
-- state road maintenance: all ELY centres share one buyer ID, so buyer history alone is nationwide.
comparable AS (
  SELECT o.publication_number AS open_id, 'buyer' AS scope, a.publication_number, a.bids_received
  FROM open o JOIN workspace.gold.award_facts a ON a.buyer_id = o.buyer_id AND a.infra_category = o.infra_category
  UNION ALL
  SELECT o.publication_number, 'region', a.publication_number, a.bids_received
  FROM open o JOIN workspace.gold.award_facts a ON a.infra_category = o.infra_category AND arrays_overlap(a.regions, o.regions)
),
history AS (
  SELECT open_id, scope, count(*) AS past_awards, count(bids_received) AS past_bid_awards,
         round(avg(bids_received), 1) AS past_avg_bids
  FROM comparable GROUP BY ALL
),
past_winners AS (
  SELECT open_id, scope,
         slice(transform(array_sort(collect_list(struct(-wins AS neg, company, wins))), x -> named_struct('company', x.company, 'wins', x.wins)), 1, 3) AS top_winners
  FROM (
    SELECT c.open_id, c.scope, w.company, count(*) AS wins
    FROM comparable c JOIN workspace.gold.award_winners w ON w.publication_number = c.publication_number
    WHERE w.is_registered_company
    GROUP BY ALL
  )
  GROUP BY ALL
),
category_bids AS (
  SELECT category_label AS infra_category, avg_bids AS category_avg_bids
  FROM workspace.gold.competition WHERE year_label = 'Kaikki'
)
SELECT
  o.publication_number,
  o.title,
  o.buyer_name,
  o.infra_category,
  o.regions,
  o.region_from_llm,
  o.municipalities,
  o.procedure_type,
  o.lot_count,
  o.tender_deadline,
  datediff(o.tender_deadline, current_date())            AS days_left,
  coalesce(o.total_value_eur, o.estimated_lot_value_eur) AS estimated_value_eur,
  o.contract_start_year,
  o.contract_end_year,
  o.option_years,
  o.work_types,
  o.scope_summary,
  o.key_requirements,
  o.risks,
  o.has_price_index_clause,
  o.price_share,
  o.award_criteria,
  o.description,
  coalesce(hb.past_awards, 0)                            AS buyer_past_awards,
  hb.past_avg_bids                                       AS buyer_past_avg_bids,
  coalesce(hb.past_bid_awards, 0)                        AS buyer_past_bid_awards,
  wb.top_winners                                         AS buyer_past_top_winners,
  coalesce(hr.past_awards, 0)                            AS region_past_awards,
  hr.past_avg_bids                                       AS region_past_avg_bids,
  wr.top_winners                                         AS region_past_top_winners,
  c.category_avg_bids,
  concat('https://ted.europa.eu/fi/notice/-/detail/', o.publication_number) AS ted_url
FROM open o
LEFT JOIN history hb      ON hb.open_id = o.publication_number AND hb.scope = 'buyer'
LEFT JOIN past_winners wb ON wb.open_id = o.publication_number AND wb.scope = 'buyer'
LEFT JOIN history hr      ON hr.open_id = o.publication_number AND hr.scope = 'region'
LEFT JOIN past_winners wr ON wr.open_id = o.publication_number AND wr.scope = 'region'
LEFT JOIN category_bids c ON c.infra_category = o.infra_category;

-- COMMAND ----------

-- Backtest of the go/no-go history factors: each past award is predicted from awards published before it only.
-- bids_mae_*: mean absolute error of the expected bid count. "shrunk" is the method used for open tenders
-- (buyer average pulled toward the category average with weight k = 3, bid_assessment.SHRINKAGE_K).
-- incumbent_rewin_rate: how often a winner of the previous comparable award (same buyer, category and region)
-- wins again, vs the win rate of a random bidder (1 / bids).
CREATE OR REPLACE TABLE workspace.gold.bid_factor_backtest
COMMENT 'Out-of-time accuracy of the bid-count forecast and the incumbent re-win rate'
AS WITH a AS (SELECT * FROM workspace.gold.award_facts WHERE bids_received IS NOT NULL),
pred AS (
  SELECT t.bids_received AS actual,
    (SELECT avg(h.bids_received) FROM a h WHERE h.publication_date < t.publication_date
       AND h.infra_category = t.infra_category) AS cat,
    (SELECT avg(h.bids_received) FROM a h WHERE h.publication_date < t.publication_date
       AND h.infra_category = t.infra_category AND h.buyer_id = t.buyer_id) AS buy,
    (SELECT count(*) FROM a h WHERE h.publication_date < t.publication_date
       AND h.infra_category = t.infra_category AND h.buyer_id = t.buyer_id) AS buy_n,
    (SELECT avg(h.bids_received) FROM a h WHERE h.publication_date < t.publication_date
       AND h.infra_category = t.infra_category AND arrays_overlap(h.regions, t.regions)) AS reg
  FROM a t
),
awards AS (
  SELECT f.publication_number, f.publication_date, f.buyer_id, f.infra_category, f.regions, f.bids_received,
         collect_set(w.winner_id) AS winners
  FROM workspace.gold.award_facts f JOIN workspace.silver.notice_winners w USING (publication_number)
  WHERE NOT f.is_framework AND w.winner_id IS NOT NULL
  GROUP BY ALL
),
incumbent AS (
  SELECT t.winners, t.bids_received,
    (SELECT max_by(h.winners, h.publication_date) FROM awards h WHERE h.publication_date < t.publication_date
       AND h.buyer_id = t.buyer_id AND h.infra_category = t.infra_category
       AND arrays_overlap(h.regions, t.regions)) AS previous_winners
  FROM awards t
)
SELECT 'bids_mae_shrunk' AS metric, round(avg(abs((coalesce(buy * buy_n, 0) + 3 * cat) / (buy_n + 3) - actual)), 2) AS value,
       count(*) AS n FROM pred WHERE cat IS NOT NULL
UNION ALL
SELECT 'bids_mae_category', round(avg(abs(cat - actual)), 2), count(*) FROM pred WHERE cat IS NOT NULL
UNION ALL
SELECT 'bids_mae_region_buyer_category', round(avg(abs(coalesce(reg, buy, cat) - actual)), 2), count(*)
FROM pred WHERE cat IS NOT NULL
UNION ALL
SELECT 'incumbent_rewin_rate', round(avg(CASE WHEN arrays_overlap(winners, previous_winners) THEN 1.0 ELSE 0 END), 2),
       count(*) FROM incumbent WHERE previous_winners IS NOT NULL
UNION ALL
SELECT 'random_bidder_win_rate', round(avg(1.0 / greatest(bids_received, 1)), 2), count(*)
FROM incumbent WHERE previous_winners IS NOT NULL AND bids_received IS NOT NULL;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.price_spread
COMMENT 'Lowest vs highest bid for non-framework awards that report both; implausible ratios excluded'
AS SELECT
  publication_number, title, infra_category, buyer_name, bids_received,
  lowest_tender_eur, highest_tender_eur, contract_value_eur,
  round((highest_tender_eur - lowest_tender_eur) / lowest_tender_eur, 3) AS spread_ratio
FROM workspace.gold.award_facts
WHERE lowest_tender_eur > 0
  AND highest_tender_eur >= lowest_tender_eur
  -- A highest bid over 5x the lowest is almost certainly a unit or lot mix-up in the source data
  AND highest_tender_eur <= 5 * lowest_tender_eur
  AND NOT is_framework;

-- COMMAND ----------

CREATE OR REPLACE TABLE workspace.gold.monthly_activity
COMMENT 'Competitions, awards and awarded value per month and category'
AS SELECT
  date_trunc('month', publication_date)                AS month,
  infra_category,
  count_if(notice_category = 'competition')            AS competitions,
  count_if(notice_category = 'award')                  AS awards,
  sum(CASE WHEN notice_category = 'award' THEN total_value_eur END) AS awarded_value_eur
FROM workspace.silver.notices
GROUP BY ALL;

-- COMMAND ----------

-- MAGIC %md ## Quality checks

-- COMMAND ----------

SELECT
  assert_true(count_if(NOT is_registered_company AND company <> 'Muut toimijat') = 0,
              'name of a non-registered winner leaked into Gold')                                      AS no_name_leak
FROM workspace.gold.award_winners;

-- COMMAND ----------

SELECT assert_true(max(abs(total - 1)) < 1e-9, 'market shares do not sum to 1') AS shares_sum_to_one
FROM (SELECT sum(share_of_wins) AS total FROM workspace.gold.market_share GROUP BY year_label, category_label);

-- COMMAND ----------

SELECT assert_true(count(*) = count(DISTINCT publication_number), 'duplicate awards') AS unique_awards
FROM workspace.gold.award_facts;

-- COMMAND ----------

SELECT * FROM workspace.gold.market_share WHERE year_label = 'Kaikki' AND category_label = 'Kaikki' ORDER BY rank LIMIT 15;
