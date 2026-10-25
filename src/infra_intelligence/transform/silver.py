"""Parse raw TED notices (Bronze JSON) into typed Silver records."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from infra_intelligence.ingest.prh_client import is_business_id, normalize_business_id
from infra_intelligence.reference import NUTS3_REGIONS, cpv_category, notice_category
from infra_intelligence.transform.companies import CompanyRecord
from infra_intelligence.transform.names import clean_company_name, has_legal_form

_LANG_PREFERENCE = ("fin", "eng", "swe")


@dataclass(frozen=True)
class NoticeRecord:
    publication_number: str
    publication_date: date | None
    notice_type: str | None
    notice_category: str
    title: str | None
    description: str | None
    buyer_id: str | None
    buyer_unit: str | None
    main_cpv: str | None
    infra_category: str | None
    cpv_codes: list[str]
    procedure_type: str | None
    regions: list[str]
    tender_deadline: date | None
    total_value_eur: float | None
    estimated_lot_value_eur: float | None
    lot_count: int
    tenders_received_min: int | None
    tenders_received_max: int | None
    lowest_tender_eur: float | None
    highest_tender_eur: float | None
    is_framework: bool
    winner_ids: list[str]
    winner_names_raw: list[str]
    winner_size: str | None


@dataclass(frozen=True)
class WinnerRecord:
    publication_number: str
    winner_id: str
    winner_name: str | None
    # False hides the name in published views: sole traders and IDs missing from PRH open data are likely
    # private persons. Foreign IDs fall back to the legal-form check.
    is_registered_company: bool
    is_single_winner: bool


def _localized(value: Any) -> list[str]:
    """TED multilingual fields are {lang: str | [str]}. Return values in the preferred language."""
    if not isinstance(value, dict) or not value:
        return []
    lang = next((l for l in _LANG_PREFERENCE if l in value), next(iter(value)))
    v = value[lang]
    return v if isinstance(v, list) else [v]


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _to_date(value: str | None) -> date | None:
    # TED dates look like "2024-01-03Z" or "2024-02-19+02:00"
    return date.fromisoformat(value[:10]) if value else None


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _floats(values: list[Any] | None) -> list[float]:
    return [f for f in map(_to_float, values or []) if f is not None]


def _unique(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(values or []))


def _submission_counts(raw: dict[str, Any], code: str) -> list[int]:
    """Per-lot submission counts of one statistic type.

    "tenders" is the total. Many notices only report "t-esubm" (electronically submitted tenders); electronic
    submission is mandatory for above-threshold procurements in Finland, so it is used as the fallback total.
    """
    pairs = zip(raw.get("received-submissions-type-code") or [], raw.get("received-submissions-type-val") or [])
    return [int(v) for c, v in pairs if c == code and str(v).isdigit()]


def winner_ids(raw: dict[str, Any]) -> list[str]:
    return _unique([normalize_business_id(i) for i in raw.get("winner-identifier") or []])


def single_winner_pair(raw: dict[str, Any]) -> tuple[str, str] | None:
    """(Y-tunnus, raw name) when the notice has exactly one winner.

    TED returns winner names and IDs as separate arrays that are not reliably aligned for multi-winner
    notices (frameworks), so only single-winner notices are trusted to link a name to an ID.
    """
    ids = winner_ids(raw)
    names = _unique(_localized(raw.get("winner-name")))
    if len(ids) == 1 and len(names) == 1:
        return ids[0], names[0]
    return None


def parse_notice(raw: dict[str, Any]) -> NoticeRecord:
    main_cpv = _first(raw.get("main-classification-proc") or [])
    currencies = set(raw.get("total-value-cur") or [])
    tenders = _submission_counts(raw, "tenders") or _submission_counts(raw, "t-esubm")
    deadlines = [d for d in map(_to_date, raw.get("deadline-receipt-tender-date-lot") or []) if d]
    lowest = _floats(raw.get("tender-value-lowest"))
    highest = _floats(raw.get("tender-value-highest"))
    estimated = _floats(raw.get("estimated-value-lot"))
    sizes = _unique(raw.get("winner-size"))
    ids = winner_ids(raw)

    return NoticeRecord(
        publication_number=raw["publication-number"],
        publication_date=_to_date(raw.get("publication-date")),
        notice_type=raw.get("notice-type"),
        notice_category=notice_category(raw.get("notice-type")),
        title=_first(_localized(raw.get("notice-title"))),
        description="\n\n".join(_localized(raw.get("description-lot"))) or None,
        buyer_id=_first([normalize_business_id(i) for i in raw.get("buyer-identifier") or []]),
        buyer_unit=_first(_localized(raw.get("buyer-name"))),
        main_cpv=main_cpv,
        infra_category=cpv_category(main_cpv),
        cpv_codes=_unique(raw.get("classification-cpv")),
        procedure_type=raw.get("procedure-type"),
        regions=_unique([NUTS3_REGIONS[c] for c in raw.get("place-of-performance") or [] if c in NUTS3_REGIONS]),
        tender_deadline=min(deadlines) if deadlines else None,
        total_value_eur=_to_float(raw.get("total-value")) if currencies <= {"EUR"} else None,
        estimated_lot_value_eur=sum(estimated) if estimated else None,
        lot_count=max(len(_unique(raw.get("result-lot-identifier"))), 1),
        tenders_received_min=min(tenders) if tenders else None,
        tenders_received_max=max(tenders) if tenders else None,
        lowest_tender_eur=min(lowest) if lowest else None,
        highest_tender_eur=max(highest) if highest else None,
        is_framework=any(v != "none" for v in raw.get("framework-agreement-lot") or []),
        winner_ids=ids,
        winner_names_raw=_unique(_localized(raw.get("winner-name"))),
        winner_size=sizes[0] if len(ids) == 1 and len(sizes) == 1 else None,
    )


def parse_winners(
    raw: dict[str, Any],
    names_by_id: dict[str, str],
    companies: dict[str, CompanyRecord],
) -> list[WinnerRecord]:
    """One row per winner ID. Name priority: PRH official name > name learned from single-winner notices >
    this notice's own name (single winner only)."""
    ids = winner_ids(raw)
    pair = single_winner_pair(raw)
    rows = []
    for winner_id in ids:
        company = companies.get(winner_id)
        name = (company and company.name) or names_by_id.get(winner_id) or (clean_company_name(pair[1]) if pair else None)
        if is_business_id(winner_id):
            registered = company is not None and not company.is_sole_trader
        else:
            registered = has_legal_form(name)
        rows.append(WinnerRecord(
            publication_number=raw["publication-number"],
            winner_id=winner_id,
            winner_name=name,
            is_registered_company=registered,
            is_single_winner=len(ids) == 1,
        ))
    return rows
