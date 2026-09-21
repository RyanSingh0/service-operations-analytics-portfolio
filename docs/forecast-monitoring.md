# Forecast operations and usage measurement

The daily job publishes three kinds of evidence together: the current demand forecast, outcomes of previously published forecasts, and aggregate website page views. Retrospective model evaluation remains separate from prospective operating history.

## Published forecasts and delayed actuals

After the public report write succeeds, the worker records the first successful forecast issue for that New York calendar day. Repeated releases do not replace that issue. Targets on or before the issue date are nowcasts and are excluded from prospective scoring. Lead time is measured from the issue date, rather than the older source cutoff.

The worker scores a target once its date is at least seven days behind the latest complete source cutoff. It freezes the actual value and source fingerprint at that point. This gives corrections time to arrive without allowing later revisions to silently rewrite published performance. The seven-day rule reduces revision sensitivity; it does not prove the source is final.

The rolling state retains 120 days of issues and frozen actuals. The dashboard displays the most recent eight weeks of target dates, with WAPE, empirical band coverage, forecast counts and distinct target-date counts. Multiple origins can forecast the same target, so these errors are dependent. Lead-time bands of 1–3, 4–7 and 8–14 days expose some of that mixture. Archived attempt reports preserve the original daily candidate predictions under unique S3 keys.

A coverage warning requires at least 28 scored predictions across 14 target dates and coverage below 80% for a nominal 90% band. This is an investigation threshold, not a hypothesis test. The worker emits a ServiceForecast/Undercoverage metric and a CloudWatch alarm uses the existing notification topic. The page also flags retrospective coverage below 80%, including Manhattan's current weak bands, without presenting that backtest as operating history.

Monitoring starts with deployment; no historical operating record is fabricated from backtests or unverified old attempts. The graph initially says it is collecting outcomes. Public publication and monitoring-state persistence are not a single transaction. A failure after the public write but before state persistence can leave an untracked issue; that execution fails visibly and must be investigated. Retrying does not backdate the issue.

## Demand shifts and source revisions

Each run compares overlapping city-total source dates with the previous extract. It reports changed dates, absolute revisions and signed revisions. These are revisions to recorded requests, not evidence that community needs changed. Counts may be affected by access to reporting channels, classification, administrative changes or corrections.

The page reports the percentage change between the latest 28-day mean and the preceding 28-day mean and flags absolute shifts above 30%. Both windows contain four of every weekday. Seasonality, holidays and genuine demand can still explain a flag. It is a distribution-change diagnostic, not proof of model concept drift or a causal explanation.

[NYC's dataset update notice](https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates) documents changes in the public reporting system. The pipeline keeps source identifiers and definitions explicit, checks coverage, and fails malformed aggregates. It does not automatically infer the causal impact of reporting-policy changes.

## Weather and calendar challenger

An experimental ridge model adds federal-holiday, before-holiday and after-holiday indicators, plus a seven-day mean of temperature and precipitation ending five days before the demand origin. Holidays are known in advance. Weather comes from the Open-Meteo ERA5 reanalysis at a central NYC grid cell; no realized weather from the forecast period enters the features.

Reanalysis is revised and this is not a reconstruction of historically available weather vintages. The extra lag is a conservative availability assumption. One grid cell cannot represent every borough's conditions. Current weather forecasts are not used as if they were known historical observations. Open-Meteo's [Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api) offers archived forecast lead times of 1–7 days; integrating a suitable issue-time archive across the full horizon is a separate experiment.

The challenger is trained and evaluated using the same temporal boundaries as the demand regression and is logged for future prospective comparison. It is deliberately ineligible for automatic promotion: it was introduced after the original test period had already been inspected. Its retrospective scores are exploratory rather than a new untouched holdout claim.

September 21 extract, demand through September 19, weather through September 14:

| Series | Selected model test WAPE | Weather/calendar challenger WAPE |
|---|---:|---:|
| Bronx | 6.55% | 10.66% |
| Brooklyn | 5.83% | 9.05% |
| Manhattan | 7.64% | 7.96% |
| Queens | 5.33% | 5.62% |
| Staten Island | 7.64% | 13.56% |
| NYC total | 4.66% | 5.52% |

The added features did not improve these results. Weather can affect requests, but this representation and window did not earn promotion. A useful next study would separate complaint categories, use issue-time weather forecasts, and preregister future evaluation dates. Reporting volume alone does not measure staffing requirements or service quality.

Weather data: [Open-Meteo historical API](https://open-meteo.com/en/docs/historical-weather-api), [attribution and terms](https://open-meteo.com/en/terms). Noncommercial public access is used; availability is not guaranteed. If optional weather retrieval fails, validated core demand forecasts continue and the page labels the challenger unavailable.

## Anonymous page views

Each production dashboard sends one small page identifier on load. Refreshes of the data do not emit another view. Do Not Track and Global Privacy Control are respected. No cookies, visitor IDs, IP addresses, full URLs, referrers or form inputs are persisted by this collector. AWS handles ordinary request transport; application access logging is not enabled and the handler does not log request bodies or headers.

The table stores one UTC-day item with counts for IT, forecasting and resolution pages. Items expire after 90 days. The daily forecast job reads up to 28 closed UTC dates and includes the summary in the same public forecast JSON. It excludes the current day. Collection began partway through September 21, so that first date contains only post-deployment views. Missing or failed usage retrieval is shown as unavailable, not zero.

These are accepted page-view signals, not distinct people, sessions, customers or business adoption. Repeats, maintainers and bots may count. Blocked scripts and throttled requests may be missed. Origin checks and CORS are not authentication and cannot stop a determined client from spoofing a beacon. The interface states these limits; no usage is backfilled before collection began.

The POST-only HTTP API throttles to one request per second with burst two. The handler caps accepted daily increments at 10,000. These reduce processing and counter inflation; they are not a hard billing cap. The API has no route to read or change source data, model files, deployment permissions or individual records. The collector role can only update its dedicated count table and write its own logs. The forecast role can only batch-read that table.

## Operation and cost

`python scripts/deploy_monitoring.py` provisions the counter, updates the exact allowed website connection origin, adds the forecast table-read permission and coverage alarm, then performs a publication check. It preserves the current forecast schedule state and refuses to begin while a forecast lease is active. This is an administrator operation; GitHub's deployment role is unchanged.

At small demonstration traffic, the counter is request-priced and has no always-on server. At the published $1/million HTTP API request tier, 10,000 API requests are about $0.01 for API requests alone, excluding Lambda, DynamoDB, monitoring and delivery. [AWS HTTP API pricing](https://aws.amazon.com/api-gateway/pricing/). Retain the existing modest-traffic planning allowance and inspect account billing after deployment; public traffic and abuse are variable and the $25 budget only alerts.
