# Validation record

Verified 18–19 September 2026. Reference snapshot: `2016-05-08 23:59:59`, source-local time. The source is fixed historical data; these results describe the deployed demonstration.

## Reconciled results

| Measure | Local and AWS result |
|---|---:|
| Original extract rows | 141,712 |
| Deliveries consumed by this cutoff | 105,372 |
| Accepted current events | 105,367 |
| Quarantined deliveries | 5 |
| Incidents observed | 19,280 |
| Open backlog | 1,262 |
| Resolved/closed incidents | 18,018 |
| Median observed resolution | 12.08 hours |
| p90 observed resolution | 292.12 hours |
| Reopened incident percentage | 1.04% |

The May 1 load consumed nine weekly batches. Advancing to May 8 consumed one new batch containing 10,727 valid observations. All 51 batches are prepared from the pinned extract; later batches are not visible before their availability cutoff.

Local/cloud comparison passed for the summary, daily series, every group/priority aggregate, profile, and cumulative quality counts. Last-run delivery counts depend on whether the execution is an initial load, increment, or code rebuild and are not used as cumulative-parity evidence.

## Automated checks

32 tests pass, covering cleaning, future-information exclusion, deterministic state selection, reopening cycles, identity and revision handling, late updates, duplicate suppression, failure preservation, lease ownership, publication validation, dimensional keys, and daily flow balance. Python lint and all four CloudFormation templates pass validation.

Sixteen shared integrity checks pass, plus the cloud Spark SQL aggregation check: unique event and incident grains; unique group, priority, and date keys; valid dimension references; one current history row per incident; valid history intervals; nonnegative durations; no future observations; incident, group, and daily balance; and independent SQL/Python queue agreement.

Independent Athena queries verified unique incident counts, backlog, foreign keys, durations, current history rows, and daily balance. The three queries scanned 427,780 bytes. Their query billing minimums still apply.

## Deployment and recovery evidence

[GitHub deployment run 35455756878](https://github.com/RyanSingh0/service-operations-analytics/actions/runs/35455756878) passed validation, restricted OIDC authentication, application release, and an AWS workflow smoke execution at commit `412aaa7`. [Separate CI run 35455756896](https://github.com/RyanSingh0/service-operations-analytics/actions/runs/35455756896) also passed. These historical production-run links belong to the private deployment repository. This public repository starts with a clean publication history; the original deployment repository remains private.

The first upgraded release authenticated correctly but its Lambda waiter requested an operation outside the role. Changing to the waiter that uses the already-permitted configuration-read operation resolved this without expanding access.

Controlled cloud exercise:

| Execution name | Outcome |
|---|---|
| `exercise-failure-1789775069` | Expected failure before publication; previous commit and public report unchanged byte-for-byte; lease released |
| `exercise-recovery-1789777658` | SUCCEEDED and published the May 8 snapshot |
| `exercise-duplicate-1789777861` | SUCCEEDED through Prepare, AlreadyPublished, Complete; no Glue transformation |

The separate local fixture exercise passed repeated delivery, late arrival, newer correction, stale revision, and rejection-threshold scenarios. These synthetic records are isolated from the public UCI report.

## Website and data boundary

The public CloudFront report matches the committed AWS summary and cutoff. Both data and website buckets have every S3 public-access block enabled. CloudFront accesses only the separate website origin through origin access control. Requests for `/internal/committed.json` and `/source/registry.json` return 403/404. Public JSON excludes internal ARNs and the source fingerprint.

Browser checks passed page loading, priority and group filtering, empty-filter results, chart controls, the quality tab, and desktop screenshot inspection. The page displays pipeline publication freshness separately from the historical data cutoff. Raw incidents and administrative actions are unavailable in the interface.

## Operational boundaries

The deployed schedule and notification status are recorded in the handoff report. Infrastructure deployment intentionally disables weekly processing until verification; application-only GitHub releases preserve that schedule. Email alerts require the recipient to confirm the SNS subscription.

Successful upgraded Glue runs were measured at 132 seconds with two G.1X workers. See [costs.md](costs.md) for usage projections and billing availability. No monthly invoice, enterprise throughput, live source integration, prediction accuracy, or business savings are claimed. Forecasting coverage and baseline limitations are documented separately.
