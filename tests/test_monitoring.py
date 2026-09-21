import copy
from datetime import date, timedelta

from serviceforecast.monitor import issuance, record_publication, update
from serviceforecast.weather import extra_features, holidays


def source():
    days = [(date(2026, 7, 1)+timedelta(days=i)).isoformat() for i in range(75)]
    return {'dates': days, 'series': {'MANHATTAN': [100]*75, 'NYC TOTAL': [100]*75},
        'source': {'data_through': days[-1], 'retrieved_at': '2026-09-15T18:00:00+00:00', 'sha256': 'abc'}}


def report():
    return {'generated_at': '2026-09-01T18:00:00+00:00', 'model_version': 'test',
        'source': {'data_through': '2026-08-30'}, 'series': {'MANHATTAN': {'selected_model': 'same_weekday',
        'forecast': [{'date': '2026-09-01', 'forecast': 0, 'lower': 0, 'upper': 0},
                     {'date': '2026-09-02', 'forecast': 110, 'lower': 90, 'upper': 130}]}}}


def test_only_future_publications_are_scored_and_retries_keep_first_issue():
    published = report()
    assert [r['target'] for r in issuance(published)['rows']] == ['2026-09-02']
    state = record_publication({'issues': {}, 'final_actuals': {}, 'started_at': '2026-09-01'}, published)
    published['series']['MANHATTAN']['forecast'][1]['forecast'] = 999
    record_publication(state, published)
    state, result = update(state, source())
    assert result['series']['MANHATTAN']['wape_pct'] == 10
    assert result['series']['MANHATTAN']['status'] == 'Collecting outcomes'
    revised = source()
    revised['series']['MANHATTAN'][revised['dates'].index('2026-09-02')] = 200
    _, newer = update(state, revised)
    assert newer['series']['MANHATTAN']['wape_pct'] == 10


def test_immature_actuals_are_not_reported_as_final_scores():
    published = report()
    published['series']['MANHATTAN']['forecast'][1]['date'] = '2026-09-12'
    state = record_publication({'issues': {}, 'final_actuals': {}, 'started_at': '2026-09-01'}, published)
    _, result = update(state, source())
    assert result['series']['MANHATTAN']['scored_predictions'] == 0
    assert result['series']['MANHATTAN']['awaiting_mature_actuals'] == 1
    assert result['series']['MANHATTAN']['wape_pct'] is None


def test_undercoverage_needs_enough_distinct_dates_and_flags_weak_bands():
    state = {'issues': {'2026-08-01': []}, 'final_actuals': {}, 'started_at': '2026-08-01'}
    for i in range(28):
        state['issues']['2026-08-01'].append({'series': 'MANHATTAN',
            'target': (date(2026, 8, 2)+timedelta(days=i//2)).isoformat(), 'prediction': 150,
            'lower': 140, 'upper': 160, 'lead_days': 1, 'candidates': {'same_weekday': 100}})
    _, result = update(state, source())
    assert result['series']['MANHATTAN']['status'] == 'Undercoverage warning'
    assert result['series']['MANHATTAN']['candidate_wape_pct']['same_weekday']['wape_pct'] == 0


def test_weather_features_do_not_read_recent_or_future_weather():
    days = [date(2026, 6, 1)+timedelta(days=i) for i in range(50)]
    weather = {'days': {d.isoformat(): [20, 2] for d in days}}
    first = extra_features(days, 20, 3, weather)
    changed = copy.deepcopy(weather)
    for d in days[16:]:
        changed['days'][d.isoformat()] = [999, 999]
    assert extra_features(days, 20, 3, changed) == first
    assert date(2026, 7, 3) in holidays(2026)
    assert date(2026, 11, 26) in holidays(2026)
