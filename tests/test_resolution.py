import math

import pandas as pd
import pytest

from serviceresolution.model import at, cohort, evaluate, km, median, survival


def test_km_keeps_censored_cases_in_risk_set():
    rows = [{'duration': 2, 'event': True}, {'duration': 3, 'event': False},
            {'duration': 4, 'event': True}]
    curve = km(rows)
    assert at(curve, 2) == pytest.approx(2/3)
    assert at(curve, 4) == 0
    assert at(km(rows, censor=True), 3, left=True) == 1


def test_hazard_curve_is_monotone_and_has_correct_median():
    model = {'intercept': math.log(.1), 'coefficients': {}}
    row = {k: 'test' for k in ('priority','contact_type','category','weekday','hour_band','age_band')}
    assert survival(model, row, 'piecewise_hazard', 10) == pytest.approx(math.exp(-1))
    assert median(model, row, 'piecewise_hazard') == pytest.approx(math.log(2)/.1)
    assert survival(model, row, 'piecewise_hazard', 24) > survival(model, row, 'piecewise_hazard', 168)


def test_end_of_horizon_censoring_is_evaluable():
    model = {'global_km': [[1, .8]], 'priority_km': {'P': [[1, .8]]}}
    rows = [{'duration': 168, 'event': False, 'priority': 'P'}]
    score = evaluate(model, rows, 'global_median', [[168, 0]])
    assert score['brier_by_horizon'][-1]['ipcw_brier'] == pytest.approx(.04)


def test_cohort_censors_without_looking_past_observation_end():
    rows = []
    for updated, state, priority in [('2016-03-01 00:00:00','New','P1'),
                                     ('2016-03-02 00:00:00','Active','P2'),
                                     ('2016-04-01 00:00:00','Resolved','P3')]:
        rows.append({'incident_id': 'INC1', 'opened_at': '2016-03-01 00:00:00',
                     'updated_at': updated, 'state': state, 'priority': priority,
                     'contact_type': 'Phone', 'category': 'C', 'source_row': len(rows), 'sys_mod_count': len(rows)})
    result, _ = cohort(pd.DataFrame(rows), '2016-03-01', '2016-04-01', '2016-03-31 23:59:59')
    assert result[0]['event'] is False
    assert result[0]['duration'] == 24
    assert result[0]['priority'] == 'P1'


def test_baseline_median_can_be_beyond_horizon():
    assert median({'global_km': [[24,.9],[168,.7]]}, {}, 'global_median') is None
