import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ENDPOINT = 'https://data.cityofnewyork.us/resource/erm2-nwe9.json'
BOROUGHS = ('BRONX', 'BROOKLYN', 'MANHATTAN', 'QUEENS', 'STATEN ISLAND')
BATCH_DAYS = 14
EXTRACT_SECONDS = 600


class ExtractDeadlineExceeded(RuntimeError):
    pass


def remaining_seconds(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExtractDeadlineExceeded('Source extraction exceeded its time budget; preserving the previous report')
    return remaining


def retryable(error):
    if isinstance(error, urllib.error.HTTPError):
        return error.code == 429 or 500 <= error.code < 600
    return isinstance(error, (urllib.error.URLError, TimeoutError))


def query(parameters, *, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + EXTRACT_SECONDS
    url = ENDPOINT + '?' + urllib.parse.urlencode(parameters)
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'ServiceOperationsAnalytics/1.0'})
            with urllib.request.urlopen(request, timeout=min(45, remaining_seconds(deadline))) as response:
                result = json.load(response)
            remaining_seconds(deadline)
            if not isinstance(result, list):
                raise ValueError('Source returned an unexpected response')
            return result
        except (urllib.error.URLError, TimeoutError) as error:
            if not retryable(error) or attempt == 2:
                raise
            delay = min(2 ** attempt, remaining_seconds(deadline))
            print(f'Source request retry {attempt+1}: {type(error).__name__}', flush=True)
            time.sleep(delay)


def fetch_window(start, stop, deadline):
    remaining_seconds(deadline)
    try:
        rows = query({'$select': 'date_trunc_ymd(created_date) as day, borough, count(*) as requests',
            '$where': f"created_date >= '{start}T00:00:00' AND created_date < '{stop}T00:00:00'",
            '$group': 'day, borough', '$order': 'day, borough', '$limit': '10000'}, deadline=deadline)
    except (urllib.error.URLError, TimeoutError) as error:
        if not retryable(error) or (stop-start).days <= 1:
            raise
        middle = start + timedelta(days=(stop-start).days // 2)
        print(f'Splitting slow source batch: {start} to {stop-timedelta(days=1)}', flush=True)
        return fetch_window(start, middle, deadline) + fetch_window(middle, stop, deadline)
    if len(rows) >= 10000:
        raise ValueError('Source query may be truncated')
    print(f'Fetched daily aggregates: {start} to {stop-timedelta(days=1)}', flush=True)
    return rows


def validate(rows, start, end):
    values = {}
    other = 0
    for row in rows:
        day = date.fromisoformat(row['day'][:10])
        borough = row.get('borough', 'Unknown')
        count = int(row['requests'])
        if count <= 0 or str(count) != str(row['requests']) or not start <= day <= end:
            raise ValueError('Invalid date or count in source aggregate')
        key = (day, borough)
        if key in values:
            raise ValueError('Duplicate date/borough aggregate')
        values[key] = count
        if borough not in BOROUGHS:
            other += count
    days = [start + timedelta(days=i) for i in range((end-start).days + 1)]
    # Missing dense city series is a failed extract, not zero demand.
    if any((day, borough) not in values for day in days for borough in BOROUGHS):
        raise ValueError('Incomplete daily borough coverage; refusing to invent zero demand')
    series = {borough: [values[(day, borough)] for day in days] for borough in BOROUGHS}
    totals = {day: 0 for day in days}
    for (day, _), count in values.items():
        totals[day] += count
    series['NYC TOTAL'] = [totals[day] for day in days]
    if any(sum(series[b][i] for b in BOROUGHS) > series['NYC TOTAL'][i] for i in range(len(days))):
        raise ValueError('Borough counts exceed city total')
    return {'dates': [d.isoformat() for d in days], 'series': series,
            'quality': {'days': len(days), 'rows': len(rows), 'unknown_borough_requests': other,
                        'unique_date_borough': True, 'complete_borough_days': True,
                        'nonnegative_counts': True, 'city_totals_reconcile': True}}


def fetch(today=None, previous=None):
    deadline = time.monotonic() + EXTRACT_SECONDS
    today = today or datetime.now(timezone.utc).date()
    latest = query({'$select': 'max(created_date) as latest',
                    '$where': f"created_date >= '{today-timedelta(days=14)}T00:00:00'"}, deadline=deadline)
    if not latest or not latest[0].get('latest'):
        raise ValueError('No recent source observations')
    latest_day = date.fromisoformat(latest[0]['latest'][:10])
    if latest_day > today:
        raise ValueError('Source contains a future maximum date')
    end = min(today-timedelta(days=2), latest_day-timedelta(days=1))
    if (today-end).days > 7:
        raise ValueError('Source is more than seven days behind')
    if previous and previous['source']['data_through'] > end.isoformat():
        raise ValueError('Source cutoff regressed; preserving the previous report')
    start = end-timedelta(days=729)
    rows = []
    full_refresh = today.isoformat()
    cursor = start
    if previous and previous['dates'][0] <= start.isoformat():
        last_full = date.fromisoformat(previous['source'].get('full_refresh_date', previous['source']['data_through']))
        refresh_from = end-timedelta(days=59)
        if (today-last_full).days < 30 and previous['dates'][-1] >= refresh_from.isoformat():
            full_refresh = last_full.isoformat()
            for index, day in enumerate(previous['dates']):
                if not start.isoformat() <= day < refresh_from.isoformat():
                    continue
                for borough in BOROUGHS:
                    rows.append({'day': day, 'borough': borough,
                                 'requests': str(previous['series'][borough][index])})
                unknown = previous['series']['NYC TOTAL'][index]-sum(previous['series'][b][index] for b in BOROUGHS)
                if unknown:
                    rows.append({'day': day, 'borough': 'Unknown', 'requests': str(unknown)})
            cursor = refresh_from
    while cursor <= end:
        stop = min(cursor+timedelta(days=BATCH_DAYS), end+timedelta(days=1))
        rows.extend(fetch_window(cursor, stop, deadline))
        cursor = stop
    result = validate(rows, start, end)
    result['source'] = {'name': 'NYC 311 Service Requests from 2020 to Present',
        'url': 'https://data.cityofnewyork.us/d/erm2-nwe9', 'endpoint': ENDPOINT,
        'latest_created_at': latest[0]['latest'], 'data_through': end.isoformat(),
        'retrieved_at': datetime.now(timezone.utc).isoformat(), 'publication_frequency': 'daily',
        'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
        'reporting_lag_days': (today-end).days, 'full_refresh_date': full_refresh,
        'correction_policy': 'Refresh the last 60 days daily; rebuild the full two-year window every 30 days.'}
    return result
