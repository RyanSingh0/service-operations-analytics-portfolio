import io
import json
import re
import urllib.error
from datetime import date, timedelta

import pytest

from serviceforecast import source


def test_transient_request_retries_then_succeeds(monkeypatch):
    calls = []
    sleeps = []
    def open_request(request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise TimeoutError('slow upstream')
        return io.BytesIO(b'[{"latest": "2026-10-04"}]')
    monkeypatch.setattr(source.urllib.request, 'urlopen', open_request)
    monkeypatch.setattr(source.time, 'sleep', sleeps.append)
    monkeypatch.setattr(source.time, 'monotonic', lambda: 100)
    assert source.query({}, deadline=120) == [{'latest': '2026-10-04'}]
    assert calls == [20, 20]
    assert sleeps == [1]


def test_permanent_http_error_is_not_retried_or_split(monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError(source.ENDPOINT, 400, 'Bad query', {}, None)
    monkeypatch.setattr(source.urllib.request, 'urlopen', fail)
    with pytest.raises(urllib.error.HTTPError):
        source.fetch_window(date(2026, 9, 1), date(2026, 9, 15), source.time.monotonic()+600)
    assert len(calls) == 1


def test_slow_batch_splits_without_missing_or_duplicating_dates(monkeypatch):
    windows = []
    def query(parameters, *, deadline):
        start, stop = [date.fromisoformat(d) for d in re.findall(r"'(\d{4}-\d{2}-\d{2})T", parameters['$where'])]
        windows.append((start, stop, deadline))
        if (stop-start).days > 7:
            raise TimeoutError('large query')
        return [{'day': str(start+timedelta(days=i))} for i in range((stop-start).days)]
    monkeypatch.setattr(source, 'query', query)
    deadline = source.time.monotonic()+600
    rows = source.fetch_window(date(2026, 9, 1), date(2026, 9, 15), deadline)
    assert [r['day'] for r in rows] == [str(date(2026, 9, 1)+timedelta(days=i)) for i in range(14)]
    assert len(windows) == 3
    assert {w[2] for w in windows} == {deadline}


def test_expired_budget_stops_before_another_request(monkeypatch):
    monkeypatch.setattr(source.time, 'monotonic', lambda: 601)
    def unexpected(*args, **kwargs):
        pytest.fail('Request started after extraction budget expired')
    monkeypatch.setattr(source.urllib.request, 'urlopen', unexpected)
    with pytest.raises(source.ExtractDeadlineExceeded):
        source.query({}, deadline=600)


def test_incremental_batches_preserve_complete_window_and_corrections(monkeypatch):
    today = date(2026, 10, 5)
    old_end = today-timedelta(days=3)
    old_dates = [str(old_end-timedelta(days=i)) for i in reversed(range(730))]
    previous = {'dates': old_dates, 'series': {b: [100]*730 for b in source.BOROUGHS},
                'source': {'data_through': str(old_end), 'full_refresh_date': '2026-09-17'}}
    previous['series']['NYC TOTAL'] = [512]*730
    windows = []
    def query(parameters, *, deadline):
        if 'max(' in parameters['$select']:
            return [{'latest': '2026-10-04T01:00:00'}]
        start, stop = [date.fromisoformat(d) for d in re.findall(r"'(\d{4}-\d{2}-\d{2})T", parameters['$where'])]
        windows.append((start, stop))
        return [{'day': str(start+timedelta(days=i)), 'borough': b, 'requests': str(n)}
                for i in range((stop-start).days) for b, n in [(b, 101) for b in source.BOROUGHS]+[('Unknown', 13)]]
    monkeypatch.setattr(source, 'query', query)
    before = json.dumps(previous)
    result = source.fetch(today=today, previous=previous)
    assert len(windows) == 5
    assert all((stop-start).days <= 14 for start, stop in windows)
    assert all(windows[i][1] == windows[i+1][0] for i in range(4))
    assert len(result['dates']) == 730
    assert result['dates'][-1] == '2026-10-03'
    assert result['series']['NYC TOTAL'] == [512]*670+[518]*60
    assert result['quality']['unknown_borough_requests'] == 12*670+13*60
    assert json.dumps(previous) == before
