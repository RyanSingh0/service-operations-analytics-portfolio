# Data contract and metric definitions

## Source and time

The reference public extract has 141,712 rows, 36 original columns, and 24,918 incident identifiers. CSV SHA-256: `fd184bbfd62329cfe093e99da2ea7071905f2ead91900b448eb2635870821bef`.

Source dates use day/month/year and an unspecified local timezone. They are not labeled UTC. Delivery availability and analytical cutoffs use that same source-local timeline; generation and monitoring timestamps use UTC.

The raw source remains unchanged. Date parsing, category cleanup, validation, version selection, dimensional keys, and metrics are derived transformations. Missing categories are not imputed from later observations.

## Delivery envelope

Each gzip JSON-lines object contains envelopes with `source_sha256` (64 lowercase hexadecimal characters), `source_row` (original position, at least 2), positive integer `revision`, and `record` (original column/value mapping). New columns are preserved in private landing data but ignored by the approved normalized schema. Missing required columns fail the batch.

The registry identifies each batch by immutable ID, compressed-byte SHA-256, S3 key under `landing/`, row count, and source-local availability cutoff. Registration uses a conditional registry update to prevent concurrent lost updates. Reusing a batch ID with changed content is rejected. Checksums are verified again before processing.

The original source key remains stable across corrections. A correction increments the revision rather than replacing the original source fingerprint. Native source identity would be required for a live connector.

## Cleaning and validation

| Check | Behavior |
|---|---|
| Missing required schema columns | Fail the batch |
| Corrupt gzip, checksum/count mismatch, invalid envelope identity | Fail the batch |
| Missing or malformed incident ID | Quarantine; IDs must match INC followed by digits |
| Unknown incident state | Quarantine |
| Missing/unparseable opening or update timestamp | Quarantine |
| Update precedes opening | Quarantine |
| Invalid, negative, or fractional counters | Quarantine |
| Empty optional category, null, or `?` | Normalize to Unknown and count in the profile |
| Same event/revision with conflicting payloads | Fail the batch |
| Correction attempts to change incident identity | Fail the batch |
| Repeated delivery of the same event/revision/payload | Count delivery, do not create another event |
| Previously unseen revision older than current | Retain for audit; do not replace current state |
| More than 1% invalid delivered rows | Fail publication |
| Nonunique keys, missing dimension joins, negative durations, count imbalance, SQL disagreement | Fail publication |

Counters checked: `sys_mod_count`, `reopen_count`, and `reassignment_count`. Recognized states: New, Active, Awaiting User Info, Awaiting Vendor, Awaiting Problem, Awaiting Evidence, Resolved, Closed. Optional category values outside an assumed business taxonomy are retained because no authoritative taxonomy is supplied.

Long durations are not automatically deleted or winsorized. Conflicting opening timestamps across observations are profiled and disclosed; the selected latest observation supplies the snapshot opening time. The dataset does not support an independently validated SLA calendar or business-hours duration.

## Table grains

| Table | Grain and key |
|---|---|
| Current `events` Parquet | One latest accepted revision per stable event ID |
| `event_revisions` | One accepted event ID and revision; includes batch, receipt timestamp, content hash, and late-arrival flag |
| `fact_incident_snapshot` | One incident per committed snapshot cutoff; incident ID unique within a run |
| `fact_incident_history` | One visible event per incident, with ordered validity intervals and transition indicators |
| `fact_daily_queue` | One calendar date per published reporting window |
| `dim_assignment_group` | One normalized group label and deterministic group key |
| `dim_priority` | One normalized priority label and deterministic priority key |
| `dim_date` | One calendar day; integer YYYYMMDD key, date, year, month, day, weekday, weekend flag |
| `incidents` | Compatibility catalog table over the current incident snapshot files |

Each attempt retains its own snapshot directory. Current catalog tables point to one committed attempt. Group and priority dimensions are lookup tables; incident history supplies temporal observations. They are not described as type 2 slowly changing dimensions.

## Metrics

| Metric | Definition and denominator |
|---|---|
| Incidents observed | Count of unique incidents with an accepted event timestamp at or before the cutoff |
| Latest state | Last event ordered by update timestamp, modification count, then original row position |
| Open backlog | Incidents whose latest state is neither Resolved nor Closed |
| Resolved/closed count | Incidents whose latest state is Resolved or Closed; incidents = open + resolved/closed |
| Observed resolution hours | Opening time to the last Resolved observation in the latest closing cycle; the first Closed observation in that cycle is the fallback; open incidents excluded |
| Median / p90 resolution | Median and interpolated 90th percentile of nonmissing observed resolution hours among currently resolved/closed incidents |
| Reopened percentage | Incidents with latest `reopen_count > 0` divided by all observed incidents, multiplied by 100 |
| Reassigned count | Incidents with latest `reassignment_count > 0`; not total handoffs |
| First observed per day | Incidents whose first accepted visible event occurs that day; this is not necessarily exact business creation volume |
| Resolution transitions | Observations entering Resolved/Closed from a nonterminal state, or a first observation already terminal |
| Reopening transitions | Observations entering a nonterminal state after a terminal state |
| Daily backlog | End-of-observed-day backlog, truncated at the requested cutoff on the final day |
| Backlog conservation | Starting backlog + first observed - terminal entries + reopenings = ending backlog |
| Group ownership | Latest observed assignment group; no causal team-performance attribution |

Final `resolved_at`, `closed_at`, `resolved_by`, `closed_code`, and `made_sla` fields do not enter event-time features. No live SLA compliance rate is claimed.

## Quality counts

Cumulative `source_rows` counts deliveries actually consumed by committed runs, not future rows in the complete extract. `accepted_rows` counts valid delivered envelopes, including duplicates and stale versions. `current_events` counts latest accepted event versions and `revision_records` counts distinct retained event revisions. Incident metrics deduplicate at incident grain after event ordering.

The last-run batch section records inserted events, corrections, duplicate deliveries, older revisions, late arrivals, and rejection reasons. A code-only rebuild can correctly show zero new rows. Historical baseline and simulated fixtures are separate; fixture failures never alter the published UCI dashboard.

## Restatement and finite replay

A later correction can restate earlier daily metrics in a newer snapshot. Old run outputs remain available for audit. Public historical metrics are therefore latest-known reconstructions, not a bitemporal query service. After the final registered availability date, repeat scheduled requests are skipped and the dashboard displays Replay complete. New data requires registering a new authorized batch or building a real source connector.
