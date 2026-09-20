# Project guide

## Purpose

Service operations teams need consistent answers about open work, incident resolution, reopening, and ownership. Audit logs contain repeated observations, missing categories, corrections, and timestamps that can expose future outcomes. This project makes those assumptions explicit and publishes reproducible metrics.

The deployment uses a fixed public historical extract. Scheduled weekly delivery and failure exercises simulate an operating pipeline; no live enterprise system is connected.

## Architecture

1. `package_batches.py` assigns each original CSV observation to the week ending Sunday. It preserves its original file fingerprint and row position, writes compressed JSON envelopes, and records each batch checksum, row count, and availability cutoff.
2. The coordinator acquires a conditional DynamoDB lease and reads the immutable delivery registry and last committed snapshot. Only unseen, eligible batches enter the run.
3. The Glue job verifies compressed-byte checksums and counts, validates the event schema, quarantines invalid rows, and reconciles accepted versions with the previous history.
4. Facts and dimensions are materialized as Parquet. Spark SQL joins the incident stage to group, priority, and date dimensions. A separate SQL aggregation must agree with the Python report's group counts.
5. Integrity checks must pass before publication. The coordinator updates the Athena catalog and commits one S3 pointer. It then copies an allowlisted aggregate report into a separate website bucket.
6. CloudFront serves the page over HTTPS. Its origin can read only the website bucket. Raw data, revision history, quarantined payloads, and internal pointers are never copied there.
7. Monday's scheduled run advances the cutoff seven historical days. A daily freshness check alerts when pending source batches exist and the last committed report is over nine days old.

The laptop is needed only for local development or manual administration. GitHub releases, scheduled AWS processing, and website serving run independently.

## Repository map

| Location | Responsibility |
|---|---|
| `src/serviceops/domain.py` | Required schema, category cleanup, source-local date parsing, and invalid row reasons |
| `src/serviceops/incremental.py` | Checksums, immutable registry selection, duplicate/revision reconciliation, and rejection threshold |
| `src/serviceops/analytics.py` | Point-in-time incident state, daily flows, and metric calculations |
| `src/serviceops/modeling.py` | Fact/dimension grains, keys, history intervals, and integrity checks |
| `src/serviceops/reporting.py` | Shared report assembly used locally and in AWS |
| `aws/incremental_job.py` | AWS orchestration of reconciliation, Spark SQL, and Parquet outputs |
| `aws/coordinator_v2.py` | Lease, cutoff selection, catalog updates, commit boundary, public report, and freshness metric |
| `scripts/replay.py` | Local incremental pipeline and standalone dashboard output |
| `scripts/exercise_batches.py` | Isolated simulated delivery and quality-failure scenarios |
| `scripts/release.py` | Deterministic artifacts, restricted application release, and smoke run |
| `scripts/setup_github.py` | One-time OIDC trust and repository variables |
| `sql/` | Dimensional transformation, queue aggregation, and independent verification |
| `dashboard/` | Public read-only interface; no administrative endpoint |
| `infrastructure/` | Storage, pipeline, website, and restricted deployment role |

## Record identity and revisions

The event key is `SHA256(original CSV fingerprint + ':' + original row position)`. Identical-looking source rows are preserved because they can be separate original audit observations. A delivery duplicate repeats the same event key, revision, and payload; it is counted as a received delivery but does not create another analytical event.

Corrections retain the original identity and increment `revision`. A newer accepted revision replaces the event in the current state and preserves previous revisions in the audit history. A previously unseen older revision is retained for audit but cannot overwrite a newer version. Two different payloads with the same identity and revision fail the run. An event cannot change its incident identifier through a correction.

Late arrival means an accepted new event or correction has an event timestamp at or before the previous committed cutoff. Reconciliation reconstructs the affected historical sequence before computing the new snapshot. These are latest-known historical metrics: a late correction can restate earlier daily results in a later report. Previous run outputs remain immutable for comparison.

This identity scheme is suitable for this pinned extract. A real connector needs a native audit-record ID, record version, source cursor, pagination contract, and delete policy. Changing a CSV fingerprint is not a safe substitute for native identity across arbitrary exports.

## Data wrangling

Dates are parsed day-first. Source timestamps stay timezone-naive because the source does not identify a timezone; publication timestamps are UTC. Missing optional categories (`?`, blanks, nulls) become `Unknown`. Required dates, IDs, valid states, and nonnegative integer counters are checked. Updates preceding opening are quarantined. No statistical outlier trimming is applied to long resolution times: a long duration alone is not proof of corrupt data.

Final outcome columns such as `resolved_at`, `closed_at`, and `made_sla` are excluded from event-time inputs. They can be repeated on early observations and leak future information. Resolution time is inferred from the latest observed closing cycle instead.

Rows with invalid required values are retained privately with reasons. More than 1% rejected rows in a run, checksum mismatch, identity conflict, failed key constraint, failed balance, or SQL disagreement stops publication. Unknown optional categories are profiled rather than silently filled with invented values.

## Facts, dimensions, and SQL

`fact_incident_snapshot` contains one row per incident for the committed cutoff. `fact_incident_history` contains ordered state observations with half-open validity intervals. Simultaneous observations may have zero-length intervals; modification count and original row position supply deterministic ordering. `event_revisions` records ingestion history separately from business-event history.

`dim_assignment_group`, `dim_priority`, and `dim_date` provide unique keys. Group and priority keys are deterministic hashes of labels. They are lookup dimensions, not slowly changing dimension type 2 tables. The date dimension includes every source-local calendar date needed for incident opening and snapshot joins.

The Spark SQL transformation validates that dimension joins preserve the incident grain. SQL queue aggregation is independently compared against the report's Python totals. Athena queries the same published Parquet and supplies a third verification path.

## Publication and recovery

Attempt outputs are isolated under `runs/<attempt>/`. Transformation failure leaves the committed pointer and public report unchanged. Catalog updates are applied before committing; if a catalog operation raises an error, the coordinator attempts to restore the previous catalog locations. The single committed S3 object is the authoritative state for subsequent ingestion.

Catalog updates, the commit object, and public JSON are not a multi-service transaction. An interrupted publication can temporarily leave catalog tables on different attempts or leave the public report behind the internal commit. Repeating the same request repairs public publication without rerunning Glue when the internal run is already committed. Check catalog snapshot metadata after an interrupted catalog update. This is guarded, idempotent batch processing, not a claim of universal exactly-once execution.

A one-hour DynamoDB lease prevents simultaneous pipeline and application-deployment changes. Glue is capped at one concurrent job with a ten-minute timeout; the workflow has a twenty-minute timeout. Only the current owner may release the lease. An unexpectedly abandoned lease expires; automatic retries do not forcibly remove another owner's lock.

## Deployment and access

Infrastructure is provisioned with CloudFormation using an authorized local AWS session. Application changes on GitHub main run tests, linting, template checks, a restricted OIDC release, and a cloud smoke run. Repository ID, owner ID, and main-branch reference constrain the OIDC subject. No long-lived AWS keys are stored in GitHub.

The deployment role can update the existing coordinator and Glue job, upload versioned artifacts and web assets, manage only the pipeline lock key, read the committed pointer, and run a named smoke execution. It cannot administer IAM, create arbitrary infrastructure, change billing, or read the raw dataset. Application code still runs under its service roles; anyone permitted to change main should therefore be trusted to change application behavior.

CloudFront exposes only static application files and aggregate JSON. Both S3 buckets retain public-access blocking. The dashboard has no execution button, data upload endpoint, or AWS credentials. Its filters and downloads operate on the already-published aggregate data.

## Scale and cost

New input is incremental; output snapshots are rebuilt. Reconciliation and report calculations run in bounded Python memory with a 500,000-revision guard. Spark performs dimensional SQL and distributed Parquet writes. This is appropriate for a small reproducible demonstration, not evidence of multi-terabyte scalability. Larger workloads need distributed merges, table-format decisions, compaction, partition-aware aggregation, and measured capacity tests.

Weekly runs, two small Glue workers, timeouts, Athena scan limits, and storage lifecycle rules limit routine usage. The website has no always-running virtual machine. Public traffic and development reruns remain variable costs; the $25 budget sends alerts and is not a hard cap. See the measured assumptions in [costs.md](costs.md).

## Dataset attribution

Amaral, Fantinato, and Peres, UCI Incident Management Process Enriched Event Log, DOI 10.24432/C57S4H, CC BY 4.0. Source: https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log.
