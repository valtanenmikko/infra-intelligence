"""Go/no-go assessment for open tenders.

Split of responsibilities, so the result is reproducible and auditable:
- the LLM rates qualitative factors it can read from text (fit to the bidder profile, delivery/commercial risk)
  and explains them;
- the competition factor is computed from historical bid counts, not by the LLM;
- the overall score and recommendation come from a fixed formula in code.
"""

from dataclasses import dataclass
from typing import Any

PROMPT_VERSION = "bid-v4"
BATCH_SIZE = 5  # tenders per request

# Example bidder used in the demo. A real deployment would load the company's own profile.
BIDDER_PROFILE = """Esimerkkiprofiili: keskisuuri suomalainen infraurakoitsija.
Vahvuudet: maanteiden ja katujen hoito- ja kunnossapitourakat, talvihoito, päällystys, pienet ja keskisuuret
maarakennus- ja siltakorjaustyöt. Oma kalusto ja päivystysorganisaatio koko Manner-Suomessa.
Rajoitteet: ei omaa ratateknistä (sähkörata, turvalaitteet) eikä vesirakentamisen kalustoa; erikoistunut
kaapeli- ja tietoliikennerakentaminen vaatii aliurakoitsijan. Sopiva urakkakoko noin 0,5–50 M€."""

SYSTEM_PROMPT = """You assess open public infrastructure tenders for a Finnish contractor's bid team.
Rate only what the given text and data support. Write all text in Finnish, short and concrete.

fit (1-5): how well the work matches the bidder profile. 5 = core business, 1 = outside capabilities.
risk (1-5): delivery and commercial risk for the bidder. 5 = low risk, 1 = high risk
  (very long term, heavy penalties or on-call duty, unclear scope, no price index clause on a multi-year contract).
Mention the incumbent or frequent past winners if the history shows them. Do not estimate prices.

resources: scope and resource needs stated in the description. Give numbers only when the text states them,
otherwise null; never estimate.
  road_km: total road length in the contract. gravel_road_km: gravel roads.
  high_class_winter_km: roads in winter maintenance classes Ise and Is (the most demanding: most equipment and
  on-call staff). cycleway_km: walking and cycling routes. difficulty: the stated difficulty level.
  notes: at most 4 short notes on equipment, staffing, on-call duty, qualifications or special tasks in the text.
Use the scope in fit and risk: compare its size and demands to the bidder profile."""

# Difficulty levels used in Finnish state road maintenance contracts (Väylävirasto)
DIFFICULTY_LEVELS = ["perusurakka", "vaativa urakka", "erittäin vaativa urakka"]
MAX_ROAD_KM = 20_000
DESCRIPTION_CHARS = 3000

ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "fit": {"type": "INTEGER"},
                    "fit_reason": {"type": "STRING"},
                    "risk": {"type": "INTEGER"},
                    "risk_reason": {"type": "STRING"},
                    "summary": {"type": "STRING"},
                    "questions_for_bid_team": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "resources": {
                        "type": "OBJECT",
                        "properties": {
                            "road_km": {"type": "NUMBER", "nullable": True},
                            "gravel_road_km": {"type": "NUMBER", "nullable": True},
                            "high_class_winter_km": {"type": "NUMBER", "nullable": True},
                            "cycleway_km": {"type": "NUMBER", "nullable": True},
                            "difficulty": {"type": "STRING", "enum": DIFFICULTY_LEVELS, "nullable": True},
                            "notes": {"type": "ARRAY", "items": {"type": "STRING"}},
                        },
                        "required": ["road_km", "gravel_road_km", "high_class_winter_km", "cycleway_km",
                                     "difficulty", "notes"],
                    },
                },
                "required": ["id", "fit", "fit_reason", "risk", "risk_reason", "summary", "questions_for_bid_team",
                             "resources"],
            },
        }
    },
    "required": ["items"],
}

WEIGHTS = {"fit": 0.4, "competition": 0.3, "risk": 0.3}
# Weight of the category average when estimating bids from a buyer's history. Chosen by backtest
# (gold.bid_factor_backtest): small buyer samples are noisy, and regional history alone was worse than the
# category average, so it is not used for the estimate.
SHRINKAGE_K = 3
BID_THRESHOLD = 65
CONSIDER_THRESHOLD = 45


@dataclass(frozen=True)
class BidAssessment:
    publication_number: str
    fit: int
    fit_reason: str
    risk: int
    risk_reason: str
    competition: int
    expected_bids: float | None
    score: int
    recommendation: str
    summary: str
    questions_for_bid_team: list[str]
    road_km: float | None = None
    gravel_road_km: float | None = None
    high_class_winter_km: float | None = None
    cycleway_km: float | None = None
    difficulty: str | None = None
    resource_notes: list[str] | None = None


def expected_bids(tender: dict[str, Any]) -> float | None:
    """Buyer's average bid count shrunk toward the category average: (n * buyer + k * category) / (n + k)."""
    category, buyer = tender.get("category_avg_bids"), tender.get("buyer_past_avg_bids")
    n = tender.get("buyer_past_bid_awards") or 0
    if category is None:
        return float(buyer) if buyer is not None else None
    if buyer is None or n == 0:
        return round(float(category), 1)
    return round((n * float(buyer) + SHRINKAGE_K * float(category)) / (n + SHRINKAGE_K), 1)


def competition_score(bids: float | None) -> int:
    """5 = little competition expected, 1 = crowded. Unknown history is neutral."""
    if bids is None:
        return 3
    for limit, score in ((1.5, 5), (2.5, 4), (3.5, 3), (5.0, 2)):
        if bids <= limit:
            return score
    return 1


def overall_score(fit: int, competition: int, risk: int) -> int:
    """Weighted 1-5 factors mapped to 0-100."""
    weighted = WEIGHTS["fit"] * fit + WEIGHTS["competition"] * competition + WEIGHTS["risk"] * risk
    return round((weighted - 1) / 4 * 100)


def recommendation(score: int, fit: int) -> str:
    if fit <= 1:
        return "Ei tarjota"  # outside capabilities, whatever the competition
    if score >= BID_THRESHOLD:
        return "Tarjoa"
    if score >= CONSIDER_THRESHOLD:
        return "Harkitse"
    return "Ei tarjota"


def _winners(winners: Any) -> str:
    if not winners:
        return "ei tietoa"
    return ", ".join(f"{w['company']} ({w['wins']})" for w in winners)


def build_prompt(tenders: list[dict[str, Any]]) -> str:
    """tenders: Gold open_tenders rows (which include the LLM extraction fields)."""
    parts = [
        f"Tarjoajan profiili:\n{BIDDER_PROFILE}",
        f"\nArvioi nämä {len(tenders)} avointa kilpailutusta. Palauta yksi item kustakin sen id:llä.",
    ]
    parts += [_tender_block(t) for t in tenders]
    return "\n".join(parts)


def _tender_block(tender: dict[str, Any]) -> str:
    period = "–".join(str(y) for y in (tender.get("contract_start_year"), tender.get("contract_end_year")) if y) or "ei tietoa"
    lines = [
        f"\n### id: {tender.get('publication_number')}",
        f"Otsikko: {tender.get('title')}",
        f"Tilaaja: {tender.get('buyer_name')}",
        f"Luokka: {tender.get('infra_category')}",
        f"Alue: {tender.get('region') or ', '.join(tender.get('regions') or []) or 'ei tietoa'}",
        f"Sopimuskausi: {period}, optiot {tender.get('option_years') or 'ei tietoa'} v",
        f"Arvioitu arvo: {tender.get('estimated_value_eur') or 'ei ilmoitettu'} €",
        f"Indeksiehto: {tender.get('has_price_index_clause')}",
        f"Laajuus: {tender.get('scope_summary') or ''}",
        f"Vaatimukset: {'; '.join(tender.get('key_requirements') or [])}",
        f"Tunnistetut riskit: {'; '.join(tender.get('risks') or [])}",
        f"Kuvaus: {(tender.get('description') or '')[:DESCRIPTION_CHARS]}",
        "\nHistoria (EU-kynnysarvon ylittävät hankinnat 2024–):",
        f"Saman tilaajan ja luokan aiemmat voittajat: {_winners(tender.get('buyer_past_top_winners'))}",
        f"Saman alueen ja luokan aiemmat voittajat: {_winners(tender.get('region_past_top_winners'))}",
        f"Odotettu tarjousmäärä historian perusteella: {expected_bids(tender) or 'ei tietoa'}",
    ]
    return "\n".join(lines)


def _rating(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"Rating must be an integer 1-5, got {value!r}")
    return value


def parse_assessments(data: Any, tenders: list[dict[str, Any]]) -> list[BidAssessment]:
    """Validate a batch response. Items with unknown IDs or invalid ratings are skipped (retried next run)."""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("LLM output has no 'items' list")
    by_id = {t["publication_number"]: t for t in tenders}
    results: dict[str, BidAssessment] = {}
    for item in items:
        tender_id = item.get("id") if isinstance(item, dict) else None
        if tender_id in by_id and tender_id not in results:
            try:
                results[tender_id] = parse_assessment(item, by_id[tender_id])
            except ValueError:
                continue
    return [results[t["publication_number"]] for t in tenders if t["publication_number"] in results]


def parse_assessment(data: Any, tender: dict[str, Any]) -> BidAssessment:
    if not isinstance(data, dict):
        raise ValueError("Assessment is not an object")
    fit, risk = _rating(data.get("fit")), _rating(data.get("risk"))
    bids = expected_bids(tender)
    competition = competition_score(bids)
    score = overall_score(fit, competition, risk)
    questions = [str(q).strip() for q in data.get("questions_for_bid_team") or [] if str(q).strip()][:3]
    resources = parse_resources(data.get("resources"))
    return BidAssessment(
        publication_number=tender["publication_number"],
        fit=fit,
        fit_reason=str(data.get("fit_reason") or "").strip(),
        risk=risk,
        risk_reason=str(data.get("risk_reason") or "").strip(),
        competition=competition,
        expected_bids=bids,
        score=score,
        recommendation=recommendation(score, fit),
        summary=str(data.get("summary") or "").strip(),
        questions_for_bid_team=questions,
        **resources,
    )


def _km(value: Any, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= limit:
        return None
    return float(value)


def parse_resources(data: Any) -> dict[str, Any]:
    """Validate the scope figures. Parts larger than the stated total are dropped as misreads."""
    data = data if isinstance(data, dict) else {}
    road = _km(data.get("road_km"), MAX_ROAD_KM)
    part_limit = road if road is not None else MAX_ROAD_KM
    difficulty = data.get("difficulty")
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    return {
        "road_km": road,
        "gravel_road_km": _km(data.get("gravel_road_km"), part_limit),
        "high_class_winter_km": _km(data.get("high_class_winter_km"), part_limit),
        "cycleway_km": _km(data.get("cycleway_km"), part_limit),
        "difficulty": difficulty if difficulty in DIFFICULTY_LEVELS else None,
        "resource_notes": [str(n).strip() for n in notes if str(n).strip()][:4],
    }
