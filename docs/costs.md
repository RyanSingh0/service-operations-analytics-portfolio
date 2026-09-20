# Measured usage and monthly estimate

Measured 18 September 2026 in US East (N. Virginia). **This is a usage-based projection, not an invoice.** AWS Cost Explorer returned `DataUnavailableException`; billed monthly cost cannot yet be verified.

## Observed usage

The upgraded initial and incremental Glue jobs each used two G.1X workers for 132 seconds, with 264 reported DPU-seconds. At $0.44 per DPU-hour, that is approximately **$0.0323 per successful run**. The controlled failure used 89 seconds / 178 DPU-seconds, approximately $0.0218. Duplicate requests skipped Glue entirely.

The three most recent successful jobs, including one earlier 156-second job, produced these projections:

| Scenario | Projected Glue compute per month |
|---|---:|
| Weekly processing, 52/12 runs | $0.148 |
| Weekly processing plus 8 full releases and 2 exercises | $0.491 |

Measured S3 content, including versions, totaled approximately 151.4 MB across the data and website buckets. Three independent Athena verification queries scanned 427,780 bytes in total; Athena's per-query minimum billing still applies.

## Planning allowance

Use **$2–$5/month** as a conservative allowance for small demonstration traffic, not as a measured bill or guarantee. Assumptions: weekly processing, about eight development releases, two exercises, under 1 GB of storage, modest logs, a handful of alarms, occasional Athena queries, and about 10,000 lightweight website visits or fewer. Public traffic and frequent rebuilds are variable costs.

No always-running EC2 server, NAT gateway, database server, or paid BI subscription is used. The CloudFront address requires no domain purchase. A custom domain would have separate registration costs; Route 53 is optional.

The account-wide $25 monthly budget alerts above 50% actual spend and above 100% forecast spend. It includes unrelated account usage and **does not impose a hard cap**. Do not label all account spend as this project's cost.

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
