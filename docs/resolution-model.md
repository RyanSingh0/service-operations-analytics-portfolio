# First-resolution survival model

This historical research model estimates time from an incident's first observed nonterminal audit event to its first subsequent observed Resolved or Closed state, within 168 hours. It does not use the analytics dashboard's latest closing-cycle target, and it is not validated for current enterprise incidents.

## Cohort and prediction moment

Features come only from the first observation: priority, contact type, category, weekday, six-hour time band, and whether the incident was first observed within one hour or within 1–24 hours of opening. Final resolution timestamps, final reassignment/reopening counts, future states, and later ownership are excluded. The prediction point is observation time, not necessarily ticket creation.

The model excludes first observations already terminal, first observations more than 24 hours after opening, and records with no positive observed follow-up. Exclusion counts are in the downloadable artifact. These choices restrict generalization; the model is not representative of every source incident.

An unresolved case is right-censored at its last observed audit timestamp. It is not marked resolved or silently discarded. Cases followed beyond seven days are administratively censored at 168 hours for this restricted target. First resolutions after seven days establish survival through the horizon but do not become in-horizon events. Last-observation censoring is conservative about source coverage, but can be informative: cases with sparse audit activity may differ from other incidents.

## Chronological separation

| Split | First observation dates | Latest permitted outcome observation | Included incidents |
|---|---|---|---:|
| Training | February 29–March 31, 2016 | March 31 | 7,913 |
| Selection | April 1–14 | April 30 | 3,741 |
| Test | May 1–14 | May 31 | 3,496 |

No incident appears in two splits. Training labels are censored using only the March snapshot; future resolutions cannot enter training. The model is selected on April outcomes and evaluated on May outcomes. The final published model remains the same training fit used for evaluation; it is not refitted on the test cases.

The model dataset uses later historical observations than the IT dashboard's current replay cutoff. It is a separate fixed research study, clearly labeled, and never changes earlier dashboard metrics.

## Models

The pooled and priority-conditioned Kaplan–Meier curves provide censor-aware median baselines and survival-probability baselines. A median beyond the seven-day horizon is shown as beyond seven days, rather than invented.

The learned model is a piecewise-exponential hazard model. Intervals are 0–1, 1–4, 4–12, 12–24, 24–48, 48–72, and 72–168 hours. Each at-risk interval contributes its exact observed exposure, including partial exposure before censoring. A regularized Poisson regression fits event rates with exposure weights. One-hot interval terms define the baseline hazard, and first-observation features modify the rate. The intercept and coefficients are exported to JSON for deterministic browser inference; there is no public Python or pickle endpoint.

For rate lambda in an interval, survival evolves as `S(t + dt) = S(t) * exp(-lambda * dt)`. The survival curve is nonincreasing. The median is the first time survival reaches 0.5. Browser and Python implementations are checked on common inputs.

## Selection and honest results

Selection uses the mean inverse-probability-of-censoring weighted (IPCW) Brier score at 4, 12, 24, 48, 72, and 168 hours. This is an average over specified horizons, not a continuous integrated Brier score. The learned model must improve the better baseline's selection score by at least 2%.

The censoring distribution is estimated on training cases. Event contributions use the probability of remaining uncensored just before their event time. A case known unresolved through an evaluation horizon uses censoring support just before that horizon, so administrative censoring at 168 hours does not incorrectly erase the endpoint. Unstable censoring support prevents reporting the affected score. IPCW assumes independent censoring; source audit behavior may violate that assumption, so the score is assumption-sensitive.

| Candidate | Selection mean IPCW Brier | Test mean IPCW Brier | Observed-event median MAE |
|---|---:|---:|---:|
| Pooled Kaplan–Meier | 0.26229 | 0.27427 | 47.25 h |
| Priority Kaplan–Meier | 0.26223 | 0.27417 | 47.74 h |
| Piecewise hazard | 0.24723 | 0.26013 | 47.71 h |

The hazard model is selected and improves test probability error by about 5.1% relative to the priority baseline. It **does not improve median time MAE over the pooled baseline**. MAE is conditional on 2,953 observed first resolutions within seven days; it excludes censored and longer cases and caps predicted medians at seven days. It is not an all-case duration error. The test set also has 90 cases censored before seven days and 453 cases observed unresolved through that horizon.

The artifact and public page report errors by priority with sample sizes. Small priority groups are unstable; an overall improvement does not establish improvement for every priority. No calibrated individual prediction interval, business savings, SLA guarantee, or present-day operational accuracy is claimed.

## Reproduce and inspect

```powershell
./.venv/Scripts/python -m pip install -e ".[dev,aws,ml]"
./.venv/Scripts/python scripts/train_resolution.py
```

Versioned artifacts are saved under `build/resolution/<version>/`. The version hashes the source fingerprint and training/model code. The JSON records coefficients, support categories, runtime versions, cohort boundaries, exclusions, baseline comparisons, per-priority metrics, and feature-distribution drift. Incident split membership is retained locally as Parquet for leakage checks and is not published. The public model report contains no incident identifiers.

Distribution checks report training/test total variation and unseen-category fractions. They are measured drift diagnostics, not a production concept-drift guarantee. Historical source data is fixed, so repeated weekly retraining on the same full extract would add no new evidence. Retrain intentionally when the feature contract or data changes; preserve the prior version and repeat chronological evaluation.

Training is local. Inference runs entirely in the browser against a versioned static artifact, keeping marginal inference infrastructure cost at zero beyond ordinary website traffic. This complements the separate daily NYC 311 pipeline, which demonstrates current-source refresh, automatic retraining, and monitored publication.

References: [UCI source](https://doi.org/10.24432/C57S4H), [censor-aware evaluation](https://scikit-survival.readthedocs.io/en/stable/user_guide/evaluating-survival-models.html), [scikit-learn Poisson regression](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.PoissonRegressor.html).
