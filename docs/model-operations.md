# Forecast promotion and recovery policy

The daily job refreshes data, selects among the existing demand models using an earlier
set of three 28-day validation windows, publishes a forecast, and preserves future predictions for scoring.
The weather/calendar model is a shadow challenger. It cannot be selected automatically.
This policy governs a reviewed change to that eligibility, not daily baseline selection.

Daily selection starts from the four-week mean. Same-weekday, then seasonal regression, must each beat their reference by at least 2% pooled MAE and win at least two of the three windows. This does not use the subsequent calibration or test targets. The published per-window scores and gate outcomes explain the choice. It reduces dependence on one month; it does not guarantee stability or future accuracy.

## Promotion gate

Evaluate each borough independently on four consecutive, complete target weeks after
actuals have matured by seven days beyond the source cutoff. Compare champion and
challenger on exactly the same published issue/target pairs; require all seven distinct
target dates in each week. Missing predictions invalidate that week's comparison.
Require challenger WAPE at least 2% lower relative to champion in each of the four weeks.
If champion error is zero, no relative improvement is established.

Before promotion, calibrate challenger bands on a separate earlier window and validate
at least 85% coverage on the prospective four-week cohort. Currently, the ledger saves
challenger point forecasts, not challenger bands: this coverage gate is not yet measurable
and promotion remains blocked until that evidence exists. Retrospective results alone
do not satisfy the gate. Review reporting changes, revision rates, subgroup errors, latency,
and missing weather before approving a versioned release. Preserve the previous artifact.

## Coverage escalation and recovery

The implemented warning uses the rolling scored cohort, at least 28 predictions across
14 distinct target dates, and coverage below 80%. It emits the existing Undercoverage
metric and feeds the existing alarm. Email delivery requires a confirmed subscription.
No automatic fallback or sustained-warning counter is implemented.

Operating rule: if the warning persists on 14 consecutive daily publications with new
eligible observations, the maintainer should investigate and release the four-week mean
with freshly calibrated bands from a separate earlier window. Do not reuse the failed
model's band. If four-week mean is already selected, focus on interval recalibration,
data corrections and source changes; switching to the same model is not a recovery.
Record the evidence, decision, model version, and next review date in a release note.
Until a reviewed recovery is released, retain the visible warning; do not imply confidence.

## What the charts measure

The [October 14 incident record](releases/2026-10-14-coverage.md) documents a shadow calibration experiment and its prospective promotion criteria. It does not change the existing warning threshold or enable automatic fallback. Outcome cohorts separate model versions while retaining overall historical warnings. Current displayed bands still use the original calibration method; shadow bounds are logged and scored only for issues actually published with them.

- Calibration curve: widths estimated at six nominal levels on 42 earlier calibration
  dates, evaluated on 42 held-out dates. Dependence and small samples limit inference.
- Heatmap and retrospective weekly line: daily origins with an assumed two-day publication
  delay, only pre-origin demand features, frozen pre-test model/selection, current revised
  extract. Only leads 1–12 remain in a 14-day forecast. Historical vintages are unavailable.
- Published monitoring: first successful public issue per New York date, future targets only,
  frozen mature actuals. Retrospective rows are never inserted into this ledger.
- Run health: up to 30 application attempts, including recorded failures and started-only
  unknown outcomes. Success denominator includes completed attempts only. p50/p95 use
  nearest rank on completed durations. Current invocation appears on the next publication.
  Lease rejections, platform failures before recording, and telemetry write failures are
  not complete Lambda availability monitoring; CloudWatch remains the operational source.

Shared chart assets and the forecast worker are deployed through the existing manual
release path. The GitHub OIDC role remains scoped to the existing incident pipeline;
it is not silently widened to grant forecast or website-wide deployment rights.
