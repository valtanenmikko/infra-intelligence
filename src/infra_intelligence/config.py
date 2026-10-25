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
    "result-value-lot",
    "winner-name",
    "received-submissions-type-val",
]

CATALOG = "workspace"
BRONZE_TED_TABLE = f"{CATALOG}.bronze.ted_notices"
