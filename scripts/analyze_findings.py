import json
from pathlib import Path
from serviceops.pipeline import read_source
from serviceops.analytics import current_incidents

root = Path(__file__).resolve().parents[1]
events, rejected, checksum = read_source(root / 'data/raw/incident_event_log.csv')
(root / 'build').mkdir(parents=True, exist_ok=True)
cutoff = '2016-05-08 23:59:59'
visible = events.loc[events.updated_at.le(cutoff)]
latest = current_incidents(events, cutoff)
result = {'as_of': cutoff, 'source_sha256': checksum, 'groups': {}}
for group in ['Group 9','Unknown']:
    rows = latest.loc[latest.assignment_group.eq(group)]
    ids = set(rows.incident_id)
    history = visible.loc[visible.incident_id.isin(ids)]
    first = history.sort_values(['updated_at','sys_mod_count','source_row']).drop_duplicates('incident_id')
    later = current_incidents(events.loc[events.incident_id.isin(ids)], events.updated_at.max())
    result['groups'][group] = {'incidents': len(rows), 'open': int(rows.is_open.sum()),
        'reassigned': int(rows.reassignment_count.gt(0).sum()), 'states': rows.state.value_counts().to_dict(),
        'first_groups': first.assignment_group.value_counts().head(5).to_dict(),
        'opened_months': rows.opened_at.str[:7].value_counts().to_dict(),
        'median_open_age_hours': float(rows.loc[rows.is_open].age_hours.median()),
        'terminal_by_extract_end': int((~later.is_open).sum()),
        'later_group_counts': later.assignment_group.value_counts().head(5).to_dict(),
        'only_one_observed_group': int(history.groupby('incident_id').assignment_group.nunique().eq(1).sum())}
result['all'] = {'reassigned': int(latest.reassignment_count.gt(0).sum()),
    'incidents': len(latest), 'backlog': int(latest.is_open.sum())}
(root / 'build/findings.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
