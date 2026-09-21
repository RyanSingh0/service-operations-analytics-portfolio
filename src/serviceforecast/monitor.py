from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo


def revision_summary(previous, current):
    if not previous:
        return {'status': 'First source snapshot; comparison starts next run'}
    old = {day: i for i, day in enumerate(previous['dates'])}
    changed, absolute, net = 0, 0, 0
    for i, day in enumerate(current['dates']):
        if day in old:
            delta = current['series']['NYC TOTAL'][i] - previous['series']['NYC TOTAL'][old[day]]
            changed += delta != 0
            absolute += abs(delta)
            net += delta
    return {'status': 'Compared overlapping source dates', 'changed_city_dates': changed,
            'absolute_revised_requests': absolute, 'net_revised_requests': net,
            'previous_cutoff': previous['source']['data_through']}


def issuance(report):
    issued = datetime.fromisoformat(report['generated_at']).astimezone(ZoneInfo('America/New_York')).date()
    rows = []
    for series, data in report['series'].items():
        for row in data['forecast']:
            lead = (date.fromisoformat(row['date']) - issued).days
            if lead > 0:
                rows.append({'series': series, 'target': row['date'], 'issued_date': issued.isoformat(),
                    'issued_at': report['generated_at'], 'source_through': report['source']['data_through'],
                    'lead_days': lead, 'model': data['selected_model'], 'version': report['model_version'],
                    'prediction': row['forecast'], 'lower': row['lower'], 'upper': row['upper'],
                    'candidates': row.get('candidates', {})})
    return {'issued_date': issued.isoformat(), 'rows': rows}


def update(state, source, previous=None):
    state = state or {'issues': {}, 'final_actuals': {}, 'started_at': source['source']['retrieved_at']}
    cutoff = date.fromisoformat(source['source']['data_through'])
    oldest = (cutoff - timedelta(days=120)).isoformat()
    state['issues'] = {k: v for k, v in state['issues'].items() if k >= oldest}
    state['final_actuals'] = {k: v for k, v in state['final_actuals'].items() if k.split('|')[1] >= oldest}
    dates = {day: i for i, day in enumerate(source['dates'])}
    mature = (cutoff - timedelta(days=7)).isoformat()
    grouped = defaultdict(list)
    provisional = defaultdict(int)
    for rows in state['issues'].values():
        for row in rows:
            target, series = row['target'], row['series']
            if target not in dates:
                continue
            if target > mature:
                provisional[series] += 1
                continue
            key = series + '|' + target
            state['final_actuals'].setdefault(key, {'value': source['series'][series][dates[target]],
                'observed_at': source['source']['retrieved_at'], 'source_sha256': source['source']['sha256']})
            grouped[series].append({**row, 'actual': state['final_actuals'][key]['value']})
    summary = {'started_at': state['started_at'], 'through': mature, 'series': {},
        'source_revisions': revision_summary(previous, source),
        'contract': 'First successful publication per New York calendar day; only future target dates. '
                    'Actuals freeze once the source cutoff passes the target by 7 days. '
                    'Weekly metrics group by target week and include overlapping forecast origins; '
                    'counts are predictions, not independent observations. No historical backfill.'}
    for series, values in source['series'].items():
        rows = grouped[series]
        recent = [r for r in rows if r['target'] >= (cutoff-timedelta(days=56)).isoformat()]
        weeks = defaultdict(list)
        for row in recent:
            day = date.fromisoformat(row['target'])
            weeks[(day-timedelta(days=day.weekday())).isoformat()].append(row)
        total = sum(r['actual'] for r in recent)
        coverage = mean(r['lower'] <= r['actual'] <= r['upper'] for r in recent)*100 if recent else None
        distinct = len({r['target'] for r in recent})
        enough = len(recent) >= 28 and distinct >= 14
        shift = (mean(values[-28:])/mean(values[-56:-28])-1)*100 if mean(values[-56:-28]) else None
        record = {'scored_predictions': len(recent), 'distinct_target_dates': distinct,
            'awaiting_mature_actuals': provisional[series], 'coverage_pct': round(coverage, 1) if coverage is not None else None,
            'status': 'Collecting outcomes' if not enough else 'Undercoverage warning' if coverage < 80 else 'Monitoring',
            'demand_shift_pct': round(shift, 1) if shift is not None else None,
            'demand_shift_warning': shift is not None and abs(shift) > 30,
            'wape_pct': round(100*sum(abs(r['prediction']-r['actual']) for r in recent)/total, 2) if total else None,
            'weekly': [], 'by_lead': [], 'candidate_wape_pct': {}}
        for week, items in sorted(weeks.items()):
            denominator = sum(r['actual'] for r in items)
            record['weekly'].append({'week': week, 'predictions': len(items), 'dates': len({r['target'] for r in items}),
                'wape_pct': round(100*sum(abs(r['prediction']-r['actual']) for r in items)/denominator, 2) if denominator else None,
                'coverage_pct': round(100*mean(r['lower'] <= r['actual'] <= r['upper'] for r in items), 1)})
        for lo, hi in ((1, 3), (4, 7), (8, 14)):
            items = [r for r in recent if lo <= r['lead_days'] <= hi]
            denominator = sum(r['actual'] for r in items)
            record['by_lead'].append({'lead': f'{lo}–{hi}', 'predictions': len(items),
                'wape_pct': round(100*sum(abs(r['prediction']-r['actual']) for r in items)/denominator, 2) if denominator else None})
        candidates = set().union(*(r.get('candidates', {}) for r in recent))
        for name in sorted(candidates):
            items = [r for r in recent if name in r.get('candidates', {})]
            denominator = sum(r['actual'] for r in items)
            record['candidate_wape_pct'][name] = {'predictions': len(items), 'wape_pct':
                round(100*sum(abs(r['candidates'][name]-r['actual']) for r in items)/denominator, 2) if denominator else None}
        summary['series'][series] = record
    return state, summary


def record_publication(state, report):
    issued = issuance(report)
    state['issues'].setdefault(issued['issued_date'], issued['rows'])
    return state
