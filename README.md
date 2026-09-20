# Service Operations Analytics

An automated AWS incident-analytics pipeline with incremental deliveries, dimensional tables, verified metrics, and a public aggregate dashboard.

**[Open the dashboard](https://d17q1whdf7htno.cloudfront.net)**

The source is the public UCI Incident Management Process Enriched Event Log. **Batch delivery, duplicate, late-update, and correction scenarios are simulated from a fixed historical dataset. This is not connected to a live ServiceNow instance.**

## Data flow

```text
Immutable S3 batches → Step Functions → Glue / Python / Spark SQL
                                      → validation and revision reconciliation
                                      → Parquet facts and dimensions → Athena
                                      → commit pointer → aggregate JSON → CloudFront dashboard
GitHub main → tests → restricted OIDC role → application release → workflow smoke run
```

- Stable event identities and revision history prevent double counting.
- Invalid records are quarantined; more than 1% invalid deliveries stop publication.
- Integrity checks reconcile incident counts, foreign keys, history intervals, daily flows, and independent SQL aggregates.
- A weekly schedule advances the historical replay; daily monitoring detects stale processing.
- The website remains available between runs. It exposes aggregates; raw data and administrative access remain private.
- GitHub deploys with temporary credentials scoped to this repository and main branch. It cannot change IAM policies or create arbitrary infrastructure.

## Run locally

Python 3.11 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,aws]"
.\.venv\Scripts\serviceops download
.\.venv\Scripts\python scripts/replay.py --as-of "2016-05-01 23:59:59"
.\.venv\Scripts\python -m http.server 8765 --bind 127.0.0.1 --directory build/incremental
```

Open http://127.0.0.1:8765. The generated HTML also opens offline. On Windows, `./scripts/start-local.ps1` performs these steps after environment setup. Use a new output directory for an earlier historical cutoff.

```powershell
.\.venv\Scripts\python scripts/replay.py --as-of "2016-05-08 23:59:59"
.\.venv\Scripts\python scripts/exercise_batches.py
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check src tests scripts aws
.\.venv\Scripts\cfn-lint infrastructure/*.yaml
```

## Documentation

- [Project guide](docs/project-guide.md): architecture, flow, processing choices, and boundaries.
- [Data contract and metrics](docs/data-contract.md): cleaning rules, table grains, and precise definitions.
- [Operations runbook](docs/runbook.md): deployment, recovery, scheduling, and custom domains.
- [Validation record](docs/validation.md): measured checks and evidence.
- [Cost measurement](docs/costs.md): observed compute usage and explicit monthly assumptions.
- [Forecast feasibility](docs/forecast-feasibility.md): temporal coverage and baseline evaluation.

## Boundaries

Ingestion is incremental: only unprocessed deliveries are read and normalized. Reconciled state and serving marts are rebuilt for each snapshot. The in-memory history has an explicit 500,000-version limit. This is a bounded portfolio workload, not an enterprise-scale CDC or exactly-once system. Spark writes Parquet and performs dimensional SQL joins; Python performs bounded reconciliation and time-aware metrics.

Replay eventually exhausts the fixed extract. The site stays online and displays that status. New authorized batches can be registered with `scripts/submit_batch.py`; a genuine live feed requires a separate source integration.

## Attribution

Amaral, C., Fantinato, M., & Peres, S. (2018). *Incident management process enriched event log*. [UCI Machine Learning Repository](https://doi.org/10.24432/C57S4H), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Transformations clean, quarantine, version, and aggregate the original observations. Raw files are excluded from Git.
