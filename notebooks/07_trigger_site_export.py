# Databricks notebook source
# MAGIC %md
# MAGIC # 07 · Trigger the site export
# MAGIC Starts the GitHub `export-site-data` workflow as soon as Gold is fresh. GitHub's own cron for free repos often
# MAGIC runs hours late or not at all, so the job triggers the export itself; the cron stays as a backup.

# COMMAND ----------

import os
import sys

sys.path.append(os.path.abspath("../src"))

# COMMAND ----------

import requests

from infra_intelligence.config import GITHUB_REPO, GITHUB_SECRET_KEY, SECRET_SCOPE, SITE_EXPORT_WORKFLOW

token = dbutils.secrets.get(SECRET_SCOPE, GITHUB_SECRET_KEY)
resp = requests.post(
    f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{SITE_EXPORT_WORKFLOW}/dispatches",
    json={"ref": "main"},
    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    timeout=30,
)
if resp.status_code != 204:
    raise RuntimeError(f"GitHub returned {resp.status_code}: {resp.text[:300]}")
print("Site export started")
