"""Company and buyer name cleaning and entity resolution by Finnish business ID (Y-tunnus)."""

import html
import re
from collections import Counter, defaultdict
from collections.abc import Iterable

_LEGAL_FORMS = {
    "oy": "Oy", "oyj": "Oyj", "ab": "Ab", "abp": "Abp", "ky": "Ky", "ay": "Ay", "tmi": "Tmi",
    "osk": "Osk", "as": "AS", "asa": "ASA", "gmbh": "GmbH", "ltd": "Ltd", "uab": "UAB", "oü": "OÜ",
}
_LEGAL_FORM_RE = re.compile(
    r"\b(" + "|".join(map(re.escape, _LEGAL_FORMS)) + r"|osuuskunta|kommandiittiyhtiö|avoin yhtiö|kuntayhtymä|liikelaitos)\b",
    re.IGNORECASE,
)
_TRAILING_FORM_RE = re.compile(r"\b(" + "|".join(map(re.escape, _LEGAL_FORMS)) + r")$", re.IGNORECASE)


def clean_company_name(raw: str) -> str:
    """Unescape, trim whitespace, drop business-unit suffixes and normalise legal-form casing.

    "Destia Oy, Kunnossapitopalvelut" -> "Destia Oy"; "Murron maansiirto oy" -> "Murron maansiirto Oy".
    """
    name = re.sub(r"\s+", " ", html.unescape(raw)).strip()
    head, sep, _ = name.partition(", ")
    if sep and _TRAILING_FORM_RE.search(head):
        name = head
    return _TRAILING_FORM_RE.sub(lambda m: _LEGAL_FORMS[m.group(1).lower()], name)


def has_legal_form(name: str | None) -> bool:
    """True if the name carries a company legal form.

    Names without one are often sole traders trading under a personal name. They are excluded from
    published name-level views to avoid exposing private individuals.
    """
    return bool(name and _LEGAL_FORM_RE.search(name))


def canonical_names(pairs: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Pick one display name per ID: the most frequent cleaned name, ties broken by shortest then alphabetical."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for entity_id, raw in pairs:
        if entity_id and raw:
            counts[entity_id][clean_company_name(raw)] += 1
    return {
        entity_id: min(c, key=lambda n: (-c[n], len(n), n))
        for entity_id, c in counts.items()
    }
