"""Static configuration: data scope and table names."""

from datetime import date

# Infrastructure CPV codes. TED matches child codes hierarchically,
# e.g. 45233000 also returns 45233252 (street surfacing).
INFRA_CPV_CODES: dict[str, str] = {
    "45230000": "Tiet, radat, kentät ja linjat",
    "45221000": "Sillat ja tunnelit",
    "45112000": "Maanrakennus ja kaivuu",
    "45240000": "Vesirakentaminen",
    "90620000": "Lumenpoisto",
    "90630000": "Jäänpoisto",
    "50230000": "Teiden korjaus ja kunnossapito",
}

BUYER_COUNTRY = "FIN"

# First run backfills from this date; later runs are incremental.
BACKFILL_FROM = date(2024, 1, 1)

# Re-read this many days before the latest stored notice to catch late arrivals.
INCREMENTAL_OVERLAP_DAYS = 7

TED_FIELDS: list[str] = [
    "publication-number",
    "publication-date",
    "notice-type",
    "notice-title",
    "buyer-name",
    "buyer-identifier",
    "classification-cpv",
    # Main CPV of the procedure. The broad query above also returns building projects that list
    # earthworks as a secondary CPV (~30 %); Silver filters on this field.
    "main-classification-proc",
    "procedure-type",
    "place-of-performance",
    "description-lot",
    "deadline-receipt-tender-date-lot",
    "total-value",
    "total-value-cur",
    "estimated-value-lot",
    "result-lot-identifier",
    "framework-agreement-lot",
    "tender-value-lowest",
    "tender-value-highest",
    # Winner names and IDs are separate arrays, not reliably aligned for multi-winner notices.
    "winner-name",
    "winner-identifier",
    "winner-size",
    # Parallel arrays: code "tenders" = total tenders received per lot.
    "received-submissions-type-code",
    "received-submissions-type-val",
]

CATALOG = "workspace"
BRONZE_TED_TABLE = f"{CATALOG}.bronze.ted_notices"
BRONZE_PRH_TABLE = f"{CATALOG}.bronze.prh_companies"
SILVER_COMPANIES_TABLE = f"{CATALOG}.silver.companies"
SILVER_NOTICES_TABLE = f"{CATALOG}.silver.notices"
SILVER_WINNERS_TABLE = f"{CATALOG}.silver.notice_winners"
SILVER_BUYERS_TABLE = f"{CATALOG}.silver.buyers"
SILVER_LLM_EXTRACTIONS_TABLE = f"{CATALOG}.silver.llm_extractions"
GOLD_LLM_EVAL_TABLE = f"{CATALOG}.gold.llm_eval_metrics"
GOLD_LLM_REGION_ERRORS_TABLE = f"{CATALOG}.gold.llm_eval_region_errors"

# LLM: Gemini free tier. The key lives in a Databricks secret scope, never in code or notebooks.
GEMINI_MODEL = "gemini-2.5-flash"
SECRET_SCOPE = "infra-intelligence"
GEMINI_SECRET_KEY = "gemini-api-key"
