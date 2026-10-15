import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from serviceforecast.weather import extra_features
from serviceforecast.diagnostics import diagnostics
from serviceforecast.intervals import bounds, calibrate

HORIZON = 14
CANDIDATES = ('same_weekday', 'four_week_mean', 'seasonal_ridge')
VERSION = 'seasonal-demand-v4-walk-forward'
SELECTION_FOLDS = 3
SELECTION_DAYS = 28
MIN_IMPROVEMENT = .02


def seasonal_values(values, origin, horizon):
    index = origin + horizon - 7 * math.ceil(horizon / 7)
    return [values[index - 7 * k] for k in range(4)]


def features(values, days, origin, horizon, scale, weather=None):
    target = days[origin] + timedelta(days=horizon)
    lags = seasonal_values(values, origin, horizon)
    result = [1.0, *[v/scale for v in lags], mean(values[origin-6:origin+1])/scale,
            mean(values[origin-27:origin+1])/scale,
            math.sin(2*math.pi*target.weekday()/7), math.cos(2*math.pi*target.weekday()/7),
            math.sin(2*math.pi*target.timetuple().tm_yday/365.25),
            math.cos(2*math.pi*target.timetuple().tm_yday/365.25), horizon/HORIZON]
    return result + extra_features(days, origin, horizon, weather) if weather else result


def solve(matrix, vector):
    a = [row[:] + [value] for row, value in zip(matrix, vector)]
    n = len(a)
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        a[col], a[pivot] = a[pivot], a[col]
        if abs(a[col][col]) < 1e-12:
            raise ValueError('Singular regression system')
        divisor = a[col][col]
        a[col] = [v/divisor for v in a[col]]
        for row in range(n):
            if row == col:
                continue
            multiplier = a[row][col]
            a[row] = [v-multiplier*p for v, p in zip(a[row], a[col])]
    return [row[-1] for row in a]


def fit(values, days, end, weather=None):
    if end < 180:
        raise ValueError('At least 180 training days required')
    scale = max(1.0, mean(values[:end]))
    size = 17 if weather else 12
    matrix = [[0.0]*size for _ in range(size)]
    vector = [0.0]*size
    samples = 0
    # Weekly origins limit redundant overlapping labels; every target is before end.
    for origin in range(55, end-HORIZON, 7):
        for horizon in range(1, HORIZON+1):
            x = features(values, days, origin, horizon, scale, weather)
            target = values[origin+horizon]/scale
            for i in range(size):
                vector[i] += x[i]*target
                for j in range(size):
                    matrix[i][j] += x[i]*x[j]
            samples += 1
    for i in range(size):
        matrix[i][i] += 1e-8 if i == 0 else 8.0
    return {'coefficients': solve(matrix, vector), 'scale': scale, 'training_days': end,
            'training_through': days[end-1].isoformat(), 'samples': samples, 'ridge_penalty': 8.0}


def predict(name, values, days, origin, horizon, fitted, weather=None):
    if origin < 27 or not 1 <= horizon <= HORIZON:
        raise ValueError('Unsupported forecast origin or horizon')
    lags = seasonal_values(values, origin, horizon)
    if name == 'same_weekday':
        return float(lags[0])
    if name == 'four_week_mean':
        return mean(lags)
    if name not in ('seasonal_ridge', 'weather_calendar_ridge'):
        raise ValueError('Unknown model')
    x = features(values, days, origin, horizon, fitted['scale'], weather)
    result = sum(a*b for a, b in zip(x, fitted['coefficients']))*fitted['scale']
    if not math.isfinite(result):
        raise ValueError('Nonfinite prediction')
    return max(0.0, result)


def evaluate(name, values, days, start, end, fitted, weather=None):
    if date.fromisoformat(fitted['training_through']) >= days[start]:
        raise ValueError('Training overlaps evaluation targets')
    rows = []
    for block in range(start, end, HORIZON):
        origin = block-1
        for index in range(block, min(block+HORIZON, end)):
            horizon = index-origin
            prediction = predict(name, values[:origin+1], days, origin, horizon, fitted, weather)
            rows.append({'date': days[index].isoformat(), 'origin': days[origin].isoformat(),
                         'horizon': horizon, 'actual': values[index], 'predicted': prediction})
    return rows


def metrics(rows):
    error = sum(abs(r['actual']-r['predicted']) for r in rows)
    total = sum(r['actual'] for r in rows)
    return {'mae': round(error/len(rows), 2), 'wape_pct': round(100*error/total, 2) if total else None,
            'days': len(rows)}


def consistent_improvement(candidate, reference):
    wins = sum(c < r for c, r in zip(candidate, reference))
    reference_error, candidate_error = sum(reference), sum(candidate)
    improvement = 1-candidate_error/reference_error if reference_error > 0 else None
    eligible = (reference_error > 0 and candidate_error <= (1-MIN_IMPROVEMENT)*reference_error
                and wins >= 2)
    return {'eligible': eligible, 'window_wins': wins, 'windows': SELECTION_FOLDS,
            'relative_improvement_pct': round(100*improvement, 2) if improvement is not None else None}


def select_model(values, days, end, weather=None):
    start = end-SELECTION_FOLDS*SELECTION_DAYS
    if start < 180 or end > len(values):
        raise ValueError('Selection requires 180 training days and three complete validation windows')
    candidates = (*CANDIDATES, 'weather_calendar_ridge') if weather else CANDIDATES
    pooled = {name: [] for name in candidates}
    errors = {name: [] for name in candidates}
    folds = []
    for first in range(start, end, SELECTION_DAYS):
        stop = first+SELECTION_DAYS
        fitted = fit(values, days, first)
        shadow = fit(values, days, first, weather) if weather else None
        scores = {}
        for name in candidates:
            rows = evaluate(name, values, days, first, stop,
                            shadow if name == 'weather_calendar_ridge' else fitted,
                            weather if name == 'weather_calendar_ridge' else None)
            pooled[name].extend(rows)
            errors[name].append(sum(abs(r['actual']-r['predicted']) for r in rows)/len(rows))
            scores[name] = metrics(rows)
        folds.append({'start': days[first].isoformat(), 'end': days[stop-1].isoformat(),
                      'training_through': fitted['training_through'], 'metrics': scores})
    baseline_gate = consistent_improvement(errors['same_weekday'], errors['four_week_mean'])
    baseline = 'same_weekday' if baseline_gate['eligible'] else 'four_week_mean'
    regression_gate = consistent_improvement(errors['seasonal_ridge'], errors[baseline])
    chosen = 'seasonal_ridge' if regression_gate['eligible'] else baseline
    decision = {'policy': 'three-window-v1', 'folds': folds, 'baseline': baseline,
                'baseline_gate': baseline_gate, 'regression_gate': regression_gate,
                'minimum_relative_improvement_pct': 100*MIN_IMPROVEMENT, 'minimum_window_wins': 2,
                'reference': 'four_week_mean',
                'rule': 'Start with the four-week mean. Same weekday must improve pooled MAE by at least 2% '
                        'and win at least two of three windows. Seasonal regression must pass the same '
                        'gate against that baseline. Ties keep the reference. Weather remains shadow-only.'}
    return chosen, {name: metrics(rows) for name, rows in pooled.items()}, decision


def build(source, weather=None):
    days = [date.fromisoformat(d) for d in source['dates']]
    n = len(days)
    if n < 365 or any(b-a != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise ValueError('At least one complete year of daily data required')
    training_end, validation_end, calibration_end = n-168, n-84, n-42
    report = {'model_version': VERSION, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': source['source'], 'quality': source['quality'], 'horizon_days': HORIZON,
        'evaluation': {'selection_start': days[training_end].isoformat(),
            'selection_end': days[validation_end-1].isoformat(),
            'calibration_start': days[validation_end].isoformat(),
            'calibration_end': days[calibration_end-1].isoformat(),
            'test_start': days[calibration_end].isoformat(), 'test_end': days[-1].isoformat(),
            'selection_windows': SELECTION_FOLDS, 'selection_window_days': SELECTION_DAYS,
            'method': 'Three disjoint 28-day walk-forward selection windows, then 42-day calibration and 42-day test; '
                      'expanding training refitted before each selection window; 14-day rolling origins. '
                      'Test model frozen before calibration. Lags use only observations through each origin. '
                      'Current revised extract; historical publication vintages are unavailable.'},
        'series': {}}
    for name, values in source['series'].items():
        if len(values) != n or any(not isinstance(v, int) or v < 0 for v in values):
            raise ValueError('Invalid daily series')
        chosen, validation, selection = select_model(values, days, validation_end, weather)
        frozen = fit(values, days, validation_end)
        calibration = evaluate(chosen, values, days, validation_end, calibration_end, frozen)
        errors = sorted(abs(r['actual']-r['predicted']) for r in calibration)
        width = errors[min(len(errors)-1, math.ceil((len(errors)+1)*.9)-1)]
        tests = {candidate: evaluate(candidate, values, days, calibration_end, n, frozen) for candidate in CANDIDATES}
        selected_test = tests[chosen]
        test_metrics = {candidate: metrics(rows) for candidate, rows in tests.items()}
        coverage = mean(abs(r['actual']-r['predicted']) <= width for r in selected_test)
        final = fit(values, days, n)
        interval_challenger = calibrate(chosen, values, days, n)
        shadow = fit(values, days, n, weather) if weather else None
        if weather:
            shadow_frozen = fit(values, days, validation_end, weather)
            test_metrics['weather_calendar_ridge'] = metrics(evaluate('weather_calendar_ridge', values, days,
                calibration_end, n, shadow_frozen, weather))
        predictions = []
        for horizon in range(1, HORIZON+1):
            value = predict(chosen, values, days, n-1, horizon, final)
            predictions.append({'date': (days[-1]+timedelta(days=horizon)).isoformat(),
                'forecast': round(value), 'lower': max(0, math.floor(value-width)),
                'upper': math.ceil(value+width), 'horizon': horizon,
                'candidates': {candidate: round(predict(candidate, values, days, n-1, horizon, final), 2)
                               for candidate in CANDIDATES}})
            lower, upper = bounds(value, horizon, interval_challenger)
            predictions[-1]['shadow_intervals'] = {interval_challenger['method']: {
                'lower': max(0, math.floor(lower)), 'upper': math.ceil(upper)}}
            if shadow:
                predictions[-1]['candidates']['weather_calendar_ridge'] = round(predict(
                    'weather_calendar_ridge', values, days, n-1, horizon, shadow, weather), 2)
        report['series'][name] = {'selected_model': chosen, 'selection_metrics': validation,
            'selection': selection,
            'test_metrics': test_metrics, 'test_interval_coverage_pct': round(100*coverage, 1),
            'interval': {'nominal_pct': 90, 'calibration_days': len(errors), 'half_width': round(width, 2),
                         'interpretation': 'Empirical error band; time dependence and drift mean 90% coverage is not guaranteed.'},
            'interval_challenger': {**interval_challenger, 'role': 'Shadow only; does not replace displayed bands'},
            'fitted_model': final, 'forecast': predictions,
            'history': [{'date': d.isoformat(), 'requests': v} for d, v in zip(days[-90:], values[-90:])],
            'test_predictions': [{**r, 'predicted': round(r['predicted'], 2)} for r in selected_test]}
        report['series'][name]['diagnostics'] = diagnostics(
            chosen, values, days, calibration_end, frozen, calibration, selected_test)
        if shadow:
            report['series'][name]['shadow_model'] = shadow
    report['weather'] = ({k: v for k, v in weather.items() if k != 'days'} if weather else
                         {'status': 'Unavailable; core demand forecasts continue without weather'})
    report['weather']['role'] = 'Experimental challenger; not eligible for automatic selection until prospective evidence accumulates'
    return report
