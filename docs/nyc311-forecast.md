# NYC 311 demand forecasting

This extension forecasts recorded daily NYC 311 service requests. It preserves the separate historical IT incident dashboard and uses a current public source with daily publication. It does not claim to stream events in real time.

## Source and ingestion

Source: [NYC Open Data — 311 Service Requests from 2020 to Present](https://data.cityofnewyork.us/d/erm2-nwe9). The public Socrata resource endpoint supports the aggregate queries used here without a paid account. Anonymous API limits and availability can change; no availability guarantee is assumed.

The first inspected extract contained requests through September 18, 2026. Its latest date was partial, so the model uses complete dates through September 17. Two years of daily history provide 730 observations per borough and city series. Dates retain the source's New York local calendar; no UTC conversion is applied to source floating timestamps.

The extractor uses SoQL, the source API's SQL-like query language:

```sql
SELECT date_trunc_ymd(created_date) AS day, borough, count(*) AS requests
WHERE created_date >= :start AND created_date < :end
GROUP BY day, borough
ORDER BY day, borough
```

Date parameters are generated from validated dates, not visitor input. Requests retrieve aggregates only: no addresses, coordinates, names, or complaint descriptions. The count is a count of source rows grouped by date/borough; request-level identifier uniqueness is owned by the source publisher and is not independently audited by this aggregate-only extractor.

Missing borough-days fail publication instead of becoming fabricated zeros. Duplicate date/borough aggregate keys, nonpositive or malformed counts, out-of-range dates, a regressing cutoff, a source more than seven days behind, or possible query truncation also fail the run. The five borough series must be present for every date. City totals include unspecified/unknown borough rows and reconcile to known boroughs plus unknown counts.

Daily updates reread the most recent 60 days to absorb revisions. A full two-year refresh every 30 days catches older corrections. This means older corrections may take up to 30 days to enter the model. Immutable attempt reports retain source metadata and fingerprints; the private cached source is the latest aggregate window.

## Model and evaluation contract

Target: requests created on each of the 14 dates after the latest complete data date, for each borough and NYC total. The publication lag means the first forecast dates may already be in the past at viewing time; these are nowcasts, clearly disclosed by the page.

Candidates:

1. Last available matching weekday.
2. Mean of the four previous available matching weekdays.
3. Ridge-regularized seasonal regression, with a fixed penalty of 8. Features include four available matching-weekday counts, trailing seven- and 28-day means, weekday and day-of-year sine/cosine terms, and forecast horizon. Count features and target are scaled using the training mean. The intercept is effectively unpenalized.

The regression uses weekly historical forecast origins and pools horizons 1–14. Every feature is available at its origin, and every training label precedes the training boundary. A small pivoted linear-system solver makes this model reproducible with the Python standard library; no managed model endpoint or heavyweight ML runtime is needed. This is a transparent regularized regression, not a deep-learning model.

The final 112 historical days are divided chronologically into 28 selection days, 42 calibration days, and 42 untouched test days. Each evaluation uses disjoint 14-day forecast blocks. Forecasts within a block do not consume later actuals; the next block can use observations that would then be historical. Regression must beat the better baseline's selection MAE by at least 2% to be selected. The choice is frozen before calibration and testing.

After selection, the regression is refitted using only data before the calibration boundary. Its coefficients remain frozen throughout calibration and test. Calibration supplies a pooled, approximately 90th-percentile absolute-error radius across the 42 dates and all horizons. The same band is evaluated on untouched test dates. Final production coefficients are then refitted on all observed data. The earlier calibration radius is reused; refitting, autocorrelation, drift, and a small calibration sample limit its interpretation. It is an empirical error band, not a guaranteed or horizon-specific confidence interval.

MAE measures requests/day. WAPE is `sum(abs(actual - forecast)) / sum(actual) * 100`, not a percentage of correctly predicted requests. Band coverage is the percentage of test actuals inside their unrounded predicted error bands.

## Initial results

Selection: May 29–June 25, 2026. Calibration: June 26–August 6. Untouched test: August 7–September 17. Results below will change with new data.

| Series | Selected model | Test MAE | Test WAPE | Band coverage |
|---|---|---:|---:|---:|
| Bronx | Four-week mean | 128.42 | 6.36% | 100% |
| Brooklyn | Four-week mean | 200.08 | 5.83% | 97.6% |
| Manhattan | Seasonal regression | 143.28 | 6.90% | 78.6% |
| Queens | Seasonal regression | 128.70 | 4.77% | 92.9% |
| Staten Island | Four-week mean | 30.61 | 7.27% | 100% |
| NYC total | Four-week mean | 453.11 | 4.25% | 97.6% |

Manhattan's band undercovers relative to the nominal 90% target. The interface reports this limitation. Model selection is based on the earlier selection period; another candidate can perform better in the final test without being substituted after seeing test results.

Backtests use the current revised source extract. Historical publication vintages, reporting delays, and exact information availability are unavailable, so this is a retrospective chronological evaluation, not a fully point-in-time replay of the city's publication system. Holidays and weather are not modeled explicitly. Each series is fitted separately; forecasts are not constrained to sum across boroughs.

## Interactive use

The public page provides borough and horizon selectors, observed/forecast charts, error bands, a candidate comparison, daily predictions, CSV/JSON downloads, and a capacity scenario. The capacity slider changes the arithmetic comparison with expected arrivals; it does not retrain or change the model. Positive daily excesses are summed without existing backlog or carryover, so this is not a staffing optimization or a forecast of operational backlog.

Visitors read static published results and never trigger compute or supply data to the training job. The forecast function has no public URL or API. Source data and forecasting artifacts remain isolated from IT incident records.

## Run locally

```powershell
./.venv/Scripts/python scripts/forecast.py --refresh
./.venv/Scripts/python -m http.server 8767 --bind 127.0.0.1 --directory build/forecast
```

Without `--refresh`, the script reuses `build/forecast/source.json`. Local execution uses the same model code as AWS. Inspect `report.json` for coefficients, training cutoff, source metadata, model comparisons, and test predictions.

## Deployment and recovery

`scripts/deploy_forecast.py --enable` provisions the forecast stack, performs a cloud release/smoke run, and enables its daily 18:00 UTC schedule after success. Infrastructure creation and current forecast application releases require an authorized administrator. The worker reads public aggregate queries, retrains/evaluates, and publishes one aggregate JSON object to the existing private website origin. The September 20 scheduled execution succeeded without an interactive login and advanced the data cutoff to September 18.

The worker holds a 20-minute DynamoDB lease on `forecast-lock`, independent of the IT pipeline's lock. Its maximum execution time is 15 minutes. Ownership is checked before publication and conditional cleanup prevents releasing another run's lock. The AWS account's low concurrency quota makes an application lease preferable to reserving Lambda capacity here.

Failures before publication preserve the previous public forecast. The source cache, private attempt report, public object, and monitoring metric are not one transaction. Repeating a failed run safely rebuilds and republishes; an error after the public object is written may leave a successful report despite a failed execution. Inspect the public generation timestamp and worker logs before concluding that no publication occurred.

CloudWatch watches worker errors and missing publication across two daily periods. The website also flags reports older than three days or source dates more than seven days behind. Alerts use the existing SNS email subscription, which requires recipient confirmation. The schedule uses the Lambda execution role and does not depend on a personal AWS login.

GitHub's forecast workflow validates the whole project. Its release job is disabled unless `ENABLE_FORECAST_RELEASE=true` and an AWS role is configured. The currently deployed IT release role does not have forecast release permissions; the checked-in IAM template retains that boundary. Before enabling this optional release job, an administrator must explicitly authorize configuration-read, code-update, and invoke permissions on the forecast function, writes to the two forecast page assets, and reads of the public forecast JSON. The deployment role cannot change infrastructure or its own IAM permissions. The deployed daily forecast runtime does not depend on enabling GitHub releases. A simultaneous daily run can hold the lease and cause a release smoke check to fail; retry after that run completes.

## Cost and future work

Daily extraction/modeling runs on a 512 MB Lambda rather than an always-running Spark cluster. A full 15-minute invocation consumes 450 GB-seconds; 31 such runs would consume 13,950 GB-seconds before any release runs. Normal cached refreshes should be much shorter; use measured Lambda REPORT lines before claiming a bill. Public API access is free, while Lambda, logs, alarms, storage, and CDN traffic incur AWS usage. The existing $25 account budget remains an alert, not a hard cap.

The IT pipeline already demonstrates PySpark and Spark SQL. This small aggregate forecasting workload does not benefit from an always-on Spark streaming job. A future true streaming extension needs a source that actually emits timely events, event-time watermarks, deduplication, checkpoint recovery, and an independently measured cost budget. Polling daily NYC data more frequently would not make its source real time.

References: [NYC dataset changes](https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates), [Socrata query documentation](https://dev.socrata.com/docs/queries/), [rolling-origin evaluation](https://otexts.com/fpp3/tscv.html).
