from datetime import date, timedelta

import pytest

from serviceforecast.model import consistent_improvement, select_model


@pytest.mark.parametrize(('candidate', 'reference', 'eligible', 'wins'), [
    ([0, 101, 101], [100, 100, 100], False, 1),
    ([97, 97, 100], [100, 100, 100], True, 2),
    ([99, 99, 99], [100, 100, 100], False, 3),
    ([100, 100, 100], [100, 100, 100], False, 0),
    ([0, 0, 0], [0, 0, 0], False, 0),
])
def test_gate_requires_both_consistency_and_material_improvement(candidate, reference, eligible, wins):
    gate = consistent_improvement(candidate, reference)
    assert gate['eligible'] is eligible
    assert gate['window_wins'] == wins


def sample():
    days = [date(2024, 1, 1)+timedelta(days=i) for i in range(400)]
    values = [100+d.weekday()*10+(i//35 % 4)*7 for i, d in enumerate(days)]
    return days, values


def test_selection_excludes_calibration_and_test_targets():
    days, values = sample()
    end = len(days)-84
    original = select_model(values, days, end)
    changed = select_model(values[:end]+[999999]*84, days, end)
    assert changed == original
    folds = original[2]['folds']
    assert len(folds) == 3
    for i, fold in enumerate(folds):
        assert fold['training_through'] < fold['start'] <= fold['end'] < str(days[end])
        assert all(m['days'] == 28 for m in fold['metrics'].values())
        if i:
            assert date.fromisoformat(folds[i-1]['end'])+timedelta(days=1) == date.fromisoformat(fold['start'])
    assert all(m['days'] == 84 for m in original[1].values())


def test_later_validation_windows_cannot_change_earlier_fold():
    days, values = sample()
    end = len(days)-84
    original = select_model(values, days, end)
    first_stop = end-56
    altered = select_model(values[:first_stop]+[90000]*(len(values)-first_stop), days, end)
    assert original[2]['folds'][0] == altered[2]['folds'][0]


def test_zero_error_ties_keep_four_week_reference():
    days, _ = sample()
    chosen, _, decision = select_model([100]*len(days), days, len(days)-84)
    assert chosen == 'four_week_mean'
    assert decision['baseline_gate']['relative_improvement_pct'] is None


def test_incomplete_training_history_is_rejected():
    days, values = sample()
    with pytest.raises(ValueError, match='180 training days'):
        select_model(values, days, 263)
