import math

import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import PoissonRegressor

BINS = [0, 1, 4, 12, 24, 48, 72, 168]
HORIZONS = [4, 12, 24, 48, 72, 168]
FIELDS = ['priority', 'contact_type', 'category']


def cohort(events, start, end, observation_end):
    visible = events.loc[events.updated_at.le(observation_end)].sort_values(
        ['incident_id', 'updated_at', 'sys_mod_count', 'source_row'])
    rows = []
    exclusions = {'first_already_terminal': 0, 'delayed_first_observation': 0, 'no_followup': 0}
    for incident_id, history in visible.groupby('incident_id', sort=False):
        first = history.iloc[0]
        if not start <= first.updated_at < end:
            continue
        if first.state in {'Resolved', 'Closed'}:
            exclusions['first_already_terminal'] += 1
            continue
        origin = pd.Timestamp(first.updated_at)
        age = (origin-pd.Timestamp(first.opened_at)).total_seconds()/3600
        if age < 0 or age > 24:
            exclusions['delayed_first_observation'] += 1
            continue
        terminal = history.loc[history.state.isin(['Resolved', 'Closed'])]
        event = not terminal.empty
        followup = terminal.iloc[0].updated_at if event else history.iloc[-1].updated_at
        duration = (pd.Timestamp(followup)-origin).total_seconds()/3600
        if duration <= 0:
            exclusions['no_followup'] += 1
            continue
        rows.append({'incident_id': incident_id, 'origin': str(origin),
            'duration': min(duration, 168.0), 'event': bool(event and duration <= 168),
            **{key: str(first[key]) for key in FIELDS}, 'weekday': str(origin.weekday()),
            'hour_band': str(origin.hour//6), 'age_band': '0–1 h' if age <= 1 else '1–24 h'})
    return rows, exclusions


def km(rows, censor=False):
    timeline = sorted(set(float(r['duration']) for r in rows))
    survival = 1.0
    curve = []
    for time in timeline:
        risk = sum(r['duration'] >= time for r in rows)
        events = sum(r['duration'] == time and (not r['event'] if censor else r['event']) for r in rows)
        if events:
            survival *= 1-events/risk
            curve.append([time, survival])
    return curve


def at(curve, time, left=False):
    value = 1.0
    for point, survival in curve:
        if point < time or (point == time and not left):
            value = survival
        else:
            break
    return value


def features(row, bin_index):
    return {**{key: row[key] for key in FIELDS}, 'weekday': row['weekday'],
            'hour_band': row['hour_band'], 'age_band': row['age_band'], 'interval': str(bin_index)}


def fit(rows):
    x, y, weights = [], [], []
    for row in rows:
        for i, (left, right) in enumerate(zip(BINS, BINS[1:])):
            exposure = min(row['duration'], right)-left
            if exposure <= 0:
                break
            resolved = row['event'] and row['duration'] <= right
            x.append(features(row, i))
            y.append(int(resolved)/exposure)
            weights.append(exposure)
            if row['duration'] <= right:
                break
    encoder = DictVectorizer(sparse=True)
    matrix = encoder.fit_transform(x)
    model = PoissonRegressor(alpha=.0001, max_iter=1000, tol=1e-7)
    model.fit(matrix, y, sample_weight=weights)
    return {'bins': BINS, 'intercept': float(model.intercept_),
        'coefficients': dict(zip(encoder.get_feature_names_out(), model.coef_.tolist())),
        'global_km': km(rows),
        'priority_km': {priority: km([r for r in rows if r['priority'] == priority])
                        for priority in sorted(set(r['priority'] for r in rows))},
        'support': {key: sorted(set(r[key] for r in rows)) for key in [*FIELDS, 'weekday', 'hour_band', 'age_band']},
        'training_n': len(rows), 'observed_events': sum(r['event'] for r in rows),
        'iterations': int(model.n_iter_)}


def curve_for(model, row, candidate):
    if candidate == 'global_median':
        return model['global_km']
    if candidate == 'priority_median':
        return model['priority_km'].get(row['priority'], model['global_km'])
    cumulative, curve = 0.0, []
    for i, (left, right) in enumerate(zip(BINS, BINS[1:])):
        log_rate = model['intercept'] + sum(model['coefficients'].get(key+'='+str(value), 0)
                                             for key, value in features(row, i).items())
        rate = math.exp(max(-30, min(10, log_rate)))
        cumulative += rate*(right-left)
        curve.append([right, math.exp(-cumulative)])
    return curve


def survival(model, row, candidate, time):
    if candidate != 'piecewise_hazard':
        return at(curve_for(model, row, candidate), time)
    cumulative = 0.0
    for i, (left, right) in enumerate(zip(BINS, BINS[1:])):
        length = min(time, right)-left
        if length <= 0:
            break
        log_rate = model['intercept'] + sum(model['coefficients'].get(key+'='+str(value), 0)
                                             for key, value in features(row, i).items())
        cumulative += math.exp(max(-30, min(10, log_rate)))*length
    return math.exp(-cumulative)


def median(model, row, candidate):
    if candidate != 'piecewise_hazard':
        return next((time for time, s in curve_for(model, row, candidate) if s <= .5), None)
    if survival(model, row, candidate, 168) > .5:
        return None
    left, right = 0.0, 168.0
    for _ in range(32):
        middle = (left+right)/2
        if survival(model, row, candidate, middle) > .5:
            left = middle
        else:
            right = middle
    return right


def evaluate(model, rows, candidate, censor_curve):
    scores = []
    cached = {}
    for horizon in HORIZONS:
        g = at(censor_curve, horizon, left=True)
        if g < .05:
            scores.append({'hours': horizon, 'ipcw_brier': None, 'reason': 'Insufficient censoring support'})
            continue
        score = 0.0
        known = 0
        for row in rows:
            key = (horizon, row['priority'] if candidate == 'priority_median' else 'global')
            if candidate == 'piecewise_hazard':
                s = survival(model, row, candidate, horizon)
            else:
                if key not in cached:
                    cached[key] = survival(model, row, candidate, horizon)
                s = cached[key]
            if row['event'] and row['duration'] <= horizon:
                denom = at(censor_curve, row['duration'], left=True)
                if denom < .05:
                    raise ValueError('Unstable censoring weights')
                score += s*s/denom
                known += 1
            elif row['duration'] > horizon or (row['duration'] == horizon and not row['event']):
                score += (1-s)**2/g
                known += 1
        scores.append({'hours': horizon, 'ipcw_brier': round(score/len(rows), 5), 'known_outcomes': known})
    comparable = [r['ipcw_brier'] for r in scores if r['ipcw_brier'] is not None]
    resolved = [r for r in rows if r['event']]
    medians = {}
    errors = []
    for row in resolved:
        key = tuple(row[k] for k in [*FIELDS, 'weekday', 'hour_band', 'age_band']) if candidate == 'piecewise_hazard' else row['priority'] if candidate == 'priority_median' else 'global'
        if key not in medians:
            medians[key] = median(model, row, candidate)
        errors.append(abs((medians[key] if medians[key] is not None else 168)-row['duration']))
    return {'n': len(rows), 'resolved_within_168h': len(resolved),
        'censored_before_168h': sum(not r['event'] and r['duration'] < 168 for r in rows),
        'mean_ipcw_brier': round(float(np.mean(comparable)), 5) if comparable else None,
        'brier_by_horizon': scores,
        'observed_event_median_mae_hours': round(float(np.mean(errors)), 2) if errors else None,
        'mae_note': 'Conditional on observed first resolutions within 168 h; medians beyond the horizon capped at 168. Not an all-case error.'}
