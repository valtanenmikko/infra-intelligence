# infra-intelligence

AI-powered tender and cost intelligence for infrastructure contractors.

Turns public procurement data into answers to business questions: which upcoming tenders are worth bidding,
who wins what at what price level, where competition is thin, and how cost inflation affects multi-year contracts.

> Status: work in progress.

## Architecture

```
EU TED API ─┐
            ├─► Databricks (Free Edition): Bronze → Silver → Gold (Delta)
Statistics  │        └─ LLM enrichment (Gemini) + evaluation
Finland API ┘
                      ▼
            GitHub Actions → static demo site (GitHub Pages)

Terraform manages the Databricks objects; an Azure Data Factory module documents the Azure variant.
```

## Data

| Source | Content | Access |
|---|---|---|
| [EU TED Search API v3](https://docs.ted.europa.eu/api/latest/index.html) | Finnish infrastructure tenders and contract awards (winners, values, number of bids) since 2024 | Public, no key |

TED covers only tenders above EU thresholds (works ≈ €5.5M). Smaller national tenders are out of scope.

## Development

```bash
python -m unittest discover -s tests -t .
```

Tests put `src/` on the path via `tests/__init__.py`.
