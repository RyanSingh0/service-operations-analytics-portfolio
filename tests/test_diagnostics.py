from datetime import date, timedelta

import pytest

from serviceforecast.diagnostics import diagnostics, score
from serviceforecast.health import summarize


def sample(values=None):
    values = values or [100 + i % 7 * 10 for i in range(365)]
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(365)]
    fitted = {'training_through': days[280].isoformat()}
    calibration = [{'actual': 100+i, 'predicted': 100} for i in range(42)]
    return diagnostics('four_week_mean', values, days, 323, fitted, calibration, calibration)


def test_replay_excludes_future_features_and_nowcasts():
    before = sample()
    altered = [100 + i % 7 * 10 if i < 330 else 9000 for i in range(365)]
    after = sample(altered)
    original = {(r['origin'], r['date']): r['predicted'] for r in before['replay_predictions']}
    for row in after['replay_predictions']:
        assert row['origin'] < row['issued'] < row['date']
        assert 1 <= row['lead'] <= 12
        if row['origin'] < '2025-11-27':
            assert row['predicted'] == original[row['origin'], row['date']]
    assert len(before['heatmap']) == 21
    assert all(c['predictions'] > 0 for c in before['heatmap'])


def test_calibration_and_weighted_errors():
    rows = [{'date': 'x', 'actual': 10, 'predicted': 0}, {'date': 'y', 'actual': 100, 'predicted': 100}]
    assert score(rows)['wape_pct'] == 9.09
    assert score([])['wape_pct'] is None
    curve = sample()['calibration_curve']
    assert [r['half_width'] for r in curve] == sorted(r['half_width'] for r in curve)
    assert [r['actual_pct'] for r in curve] == sorted(r['actual_pct'] for r in curve)
    with pytest.raises(ValueError, match='overlaps'):
        diagnostics('four_week_mean', [1]*365, [date(2025,1,1)]*365, 323,
                    {'training_through': '2025-01-01'}, [], [])


def test_health_keeps_failures_unknowns_and_latest_thirty():
    rows = [{'id': str(i), 'started_at': f'{i:03}', 'status': 'SUCCEEDED', 'duration_seconds': i}
            for i in range(35)]
    rows[-1]['status'] = 'STARTED'
    rows[-2]['status'] = 'FAILED'
    result = summarize(rows)
    assert len(result['runs']) == 30
    assert result['completed'] == 29
    assert result['success_rate_pct'] == 96.6
    assert result['p50_seconds'] == 19
    assert result['p95_seconds'] == 32
    assert summarize([])['success_rate_pct'] is None
