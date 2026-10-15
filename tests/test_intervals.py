from datetime import date, timedelta
import copy

import pytest

from serviceforecast.intervals import bounds, calibrate, quantile, score
from serviceforecast.monitor import update


def test_recent_calibration_excludes_future_targets_and_refits_before_each_block(monkeypatch):
    from serviceforecast import model
    days = [date(2025, 1, 1)+timedelta(days=i) for i in range(400)]
    values = [100+i%7*10+i//30 for i in range(400)]
    boundaries = []
    real_fit = model.fit
    def tracked(values, days, end):
        boundaries.append(end)
        return real_fit(values, days, end)
    monkeypatch.setattr(model, 'fit', tracked)
    first = calibrate('seasonal_ridge', values, days, 350)
    assert boundaries == list(range(266, 350, 14))
    assert calibrate('seasonal_ridge', values[:350]+[10**8]*50, days, 350) == first
    assert [g['residuals'] for g in first['groups']] == [42, 42]
    assert first['calibration_end'] == days[349].isoformat()
    with pytest.raises(ValueError):
        calibrate('same_weekday', values, days, 200)


def test_band_score_penalizes_unnecessary_width_and_misses():
    exact = [{'date': '2026-01-01', 'actual': 100, 'lower': 90, 'upper': 110}]
    wide = [{**exact[0], 'lower': 0, 'upper': 200}]
    miss = [{**exact[0], 'actual': 120}]
    assert score(exact)['coverage_pct'] == score(wide)['coverage_pct'] == 100
    assert score(exact)['mean_interval_score'] < score(wide)['mean_interval_score'] < score(miss)['mean_interval_score']
    assert quantile(list(range(42))) == 38
    interval = {'groups': [{'horizon_start': 1, 'horizon_end': 7, 'half_width': 20},
                           {'horizon_start': 8, 'horizon_end': 14, 'half_width': 40}]}
    assert bounds(10, 7, interval) == (0, 30)
    assert bounds(10, 8, interval) == (0, 50)
    with pytest.raises(ValueError):
        bounds(10, 15, interval)


def test_version_cohorts_keep_old_warning_and_only_score_matched_shadow_rows():
    days = [(date(2026, 8, 1)+timedelta(days=i)).isoformat() for i in range(60)]
    source = {'dates': days, 'series': {'CITY': [100]*60},
              'source': {'data_through': days[-1], 'retrieved_at': days[-1], 'sha256': 'abc'}}
    old = [{'series': 'CITY', 'version': 'old', 'target': days[10+i//2], 'prediction': 150,
            'lower': 140, 'upper': 160, 'lead_days': 2} for i in range(28)]
    old[0]['shadow_intervals'] = {'candidate': {'lower': 90, 'upper': 160}}
    pending = {'series': 'CITY', 'version': 'new', 'target': '2026-10-10', 'prediction': 100,
               'lower': 90, 'upper': 110, 'lead_days': 2}
    state = {'issues': {days[0]: old, days[-3]: [pending]}, 'final_actuals': {}, 'started_at': days[0]}
    original = copy.deepcopy(state['issues'])
    _, result = update(state, source, current_version='new')
    series = result['series']['CITY']
    assert series['status'] == 'Undercoverage warning'
    assert series['by_version']['new']['status'] == 'Collecting outcomes'
    assert series['by_version']['new']['coverage_pct'] is None
    assert series['by_version']['new']['awaiting_mature_actuals'] == 1
    assert series['by_version']['old']['below_band'] == 28
    assert series['misses']['mean_bias'] == 50
    matched = series['interval_challengers']['candidate']
    assert matched['reference']['predictions'] == matched['challenger']['predictions'] == 1
    assert matched['reference']['coverage_pct'] == 0
    assert matched['challenger']['coverage_pct'] == 100
    assert state['issues'] == original


def test_published_shadow_intervals_are_preserved_on_retry():
    from serviceforecast.monitor import record_publication
    report = {'generated_at': '2026-10-14T18:00:00+00:00', 'model_version': 'v4',
              'source': {'data_through': '2026-10-12'}, 'series': {'CITY': {'selected_model': 'same_weekday',
              'forecast': [{'date': '2026-10-15', 'forecast': 100, 'lower': 90, 'upper': 110,
                            'shadow_intervals': {'candidate': {'lower': 80, 'upper': 120}}}]}}}
    state = record_publication({'issues': {}}, copy.deepcopy(report))
    report['series']['CITY']['forecast'][0]['shadow_intervals']['candidate']['upper'] = 999
    record_publication(state, report)
    assert state['issues']['2026-10-14'][0]['shadow_intervals']['candidate']['upper'] == 120
