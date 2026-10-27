# infra-intelligence

AI-powered tender and cost intelligence for Finnish infrastructure contractors. Portfolio project aimed at
data/AI engineer roles in the infrastructure sector. Business-focused: answers "which tenders to bid, who wins
at what price, where competition is thin, how cost inflation hits multi-year contracts".

This file overrides the generic parent `Projektit/CLAUDE.md` where they conflict (e.g. build commands, swarm usage).

## Hard rules

- **Zero cost.** No paid cloud resources or paid API calls. LLM = Gemini Flash free tier.
- **Repo stays private** until the user explicitly asks to publish. Never change visibility or enable Pages on your own.
- The demo must not use any company's branding or imply it was made for/with a specific company. Companies appear only as data (e.g. tender winners).
- No new pip packages without asking. Tests use stdlib `unittest` + `unittest.mock`.
- Conventional commits, no Co-Authored-By lines.
- Reply to the user in Finnish; code, comments and docs in English.

## Stack

| Layer | Choice |
|---|---|
| Source | EU TED Search API v3 (public, no key). Later: Statistics Finland PxWeb cost indices |
| Compute/storage | Databricks Free Edition, serverless, Unity Catalog `workspace` catalog, Delta |
| Medallion | `workspace.bronze` → `workspace.silver` → `workspace.gold` |
| LLM | Gemini free tier with automatic model fallback (`config.EXTRACTION_MODELS` / `ASSESSMENT_MODELS`). Extraction: 3.5/3.1 Flash Lite, 15 RPM, **500 requests/day**. Go/no-go: 3.8 Flash (5 RPM, 20/day, often 503 overloaded) → 3.6 Flash → 3.5 Flash Lite. Quotas reset at midnight Pacific time. Batch notices, process each once per prompt version |
| IaC | Terraform: Databricks objects (always), Azure + ADF module (documented variant, apply only if free credits) |
| Demo | Static site built by GitHub Actions from Gold data → GitHub Pages (only when published) |

## Layout

- `src/infra_intelligence/` — importable Python package (config, ingest clients, later transforms/LLM)
- `notebooks/` — Databricks notebooks in source format; they add `../src` to `sys.path`
- `tests/` — unit tests; `tests/__init__.py` puts `src/` on the path

## Commands

```bash
python -m unittest discover -s tests -t .        # unit tests (run after every code change)
```

Databricks CLI (profile `dbc-2186c486-fc1a`, user valtanenmikko@gmail.com). In a fresh VS Code terminal the
CLI may need a PATH refresh:
```powershell
$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
```
- Scheduled job `infra-intelligence-daily` (job_id 288507497663040), daily 10:30 Europe/Helsinki, Git source
  `main` (no repo pull needed). Test single tasks with `databricks jobs run-now --json '{"job_id": ..., "only": ["silver"]}'`.
  Extraction processes all pending notices (first run ~82 requests on Flash Lite, then a few per day).
- Git folder (for interactive use): `/Workspace/Users/valtanenmikko@gmail.com/infra-intelligence` (update with `databricks repos update <id> --branch main` after pushing)
- One-off notebook run: `databricks jobs submit --json @submit.json` with a `notebook_task` (serverless, no cluster spec)
- Ad-hoc SQL: `databricks api post /api/2.0/sql/statements` with the first warehouse from `databricks warehouses list`

## Data notes

- TED query uses infra CPV parent codes (`config.INFRA_CPV_CODES`); TED matches child codes hierarchically.
- ~30 % of hits are building projects listing earthworks as a *secondary* CPV. Bronze keeps everything raw;
  Silver filters on `main-classification-proc`.
- TED covers only above-EU-threshold tenders (works ≈ €5.5M). State this limitation in docs and the demo.
- Entity resolution is by Y-tunnus, never by name. Winners come as Y-tunnus or Finnish VAT number
  (`FI21630263` = `2163026-3`); `normalize_business_id` merges them. Official names, company form and industry
  come from the PRH YTJ open data API (cached in `bronze.prh_companies`).
- `winner-name` and `winner-identifier` arrays are NOT aligned in multi-winner (framework) notices; only
  single-winner notices may link a name to an ID.
- Privacy: winner names are shown only when `is_registered_company` (found in PRH open data and not a sole
  trader). IDs missing from PRH open data are typically private persons.
- ELY centres, Elinvoimakeskus agencies (2026 rename) and KEHA share one buyer Y-tunnus (`BUYER_NAME_OVERRIDES`).
- Bid counts: `tenders` statistic, falling back to `t-esubm` (e-submission is mandatory above EU thresholds).
- In Databricks SQL read hyphenated JSON keys with `raw_json:['winner-name']`, not `$.winner-name`.

## Environment quirks

- `.env` files are hidden from Claude by permission rules — ask the user to edit them.
- A Ruflo hook in the parent folder creates stray empty files named after code fragments (e.g. `CompanyRecord`,
  `tuple[str`). Before committing run `find . -maxdepth 1 -type f -empty -delete` and check `git status`.
- Databricks Free Edition has a daily serverless quota; when exceeded, all compute (jobs and SQL warehouse) is
  refused for the rest of the day ("RESOURCE_EXHAUSTED"). Put quality checks inside notebooks, avoid ad-hoc
  warehouse queries, run only the notebooks a change affects, and stop the warehouse if it loops on start.
- Write JSON request files for the Databricks CLI without a BOM (PowerShell `Out-File -Encoding utf8` adds one).
- `.claude/skills/` and `.databricks/` hold vendored Databricks + HashiCorp skills and are gitignored.
