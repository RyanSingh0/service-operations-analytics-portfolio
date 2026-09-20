# Forecast feasibility assessment

This is a feasibility and baseline evaluation, not a deployed prediction service. Reproduce it with `python scripts/profile_history.py` after downloading the source.

## Measured coverage

- Audit updates: 29 February 2016 through 18 February 2017, spanning 356 calendar days.
- Incident openings: 29 February 2016 through 16 February 2017, spanning 354 days.
- 207 days contain an opening; 147 dates inside that window contain no recorded openings.
- February through May 2016 contains 24,644 of 24,918 incidents, approximately 98.9%.
- Monthly counts then collapse: June has 5, July 14, August 15, September 12, October 16, November 26, December 37, January 2017 has 94, and February 55.

The calendar span is not a year of consistently sampled demand. Missing arrivals could reflect extraction coverage rather than a real collapse in support workload. No cause can be inferred from this file alone.

## Baseline experiment

Walk-forward evaluation used the last 30% of the opening-date range (107 days, starting 2 November 2016). Each prediction used only earlier actual observations. No dates after the last observed opening were fabricated as zero demand.

| Baseline | MAE, incidents/day |
|---|---:|
| Same weekday last week | 1.748 |
| Mean of four previous matching weekdays | 1.449 |
| Previous seven-day mean | 1.745 |
| Always zero, diagnostic control | 1.953 |

The evaluation period averages only 1.953 recorded arrivals/day. Small absolute errors are largely a consequence of the sparse tail. They are not evidence that a model can forecast the much busier March–May period. Do not report these results as production forecasting accuracy.

## Recommended modeling direction

An incident-level resolution-time study is more plausible than a headline year-long arrival forecast, but needs a separate evaluation contract:

1. Choose a prediction point: first observed event, or a fixed elapsed-time landmark such as four hours. Define features available by that point.
2. Exclude future state, final resolution timestamps as features, final reassignment/reopening counts, and information copied from later records.
3. Split by incident and calendar time, keeping all observations of one incident in one split. Apply any tuning only to earlier data.
4. Treat still-open incidents as right-censored. Dropping them silently creates selection bias. Either use a survival formulation or explicitly limit a first study to a documented closed cohort with a fixed follow-up window.
5. Start with a training-set median baseline and a priority-conditioned median baseline before fitting a more complex model.
6. Evaluate absolute error and error by priority, with censored-case treatment documented. Audit drift and coverage before deploying predictions.

A narrow arrival study within the dense March–May window could still be educational, but roughly thirteen weeks is weak evidence for stable seasonality or generalization. A real demand forecast needs longer, consistently collected history.
