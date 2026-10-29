"""Build the demo site's data file (site/data/site.json) from Gold tables.

Only aggregated, publishable data leaves Databricks: Gold already replaces names of likely private persons with
"Muut toimijat", and tender descriptions are not exported (only the LLM summary and assessment).
"""

import json
from datetime import date
from typing import Any, Protocol


class SqlRunner(Protocol):
    def query(self, statement: str) -> list[dict[str, Any]]: ...


QUERIES: dict[str, str] = {
    "kpis": """
        SELECT
          (SELECT count(*) FROM workspace.silver.notices)                                         AS notices,
          (SELECT count(*) FROM workspace.gold.award_facts)                                      AS awards,
          (SELECT count(*) FROM workspace.silver.notices WHERE notice_category = 'competition') AS competitions,
          (SELECT count(*) FROM workspace.gold.open_tenders)                                     AS open_tenders,
          (SELECT sum(contract_value_eur) FROM workspace.gold.award_facts WHERE winner_count = 1) AS single_winner_value_eur,
          (SELECT avg_bids FROM workspace.gold.competition WHERE category_label = 'Kaikki' AND year_label = 'Kaikki') AS avg_bids,
          (SELECT share_low_competition FROM workspace.gold.competition WHERE category_label = 'Kaikki' AND year_label = 'Kaikki') AS share_low_competition,
          (SELECT concat(date_format(min(publication_date), 'M/yyyy'), '–', date_format(max(publication_date), 'M/yyyy')) FROM workspace.silver.notices) AS period
    """,
    "market_share": """
        SELECT category_label AS category, company, wins, won_value_eur, share_of_awards, slice_awards
        FROM workspace.gold.market_share
        WHERE year_label = 'Kaikki' AND (rank <= 12 OR company = 'Muut toimijat')
        ORDER BY category, rank
    """,
    "competition": """
        SELECT category_label AS category, awards, avg_bids, share_single_bid, share_low_competition
        FROM workspace.gold.competition
        WHERE year_label = 'Kaikki' AND category_label <> 'Kaikki' AND awards >= 5
        ORDER BY awards DESC
    """,
    "regions": """
        SELECT region, awards, avg_bids, share_low_competition
        FROM workspace.gold.competition_by_region
        WHERE region <> 'Ei aluetietoa' AND awards >= 5
        ORDER BY awards DESC
    """,
    "buyers": """
        SELECT buyer_name AS buyer, notices, awards, awarded_value_eur, main_category, avg_bids,
               top_winners[0].company AS top_winner, top_winner_share
        FROM workspace.gold.buyer_profiles
        ORDER BY notices DESC LIMIT 10
    """,
    "open_tenders": """
        WITH a AS (
          SELECT * FROM workspace.gold.bid_assessments
          QUALIFY row_number() OVER (PARTITION BY publication_number ORDER BY _assessed_at DESC) = 1
        )
        SELECT o.publication_number AS id, o.title, o.buyer_name AS buyer, o.infra_category AS category,
               array_join(o.regions, ', ') AS region, o.region_from_llm, o.tender_deadline AS deadline, o.days_left,
               concat_ws('–', o.contract_start_year, o.contract_end_year) AS period, o.option_years,
               o.estimated_value_eur, a.recommendation, a.score, a.fit, a.competition, a.risk, a.expected_bids,
               a.summary, a.fit_reason, a.risk_reason, to_json(a.questions_for_bid_team) AS questions,
               a.road_km, a.gravel_road_km, a.high_class_winter_km, a.cycleway_km, a.difficulty,
               to_json(a.resource_notes) AS resource_notes, o.price_share, to_json(o.award_criteria) AS award_criteria, o.win_chance,
               a.scope_clarity, a.contract_terms, a.operational_demands,
               to_json(coalesce(o.region_past_top_winners, o.buyer_past_top_winners)) AS past_winners, o.ted_url AS url
        FROM workspace.gold.open_tenders o JOIN a USING (publication_number)
        ORDER BY a.score DESC
    """,
    "price_spread": "SELECT count(*) AS n, median(spread_ratio) AS median_spread FROM workspace.gold.price_spread",
    "llm_eval": """
        SELECT metric, value, n FROM workspace.gold.llm_eval_metrics
        WHERE prompt_version = (SELECT max(prompt_version) FROM workspace.gold.llm_eval_metrics)
    """,
    "bid_backtest": "SELECT metric, value, n FROM workspace.gold.bid_factor_backtest",
    # Comparable to the EU Single Market Scoreboard indicators (single bidder, awarded on price only)
    "eu_indicators": """
        SELECT count(bids_received) AS n_bids, avg(CAST(is_single_bid AS INT)) AS single_bid_share,
               count(price_share) AS n_price, avg(CASE WHEN price_share >= 1 THEN 1.0 WHEN price_share IS NOT NULL THEN 0 END) AS price_only_share
        FROM workspace.gold.award_facts
    """,
    "criteria": """
        SELECT criteria_band AS band, awards, avg_bids, share_low_competition
        FROM workspace.gold.competition_by_criteria ORDER BY band_order
    """,
}

INT_FIELDS = {"notices", "awards", "competitions", "open_tenders", "wins", "n", "days_left", "score", "fit",
              "competition", "risk", "slice_awards", "scope_clarity", "contract_terms",
              "operational_demands", "n_bids", "n_price"}
FLOAT_FIELDS = {"single_winner_value_eur", "avg_bids", "share_low_competition", "share_single_bid", "won_value_eur",
                "share_of_awards", "awarded_value_eur", "top_winner_share", "option_years", "estimated_value_eur",
                "expected_bids", "median_spread", "value", "road_km", "gravel_road_km", "high_class_winter_km",
                "cycleway_km", "price_share", "win_chance", "single_bid_share", "price_only_share"}
BOOL_FIELDS = {"region_from_llm"}
JSON_FIELDS = {"questions", "past_winners", "resource_notes", "award_criteria"}
EVAL_LABELS = {
    "region_accuracy": "Maakunta oikein",
    "region_coverage": "Maakunta pääteltiin",
    "region_precision": "Annetuista maakunnista oikein",
    "value_match": "Arvo täsmää (±5 %)",
}


def clean_title(title: str | None) -> str | None:
    """TED titles repeat country and CPV label: "Suomi – <CPV label> – <actual title>". Keep the actual title."""
    if not title:
        return title
    parts = title.split(" – ", 2)
    return parts[2] if len(parts) == 3 and parts[0] in ("Suomi", "Finland") else title


def _convert(row: dict[str, Any]) -> dict[str, Any]:
    """The Statement API returns every value as a string; cast by field name."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if v is None or v == "":
            out[k] = [] if k in JSON_FIELDS else None
        elif k in INT_FIELDS:
            out[k] = int(float(v))
        elif k in FLOAT_FIELDS:
            out[k] = float(v)
        elif k in BOOL_FIELDS:
            out[k] = v == "true"
        elif k in JSON_FIELDS:
            out[k] = json.loads(v) or []
        else:
            out[k] = v
    return out


def build_site_data(sql: SqlRunner, today: date) -> dict[str, Any]:
    data = {name: [_convert(r) for r in sql.query(q)] for name, q in QUERIES.items()}
    kpis = data["kpis"][0]
    for t in data["open_tenders"]:
        t["title"] = clean_title(t.get("title"))
        t["region"] = t["region"] or None
        t["period"] = t["period"] or None
    return {
        "meta": {
            "sample": False,
            "generated_at": today.isoformat(),
            "period": kpis.pop("period"),
            "sources": ["EU TED Search API v3", "PRH YTJ avoin data"],
        },
        "kpis": kpis,
        "market_share": data["market_share"],
        "competition": data["competition"],
        "regions": data["regions"],
        "buyers": data["buyers"],
        "open_tenders": data["open_tenders"],
        "price_spread": data["price_spread"][0],
        "llm_eval": [
            {**m, "label": EVAL_LABELS[m["metric"]]} for m in data["llm_eval"] if m["metric"] in EVAL_LABELS
        ],
        "criteria": data["criteria"],
        "eu_indicators": data["eu_indicators"][0],
        "bid_backtest": {m["metric"]: {"value": m["value"], "n": m["n"]} for m in data["bid_backtest"]},
    }
