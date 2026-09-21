import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone


def fetch_weather(source, previous=None):
    start = date.fromisoformat(source['dates'][0])-timedelta(days=12)
    end = date.fromisoformat(source['dates'][-1])-timedelta(days=5)
    days = dict(previous.get('days', {})) if previous else {}
    cursor = max(start, end-timedelta(days=30)) if days and min(days) <= start.isoformat() else start
    params = {'latitude': 40.7128, 'longitude': -74.0060, 'start_date': cursor.isoformat(),
        'end_date': end.isoformat(), 'daily': 'temperature_2m_mean,precipitation_sum',
        'timezone': 'America/New_York', 'models': 'era5'}
    url = 'https://archive-api.open-meteo.com/v1/archive?'+urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = json.load(response)['daily']
    for day, temperature, rain in zip(raw['time'], raw['temperature_2m_mean'], raw['precipitation_sum']):
        if temperature is None or rain is None:
            raise ValueError('Weather observations incomplete')
        days[day] = [float(temperature), float(rain)]
    days = {k: v for k, v in days.items() if start.isoformat() <= k <= end.isoformat()}
    if len(days) != (end-start).days+1:
        raise ValueError('Weather date coverage incomplete')
    return {'days': days, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'source': 'Open-Meteo ERA5 reanalysis, NYC central grid cell',
        'url': 'https://open-meteo.com/en/docs/historical-weather-api', 'through': end.isoformat(),
        'contract': 'Shadow challenger only. Weather ends five days before each demand origin; '
                    'no realized future weather. Reanalysis is revised, not historical publication vintages.'}


def holidays(year):
    fixed = [date(year, m, d) for m, d in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25))]
    result = set(fixed)
    for day in fixed:
        if day.weekday() == 5:
            result.add(day-timedelta(days=1))
        elif day.weekday() == 6:
            result.add(day+timedelta(days=1))
    for month, weekday, nth in ((1, 0, 3), (2, 0, 3), (9, 0, 1), (10, 0, 2), (11, 3, 4)):
        first = date(year, month, 1)
        result.add(first+timedelta(days=(weekday-first.weekday()) % 7+7*(nth-1)))
    last = date(year, 5, 31)
    result.add(last-timedelta(days=last.weekday()))
    return result


def extra_features(days, origin, horizon, weather):
    target = days[origin]+timedelta(days=horizon)
    calendar = holidays(target.year-1) | holidays(target.year) | holidays(target.year+1)
    samples = [weather['days'][(days[origin]-timedelta(days=lag)).isoformat()] for lag in range(5, 12)]
    return [float(target in calendar), float(target-timedelta(days=1) in calendar),
            float(target+timedelta(days=1) in calendar),
            sum(v[0] for v in samples)/140, sum(v[1] for v in samples)/140]
