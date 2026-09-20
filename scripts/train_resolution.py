import hashlib
import json
import platform
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import sklearn

from serviceops.pipeline import read_source
from serviceresolution.model import cohort, evaluate, fit, km

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / 'build/resolution'
    output.mkdir(parents=True, exist_ok=True)
    events, rejected, checksum = read_source(ROOT / 'data/raw/incident_event_log.csv')
    train, train_excluded = cohort(events, '2016-02-29', '2016-04-01', '2016-03-31 23:59:59')
    validation, validation_excluded = cohort(events, '2016-04-01', '2016-04-15', '2016-04-30 23:59:59')
    test, test_excluded = cohort(events, '2016-05-01', '2016-05-15', '2016-05-31 23:59:59')
    ids = [set(r['incident_id'] for r in split) for split in (train, validation, test)]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    print(json.dumps({'training': len(train), 'validation': len(validation), 'test': len(test)}), flush=True)
    model = fit(train)
    censor_curve = km(train, censor=True)
    candidates = ('global_median', 'priority_median', 'piecewise_hazard')
    selection = {name: evaluate(model, validation, name, censor_curve) for name in candidates}
    baseline = min(candidates[:2], key=lambda name: selection[name]['mean_ipcw_brier'])
    chosen = 'piecewise_hazard' if selection['piecewise_hazard']['mean_ipcw_brier'] < .98*selection[baseline]['mean_ipcw_brier'] else baseline
    testing = {name: evaluate(model, test, name, censor_curve) for name in candidates}
    by_priority = {priority: {name: evaluate(model, [r for r in test if r['priority'] == priority], name, censor_curve)
                             for name in candidates} for priority in sorted(set(r['priority'] for r in test))}
    drift = {}
    for key in ('priority', 'contact_type', 'category'):
        before, after = Counter(r[key] for r in train), Counter(r[key] for r in test)
        labels = set(before) | set(after)
        drift[key] = {'total_variation': round(.5*sum(abs(before[v]/len(train)-after[v]/len(test)) for v in labels), 4),
                      'unseen_test_fraction': round(sum(v for k, v in after.items() if k not in before)/len(test), 4),
                      'training': dict(before), 'test': dict(after)}
    version = hashlib.sha256((checksum+Path(__file__).read_text()+
        (ROOT / 'src/serviceresolution/model.py').read_text()).encode()).hexdigest()[:16]
    report = {'version': version, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': checksum, 'target': 'Hours from first observed nonterminal state to first observed Resolved/Closed, capped at 168 h',
        'prediction_point': 'First nonterminal audit observation within 24 h of opening',
        'selected_model': chosen, 'model': model, 'validation': selection, 'test': testing,
        'test_by_priority': by_priority, 'drift': drift,
        'cohort': {'training_n': len(train), 'validation_n': len(validation), 'test_n': len(test),
            'training_origins': ['2016-02-29', '2016-03-31'], 'training_observation_end': '2016-03-31 23:59:59',
            'validation_origins': ['2016-04-01', '2016-04-14'], 'validation_observation_end': '2016-04-30 23:59:59',
            'test_origins': ['2016-05-01', '2016-05-14'], 'test_observation_end': '2016-05-31 23:59:59',
            'excluded': {'training': train_excluded, 'validation': validation_excluded, 'test': test_excluded},
            'invalid_source_rows': len(rejected)},
        'runtime': {'python': platform.python_version(), 'scikit_learn': sklearn.__version__},
        'limitations': ['Unresolved cases are censored at their last observed audit event, not assumed resolved or discarded.',
            'Censoring may depend on incident behavior; IPCW assumes independent censoring and therefore remains assumption-sensitive.',
            'All cohorts have at least two audit observations or a later observed resolution; cases without observable follow-up are excluded and counted.',
            'MAE is only for observed events within seven days; it does not describe censored or longer cases.',
            'Historical anonymized 2016 cohort, not validated for present-day service operations.',
            'Selection is based on validation IPCW Brier averaged over fixed horizons. Test results never choose the model.',
            'First observed resolution differs from the analytics dashboard closing-cycle metric; later reopening is outside this target.']}
    destination = output / version
    destination.mkdir(exist_ok=True)
    (destination / 'model-report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    (output / 'model-report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    pd.DataFrame([{'incident_id': r['incident_id'], 'split': split} for split, rows in
                 [('train', train), ('validation', validation), ('test', test)] for r in rows]).to_parquet(destination / 'split-membership.parquet', index=False)
    print(json.dumps({'version': version, 'chosen': chosen, 'selection': {k:v['mean_ipcw_brier'] for k,v in selection.items()},
                     'test': {k: {'brier': v['mean_ipcw_brier'], 'mae': v['observed_event_median_mae_hours'],
                                  'events': v['resolved_within_168h'], 'censored': v['censored_before_168h']} for k,v in testing.items()}}, indent=2))


if __name__ == '__main__':
    main()
