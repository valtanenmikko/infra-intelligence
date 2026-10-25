"""Parse PRH YTJ company records into Silver company rows."""

from dataclasses import dataclass
from datetime import date
from typing import Any

_FINNISH = "1"  # PRH languageCode
_OFFICIAL_NAME = "1"  # PRH name type: 1 = official name, 2 = parallel name, 3 = auxiliary name
_SOLE_TRADER_FORMS = {"yksityinen elinkeinonharjoittaja", "toiminimi"}


@dataclass(frozen=True)
class CompanyRecord:
    business_id: str
    name: str | None
    company_form: str | None
    is_sole_trader: bool
    industry_code: str | None
    industry: str | None
    registered_on: date | None


def _finnish(descriptions: list[dict[str, Any]] | None) -> str | None:
    return next((d.get("description") for d in descriptions or [] if d.get("languageCode") == _FINNISH), None)


def _current(items: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Latest item without an end date."""
    active = [i for i in items or [] if not i.get("endDate")]
    return max(active, key=lambda i: i.get("registrationDate") or "", default=None)


def parse_company(raw: dict[str, Any]) -> CompanyRecord:
    name = _current([n for n in raw.get("names") or [] if n.get("type") == _OFFICIAL_NAME])
    form = _current(raw.get("companyForms"))
    form_name = _finnish(form.get("descriptions")) if form else None
    industry = raw.get("mainBusinessLine") or {}
    registered = raw.get("registrationDate")
    return CompanyRecord(
        business_id=raw["businessId"]["value"],
        name=name.get("name") if name else None,
        company_form=form_name,
        is_sole_trader=bool(form_name and form_name.lower() in _SOLE_TRADER_FORMS),
        industry_code=industry.get("type"),
        industry=_finnish(industry.get("descriptions")),
        registered_on=date.fromisoformat(registered) if registered else None,
    )
