"""Reference data: code lists that map raw TED codes to business-friendly labels."""

# NUTS 3 regions in Finland. TED notices mix the 2021 and 2024 NUTS versions (the 2024 revision renumbered
# several regions, e.g. Pirkanmaa FI197 -> FI19B). No code means a different region across versions, so the
# union is safe. Source: Eurostat GISCO NUTS_AT_2021.csv / NUTS_AT_2024.csv.
NUTS3_REGIONS: dict[str, str] = {
    # NUTS 2021
    "FI193": "Keski-Suomi",
    "FI194": "Etelä-Pohjanmaa",
    "FI195": "Pohjanmaa",
    "FI197": "Pirkanmaa",
    "FI1C3": "Päijät-Häme",
    "FI1C4": "Kymenlaakso",
    "FI1D1": "Etelä-Savo",
    "FI1D2": "Pohjois-Savo",
    "FI1D3": "Pohjois-Karjala",
    # NUTS 2024
    "FI198": "Keski-Suomi",
    "FI199": "Etelä-Pohjanmaa",
    "FI19A": "Pohjanmaa",
    "FI19B": "Pirkanmaa",
    "FI1C6": "Päijät-Häme",
    "FI1C7": "Kymenlaakso",
    "FI1DA": "Etelä-Savo",
    "FI1DB": "Pohjois-Savo",
    "FI1DC": "Pohjois-Karjala",
    # Same code in both versions
    "FI196": "Satakunta",
    "FI1B1": "Helsinki-Uusimaa",
    "FI1C1": "Varsinais-Suomi",
    "FI1C2": "Kanta-Häme",
    "FI1C5": "Etelä-Karjala",
    "FI1D5": "Keski-Pohjanmaa",
    "FI1D7": "Lappi",
    "FI1D8": "Kainuu",
    "FI1D9": "Pohjois-Pohjanmaa",
    "FI200": "Ahvenanmaa",
}

# Business categories by CPV prefix. Longest matching prefix wins.
CPV_CATEGORIES: dict[str, str] = {
    "45233": "Tiet ja kadut",
    "45234": "Rautatiet",
    "45235": "Lentokentät",
    "45231": "Putki- ja kaapelilinjat",
    "45232": "Putki- ja kaapelilinjat",
    "45236": "Liikunta- ja virkistysalueet",
    "4523": "Tie- ja ratarakentaminen, muu",
    "45221": "Sillat ja tunnelit",
    "45112": "Maanrakennus",
    "4524": "Vesirakentaminen",
    "9062": "Talvihoito",
    "9063": "Talvihoito",
    "5023": "Teiden kunnossapito",
}

# Display names for buyers whose Y-tunnus covers many unit names. The ELY centres, the 2026 successor
# Elinvoimakeskus agencies and their shared service centre (KEHA) all procure under one business ID.
BUYER_NAME_OVERRIDES: dict[str, str] = {
    "2296962-1": "ELY-keskukset / elinvoimakeskukset",
    "1010547-1": "Väylävirasto",
    "0201256-6": "Helsingin kaupunki",
}

_NOTICE_CATEGORIES: list[tuple[str, str]] = [
    ("can-modif", "modification"),
    ("can-", "award"),
    ("cn-", "competition"),
    ("pin-", "prior_information"),
    ("veat", "direct_award_notice"),
    ("pmc", "market_consultation"),
    ("qu-sy", "qualification_system"),
]


def cpv_category(cpv: str | None) -> str | None:
    """Return the business category for a CPV code, or None if it is outside the infra scope."""
    if not cpv:
        return None
    matches = [p for p in CPV_CATEGORIES if cpv.startswith(p)]
    return CPV_CATEGORIES[max(matches, key=len)] if matches else None


def notice_category(notice_type: str | None) -> str:
    for prefix, category in _NOTICE_CATEGORIES:
        if notice_type and notice_type.startswith(prefix):
            return category
    return "other"
