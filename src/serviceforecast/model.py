import math
from datetime import date, datetime, timedelta, timezone
from statistics import mean

HORIZON = 14
CANDIDATES = ('same_weekday', 'four_week_mean', 'seasonal_ridge')
VERSION = 'seasonal-demand-v1'


def seasonal_values(values, origin, horizon):
    index = origin + horizon - 7 * math.ceil(horizon / 7)
    return [values[index - 7 * k] for k in range(4)]


def features(values, days, origin, horizon, scale):
    target = days[origin] + timedelta(days=horizon)
    lags = seasonal_values(values, origin, horizon)
    return [1.0, *[v/scale for v in lags], mean(values[origin-6:origin+1])/scale,
            mean(values[origin-27:origin+1])/scale,
            math.sin(2*math.pi*target.weekday()/7), math.cos(2*math.pi*target.weekday()/7),
            math.sin(2*math.pi*target.timetuple().tm_yday/365.25),
            math.cos(2*math.pi*target.timetuple().tm_yday/365.25), horizon/HORIZON]


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


def fit(values, days, end):
    if end < 180:
        raise ValueError('At least 180 training days required')
    scale = max(1.0, mean(values[:end]))
    size = 12
    matrix = [[0.0]*size for _ in range(size)]
    vector = [0.0]*size
    samples = 0
    # Weekly origins limit redundant overlapping labels; every target is before end.
    for origin in range(55, end-HORIZON, 7):
        for horizon in range(1, HORIZON+1):
            x = features(values, days, origin, horizon, scale)
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


def predict(name, values, days, origin, horizon, fitted):
    if origin < 27 or not 1 <= horizon <= HORIZON:
        raise ValueError('Unsupported forecast origin or horizon')
    lags = seasonal_values(values, origin, horizon)
    if name == 'same_weekday':
        return float(lags[0])
    if name == 'four_week_mean':
        return mean(lags)
    if name != 'seasonal_ridge':
        raise ValueError('Unknown model')
    x = features(values, days, origin, horizon, fitted['scale'])
    result = sum(a*b for a, b in zip(x, fitted['coefficients']))*fitted['scale']
    if not math.isfinite(result):
        raise ValueError('Nonfinite prediction')
    return max(0.0, result)


def evaluate(name, values, days, start, end, fitted):
    if date.fromisoformat(fitted['training_through']) >= days[start]:
        raise ValueError('Training overlaps evaluation targets')
    rows = []
    for block in range(start, end, HORIZON):
        origin = block-1
        for index in range(block, min(block+HORIZON, end)):
            horizon = index-origin
            prediction = predict(name, values[:origin+1], days, origin, horizon, fitted)
            rows.append({'date': days[index].isoformat(), 'origin': days[origin].isoformat(),
                         'horizon': horizon, 'actual': values[index], 'predicted': prediction})
    return rows


def metrics(rows):
    error = sum(abs(r['actual']-r['predicted']) for r in rows)
    total = sum(r['actual'] for r in rows)
    return {'mae': round(error/len(rows), 2), 'wape_pct': round(100*error/total, 2) if total else None,
            'days': len(rows)}


def build(source):
    days = [date.fromisoformat(d) for d in source['dates']]
    n = len(days)
    if n < 365 or any(b-a != timedelta(days=1) for a, b in zip(days, days[1:])):
        raise ValueError('At least one complete year of daily data required')
    training_end, validation_end, calibration_end = n-112, n-84, n-42
    report = {'model_version': VERSION, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': source['source'], 'quality': source['quality'], 'horizon_days': HORIZON,
        'evaluation': {'selection_start': days[training_end].isoformat(),
            'selection_end': days[validation_end-1].isoformat(),
            'calibration_start': days[validation_end].isoformat(),
            'calibration_end': days[calibration_end-1].isoformat(),
            'test_start': days[calibration_end].isoformat(), 'test_end': days[-1].isoformat(),
            'method': 'Disjoint 28-day selection, 42-day calibration, 42-day test; 14-day rolling origins. '
                      'Test model frozen before calibration. Lags use only observations through each origin. '
                      'Current revised extract; historical publication vintages are unavailable.'},
        'series': {}}
    for name, values in source['series'].items():
        if len(values) != n or any(not isinstance(v, int) or v < 0 for v in values):
            raise ValueError('Invalid daily series')
        initial = fit(values, days, training_end)
        validation = {candidate: metrics(evaluate(candidate, values, days, training_end, validation_end, initial))
                      for candidate in CANDIDATES}
        baseline = min(CANDIDATES[:2], key=lambda key: validation[key]['mae'])
        chosen = 'seasonal_ridge' if validation['seasonal_ridge']['mae'] < .98*validation[baseline]['mae'] else baseline
        frozen = fit(values, days, validation_end)
        calibration = evaluate(chosen, values, days, validation_end, calibration_end, frozen)
        errors = sorted(abs(r['actual']-r['predicted']) for r in calibration)
        width = errors[min(len(errors)-1, math.ceil((len(errors)+1)*.9)-1)]
        tests = {candidate: evaluate(candidate, values, days, calibration_end, n, frozen) for candidate in CANDIDATES}
        selected_test = tests[chosen]
        test_metrics = {candidate: metrics(rows) for candidate, rows in tests.items()}
        coverage = mean(abs(r['actual']-r['predicted']) <= width for r in selected_test)
        final = fit(values, days, n)
        predictions = []
        for horizon in range(1, HORIZON+1):
            value = predict(chosen, values, days, n-1, horizon, final)
            predictions.append({'date': (days[-1]+timedelta(days=horizon)).isoformat(),
                'forecast': round(value), 'lower': max(0, math.floor(value-width)),
                'upper': math.ceil(value+width), 'horizon': horizon})
        report['series'][name] = {'selected_model': chosen, 'selection_metrics': validation,
            'test_metrics': test_metrics, 'test_interval_coverage_pct': round(100*coverage, 1),
            'interval': {'nominal_pct': 90, 'calibration_days': len(errors), 'half_width': round(width, 2),
                         'interpretation': 'Empirical error band; time dependence and drift mean 90% coverage is not guaranteed.'},
            'fitted_model': final, 'forecast': predictions,
            'history': [{'date': d.isoformat(), 'requests': v} for d, v in zip(days[-90:], values[-90:])],
            'test_predictions': [{**r, 'predicted': round(r['predicted'], 2)} for r in selected_test]}
    return report
