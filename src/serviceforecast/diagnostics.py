"""Retrospective diagnostics, kept separate from the publication ledger."""
import math
from datetime import date, timedelta


def score(rows):
    total = sum(r['actual'] for r in rows)
    return {'predictions': len(rows), 'dates': len({r['date'] for r in rows}),
            'wape_pct': round(100 * sum(abs(r['actual'] - r['predicted']) for r in rows) / total, 2)
            if total else None}


def diagnostics(chosen, values, days, start, fitted, calibration, test):
    from serviceforecast.model import predict

    if date.fromisoformat(fitted['training_through']) >= days[start]:
        raise ValueError('Diagnostic training overlaps targets')
    rows = []
    for origin in range(start - 1, len(days) - 3):
        for horizon in range(3, min(14, len(days) - origin - 1) + 1):
            target = days[origin + horizon]
            rows.append({'date': target.isoformat(), 'origin': days[origin].isoformat(),
                         'issued': (days[origin] + timedelta(days=2)).isoformat(),
                         'lead': horizon - 2, 'weekday': target.weekday(),
                         'actual': values[origin + horizon],
                         'predicted': predict(chosen, values[:origin + 1], days, origin, horizon, fitted)})
    heatmap = []
    for weekday in range(7):
        for low, high in ((1, 3), (4, 7), (8, 14)):
            subset = [r for r in rows if r['weekday'] == weekday and low <= r['lead'] <= high]
            heatmap.append({'weekday': weekday, 'lead': f'{low}–{high}', **score(subset)})
    weeks = {}
    for row in rows:
        day = date.fromisoformat(row['date'])
        week = (day - timedelta(days=day.weekday())).isoformat()
        weeks.setdefault(week, []).append(row)
    errors = sorted(abs(r['actual'] - r['predicted']) for r in calibration)
    curve = []
    for nominal in (50, 60, 70, 80, 90, 95):
        width = errors[min(len(errors) - 1, math.ceil((len(errors) + 1) * nominal / 100) - 1)]
        actual = 100 * sum(abs(r['actual'] - r['predicted']) <= width for r in test) / len(test)
        curve.append({'nominal_pct': nominal, 'actual_pct': round(actual, 1), 'half_width': round(width, 2)})
    return {'label': 'Retrospective replay of current revised extract',
            'method': 'Daily origins; model and selection frozen before test. Only pre-origin demand is used. '
                      'Assumes two days of publication lag, leaving 1–12 future lead days within the 14-day model. '
                      'Historical source vintages and actual past availability are not reconstructed. '
                      'Overlapping predictions are dependent; these are not live monitoring observations.',
            'heatmap': heatmap, 'weekly': [{'week': k, **score(v)} for k, v in sorted(weeks.items())],
            'calibration_curve': curve, 'calibration_test_dates': len(test),
            'replay_predictions': rows}
