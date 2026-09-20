from datetime import date, timedelta
import math

import pytest

from serviceforecast.model import build, evaluate, features, fit, predict, seasonal_values, solve
from serviceforecast.source import BOROUGHS, validate


def sample(n=400):
    days = [date(2024, 1, 1)+timedelta(days=i) for i in range(n)]
    values = [100+10*d.weekday()+int(15*math.sin(i/40)) for i, d in enumerate(days)]
    return days, values


def test_features_never_read_beyond_origin():
    days, values = sample()
    for horizon in range(1, 15):
        expected = features(values[:201], days, 200, horizon, 100)
        contaminated = values[:201]+[10**9]*199
        assert features(contaminated, days, 200, horizon, 100) == expected
        assert len(seasonal_values(values[:201], 200, horizon)) == 4


def test_fit_does_not_use_future_targets():
    days, values = sample()
    original = fit(values, days, 240)
    assert fit(values[:240]+[10**9]*160, days, 240) == original
    with pytest.raises(ValueError, match='overlaps'):
        evaluate('seasonal_ridge', values, days, 239, 250, original)


def test_solver_matches_known_system():
    assert solve([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0]) == pytest.approx([2, 3])


def test_weekly_baseline_is_exact_on_weekly_signal():
    days, _ = sample()
    values = [100+d.weekday()*10 for d in days]
    for horizon in range(1, 15):
        assert predict('same_weekday', values[:200], days, 199, horizon, {}) == values[199+horizon]


def test_forecast_split_and_prediction_contract():
    days, values = sample()
    report = build({'dates': [d.isoformat() for d in days], 'series': {'NYC TOTAL': values},
                    'source': {'data_through': days[-1].isoformat()}, 'quality': {}})
    result = report['series']['NYC TOTAL']
    assert report['evaluation']['selection_end'] < report['evaluation']['calibration_start']
    assert report['evaluation']['calibration_end'] < report['evaluation']['test_start']
    assert result['test_metrics'][result['selected_model']]['days'] == 42
    assert len(result['forecast']) == 14
    assert all(0 <= r['lower'] <= r['forecast'] <= r['upper'] for r in result['forecast'])
    assert result['forecast'][0]['date'] == (days[-1]+timedelta(days=1)).isoformat()
    assert all(row['origin'] < row['date'] for row in result['test_predictions'])


def test_source_missing_days_and_duplicates_fail():
    start = date(2025, 1, 1)
    rows = [{'day': start.isoformat(), 'borough': b, 'requests': '100'} for b in BOROUGHS]
    assert validate(rows, start, start)['series']['NYC TOTAL'] == [500]
    with pytest.raises(ValueError, match='Incomplete'):
        validate(rows[:-1], start, start)
    with pytest.raises(ValueError, match='Duplicate'):
        validate(rows+[rows[0]], start, start)


def test_unknown_borough_is_preserved_in_city_total():
    start = date(2025, 1, 1)
    rows = [{'day': str(start), 'borough': b, 'requests': '100'} for b in BOROUGHS]
    rows.append({'day': str(start), 'requests': '12'})
    result = validate(rows, start, start)
    assert result['series']['NYC TOTAL'] == [512]
    assert result['quality']['unknown_borough_requests'] == 12
