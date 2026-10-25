"""LLM extraction of structured facts from tender titles and descriptions.

The model sees only the title, buyer and description. Structured TED fields such as NUTS regions and values are
deliberately withheld so they can serve as ground truth in evaluation (see evaluation.py).
"""

from dataclasses import dataclass
from typing import Any

from infra_intelligence.reference import NUTS3_REGIONS

PROMPT_VERSION = "extract-v1"
MAX_DESCRIPTION_CHARS = 4000
MAX_LIST_ITEMS = 5

REGIONS: list[str] = sorted(set(NUTS3_REGIONS.values()))

SYSTEM_PROMPT = """You are a procurement analyst for a Finnish infrastructure contractor.
You read public tender notices (in Finnish) and extract facts for the bid team.

Rules:
- Use only information stated or clearly implied in the notice. Never guess. Use null or [] when unknown.
- region: the Finnish region (maakunta) where the work is done. Infer it from municipality or place names
  (e.g. "Viinijärvi" is in Liperi -> Pohjois-Karjala). Use null for nationwide work or several regions.
- municipalities: municipality (kunta) names where the work is done, in Finnish.
- contract years: the main contract period without options. option_years: total length of optional extensions.
- mentioned_value_eur: only if the text states a euro amount for the contract value or estimate.
- Write scope_summary, key_requirements and risks in Finnish, short and concrete.
- risks: commercial or delivery risks for a contractor (long duration, penalties, tight schedule, demanding
  on-call duty, price adjustment terms...). Do not invent risks that the text does not support.
"""

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "municipalities": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "region": {"type": "STRING", "enum": REGIONS, "nullable": True},
                    "contract_start_year": {"type": "INTEGER", "nullable": True},
                    "contract_end_year": {"type": "INTEGER", "nullable": True},
                    "option_years": {"type": "NUMBER", "nullable": True},
                    "work_types": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "scope_summary": {"type": "STRING"},
                    "key_requirements": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "risks": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "has_price_index_clause": {"type": "BOOLEAN", "nullable": True},
                    "mentioned_value_eur": {"type": "NUMBER", "nullable": True},
                },
                "required": ["id", "municipalities", "region", "work_types", "scope_summary", "key_requirements", "risks"],
            },
        }
    },
    "required": ["items"],
}


@dataclass(frozen=True)
class ExtractionRecord:
    publication_number: str
    municipalities: list[str]
    region: str | None
    contract_start_year: int | None
    contract_end_year: int | None
    option_years: float | None
    work_types: list[str]
    scope_summary: str | None
    key_requirements: list[str]
    risks: list[str]
    has_price_index_clause: bool | None
    mentioned_value_eur: float | None


def build_prompt(notices: list[dict[str, Any]]) -> str:
    """notices: dicts with publication_number, title, buyer_name, description."""
    parts = [f"Extract facts from these {len(notices)} tender notices. Return one item per notice, using its id."]
    for n in notices:
        description = (n.get("description") or "")[:MAX_DESCRIPTION_CHARS]
        parts.append(
            f"\n### id: {n['publication_number']}\n"
            f"Otsikko: {n.get('title') or ''}\n"
            f"Tilaaja: {n.get('buyer_name') or ''}\n"
            f"Kuvaus: {description}"
        )
    return "\n".join(parts)


def _clean_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = [str(v).strip() for v in values if v is not None and str(v).strip()]
    return list(dict.fromkeys(cleaned))[:MAX_LIST_ITEMS]


def _year(value: Any) -> int | None:
    return value if isinstance(value, int) and 2015 <= value <= 2060 else None


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def parse_extractions(data: Any, expected_ids: list[str]) -> list[ExtractionRecord]:
    """Validate model output. Unknown IDs are dropped; values outside sane ranges become null."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM output has no 'items' list")
    expected = set(expected_ids)
    records: dict[str, ExtractionRecord] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("id") not in expected or item["id"] in records:
            continue
        start, end = _year(item.get("contract_start_year")), _year(item.get("contract_end_year"))
        if start and end and end < start:
            start = end = None
        region = item.get("region")
        summary = item.get("scope_summary")
        index_clause = item.get("has_price_index_clause")
        records[item["id"]] = ExtractionRecord(
            publication_number=item["id"],
            municipalities=_clean_list(item.get("municipalities")),
            region=region if region in REGIONS else None,
            contract_start_year=start,
            contract_end_year=end,
            option_years=_number(item.get("option_years"), 0, 20),
            work_types=_clean_list(item.get("work_types")),
            scope_summary=summary.strip() if isinstance(summary, str) and summary.strip() else None,
            key_requirements=_clean_list(item.get("key_requirements")),
            risks=_clean_list(item.get("risks")),
            has_price_index_clause=index_clause if isinstance(index_clause, bool) else None,
            mentioned_value_eur=_number(item.get("mentioned_value_eur"), 1, 5e9),
        )
    return [records[i] for i in expected_ids if i in records]
