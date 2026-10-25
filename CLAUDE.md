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
| LLM | Gemini Flash free tier (~15 RPM / ~1,500 RPD) behind a swappable interface; process each notice once |
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
- Git folder: `/Workspace/Users/valtanenmikko@gmail.com/infra-intelligence` (update with `databricks repos update <id> --branch main` after pushing)
- One-off notebook run: `databricks jobs submit --json @submit.json` with a `notebook_task` (serverless, no cluster spec)
- Ad-hoc SQL: `databricks api post /api/2.0/sql/statements` with the first warehouse from `databricks warehouses list`

## Data notes

- TED query uses infra CPV parent codes (`config.INFRA_CPV_CODES`); TED matches child codes hierarchically.
- ~30 % of hits are building projects listing earthworks as a *secondary* CPV. Bronze keeps everything raw;
  Silver filters on `main-classification-proc`.
- TED covers only above-EU-threshold tenders (works ≈ €5.5M). State this limitation in docs and the demo.
- Same company appears under several names (e.g. business-unit suffixes); buyer agencies were renamed in 2026
  (ELY → Elinvoimakeskus). Entity resolution belongs in Silver.
- In Databricks SQL read hyphenated JSON keys with `raw_json:['winner-name']`, not `$.winner-name`.

## Environment quirks

- `.env` files are hidden from Claude by permission rules — ask the user to edit them.
- `.claude/skills/` and `.databricks/` hold vendored Databricks + HashiCorp skills and are gitignored.
