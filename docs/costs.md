# Measured usage and monthly estimate

## September 25 measurement

Cost Explorer reports **$0.379389 estimated account-wide unblended cost for September 1–25**
(September 26 end-exclusive), retrieved September 25 at 21:25 New York time. This is
month-to-date account spending, not a project-only allocation or a finalized monthly bill.
Versioned storage across the project data and website buckets totals approximately 384.4 MB.
The first diagnostics release recorded an 87.779-second application run, including source
fetches. Run times vary with upstream latency; this single observation is not a monthly cost.
The $2–$5 planning allowance below remains an estimate, and the $25 budget remains an alert.

## Earlier measurements

Updated 20 September 2026 in US East (N. Virginia). Cost Explorer now reports **$0.23494 account-wide unblended cost** for September 1–19 (September 20 end-exclusive), marked **Estimated**. This is a partial-month account measurement, not a finalized invoice or a project-only allocation. It includes $0.20607 Glue, $0.01842 S3, $0.01 tax, and small other charges. It must not be extrapolated as a complete monthly bill.

The daily NYC forecast ran automatically on September 20: 7.090 seconds execution, 7.411 seconds billed, 512 MB configured, 105 MB peak memory. At $0.0000166667 per GB-second, 31 similar invocations cost about **$0.0019/month in Lambda compute alone**, before free allowances. Requests, monitoring, logs, storage, and website delivery are additional. The historical resolution model trains locally and uses static browser inference.

## Observed usage

The upgraded initial and incremental Glue jobs each used two G.1X workers for 132 seconds, with 264 reported DPU-seconds. At $0.44 per DPU-hour, that is approximately **$0.0323 per successful run**. The controlled failure used 89 seconds / 178 DPU-seconds, approximately $0.0218. Duplicate requests skipped Glue entirely.

The three most recent successful jobs, including one earlier 156-second job, produced these projections:

| Scenario | Projected Glue compute per month |
|---|---:|
| Weekly processing, 52/12 runs | $0.148 |
| Weekly processing plus 8 full releases and 2 exercises | $0.491 |

Measured S3 content, including versions, totaled approximately 151.4 MB across the data and website buckets. Three independent Athena verification queries scanned 427,780 bytes in total; Athena's per-query minimum billing still applies.

## Planning allowance

Use **$2–$5/month** as a conservative allowance for small demonstration traffic, not as a measured bill or guarantee. Assumptions: weekly processing, about eight development releases, two exercises, under 1 GB of storage, modest logs, a handful of alarms, daily short forecast runs, occasional Athena queries, and about 10,000 lightweight website visits or fewer. Public traffic and frequent rebuilds are variable costs.

No always-running EC2 server, NAT gateway, database server, or paid BI subscription is used. The CloudFront address requires no domain purchase. A custom domain would have separate registration costs; Route 53 is optional.

The account-wide $25 monthly budget alerts above 50% actual spend and above 100% forecast spend. It includes unrelated account usage and **does not impose a hard cap**. Do not label all account spend as this project's cost.

## Monitoring extension

September 21's scheduled forecast with weather/calendar evaluation used 38.403 seconds of execution, 38.778 billed seconds and 512 MB, with 107 MB peak memory. At the same Lambda rate above, 31 such invocations would be about $0.01 in compute alone. This is one observed run, not a monthly bill. The new page-view API and coverage alarm add request and monitoring charges; see [collection limits and pricing assumptions](forecast-monitoring.md#operation-and-cost). The $2–$5 planning allowance remains conditional on modest traffic and should be checked against actual billing.

## Measure again

Run `python scripts/measure_cost.py` with the authorized `serviceops` profile. It records execution times, AWS-reported DPU-seconds, versioned S3 storage, and available billing data in `build/cost-measurement.json`. Recalculate after meaningful workload changes.

Controls include two fixed workers, one concurrent Glue job, a ten-minute Glue timeout, a twenty-minute workflow timeout, no automatic Glue retries, a 100 MiB Athena scan limit, fourteen-day coordinator logs, seven-day query results, and expiration of old object versions. Current snapshot prefixes are retained for audit and need periodic storage review.

Disable scheduled processing with `python scripts/deploy.py disable`; the website continues serving the last successful report.

## Pricing references

- [AWS Glue pricing](https://aws.amazon.com/glue/pricing/)
- [Athena pricing and minimum billing](https://aws.amazon.com/athena/pricing/)
- [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)
- [S3 pricing](https://aws.amazon.com/s3/pricing/)

Rates and account allowances may change. Credits and free tiers are not required for the Glue compute calculation above.

- [AWS Lambda pricing](https://aws.amazon.com/lambda/pricing/)
