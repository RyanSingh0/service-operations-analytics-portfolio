import os
import time
from datetime import datetime, timedelta, timezone


def summarize(ddb):
    table = os.environ.get('USAGE_TABLE')
    if not table:
        return {'status': 'Not configured', 'total_views': None}
    today = datetime.now(timezone.utc).date()
    days = [(today-timedelta(days=i)).isoformat() for i in range(1, 29)]
    request = {table: {'Keys': [{'day': {'S': day}} for day in days], 'ConsistentRead': True}}
    rows = []
    for attempt in range(3):
        result = ddb.batch_get_item(RequestItems=request)
        rows.extend(result.get('Responses', {}).get(table, []))
        request = result.get('UnprocessedKeys', {})
        if not request:
            break
        time.sleep(.1*(attempt+1))
    if request:
        raise ValueError('Usage read incomplete')
    counts = {row['day']['S']: {page: int(row.get(page, {}).get('N', '0'))
              for page in ('it', 'forecast', 'resolution', 'total')} for row in rows}
    start = max(min(days), os.environ.get('USAGE_START_DATE') or min(counts, default=today.isoformat()))
    included = sorted(day for day in days if day >= start)
    return {'status': 'Collecting first complete day' if not included else 'Available',
        'start': start, 'through': max(days), 'total_views': sum(counts.get(d, {}).get('total', 0) for d in included),
        'pages': {p: sum(counts.get(d, {}).get(p, 0) for d in included) for p in ('it', 'forecast', 'resolution')},
        'daily': [{'date': d, 'views': counts.get(d, {}).get('total', 0)} for d in included],
        'definition': 'Accepted page-view signals over up to 28 complete UTC days. Repeat visits, maintainers '
                      'and bots may be included; blocked scripts and throttled requests are omitted. '
                      'No cookies or visitor identifiers are stored. This is not a unique-person count.'}
