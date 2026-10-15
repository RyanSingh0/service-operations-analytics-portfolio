"""Recent out-of-sample residuals for horizon-specific demand bands."""
import math
from statistics import mean

WINDOW = 84
GROUPS = ((1, 7), (8, 14))
METHOD = 'rolling-84-horizon-v1'


def quantile(errors, nominal=.9):
    if not errors or not 0 < nominal < 1 or any(not math.isfinite(e) or e < 0 for e in errors):
        raise ValueError('Invalid calibration errors or nominal level')
    ordered = sorted(errors)
    return ordered[min(len(ordered)-1, math.ceil((len(ordered)+1)*nominal)-1)]


def calibrate(name, values, days, end):
    from serviceforecast.model import evaluate, fit

    start = end-WINDOW
    if start < 180 or end > len(values):
        raise ValueError('Calibration requires 180 training days and 84 residual days')
    rows = []
    for first in range(start, end, 14):
        fitted = fit(values, days, first) if name == 'seasonal_ridge' else {'training_through': days[first-1].isoformat()}
        rows.extend(evaluate(name, values, days, first, first+14, fitted))
    groups = []
    for low, high in GROUPS:
        errors = [abs(r['actual']-r['predicted']) for r in rows if low <= r['horizon'] <= high]
        groups.append({'horizon_start': low, 'horizon_end': high, 'residuals': len(errors),
                       'half_width': quantile(errors)})
    return {'method': METHOD, 'nominal_pct': 90, 'calibration_start': days[start].isoformat(),
            'calibration_end': days[end-1].isoformat(), 'calibration_days': WINDOW, 'groups': groups,
            'interpretation': '84 recent out-of-sample dates; expanding refits every 14 days; separate widths '
                              'for source horizons 1–7 and 8–14. Revised historical data and dependent errors '
                              'mean nominal coverage is not guaranteed.'}


def bounds(prediction, horizon, interval):
    for group in interval['groups']:
        if group['horizon_start'] <= horizon <= group['horizon_end']:
            width = group['half_width']
            return max(0.0, prediction-width), prediction+width
    raise ValueError('Unsupported interval horizon')


def score(rows):
    if not rows:
        raise ValueError('No interval predictions')
    return {'predictions': len(rows), 'distinct_target_dates': len({r['date'] for r in rows}),
            'coverage_pct': round(100*mean(r['lower'] <= r['actual'] <= r['upper'] for r in rows), 1),
            'mean_width': round(mean(r['upper']-r['lower'] for r in rows), 2),
            'mean_interval_score': round(mean(r['upper']-r['lower'] + 20*max(r['lower']-r['actual'], 0)
                                              + 20*max(r['actual']-r['upper'], 0) for r in rows), 2)}


def compare(name, values, days, start, end):
    """Hold point predictions fixed while comparing old and recent calibration."""
    from serviceforecast.model import evaluate, fit, predict

    old_rows, new_rows = [], []
    for first in range(start, end, 14):
        fitted = fit(values, days, first)
        old_fit = fit(values, days, first-84)
        old_cal = evaluate(name, values, days, first-84, first-42, old_fit)
        width = quantile([abs(r['actual']-r['predicted']) for r in old_cal])
        interval = calibrate(name, values, days, first)
        # A two-day publication lag leaves horizons 3–14 genuinely in the future.
        for index in range(first+2, min(first+14, end)):
            horizon = index-first+1
            point = predict(name, values[:first], days, first-1, horizon, fitted)
            base = {'date': days[index].isoformat(), 'origin': days[first-1].isoformat(),
                    'actual': values[index], 'predicted': point, 'horizon': horizon}
            old_rows.append({**base, 'lower': max(0, point-width), 'upper': point+width})
            lower, upper = bounds(point, horizon, interval)
            new_rows.append({**base, 'lower': lower, 'upper': upper})
    return {'reference': score(old_rows), 'recent': score(new_rows),
            'method': 'Retrospective band comparison on shared point forecasts; selection frozen before test; '
                      'refits and calibration use only data before each origin; two-day publication lag. '
                      'Uses revised source data, not historical publication vintages.'}
