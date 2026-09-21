import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture
def collector(monkeypatch):
    path = Path(__file__).parents[1] / 'aws/page_views.py'
    spec = importlib.util.spec_from_file_location('page_views', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv('WEBSITE_ORIGIN', 'https://example.com')
    monkeypatch.setenv('USAGE_TABLE', 'counts')
    return module


def test_collector_only_persists_daily_aggregate(collector, monkeypatch):
    ddb = Mock()
    monkeypatch.setattr(collector.boto3, 'client', lambda name: ddb)
    response = collector.handler({'body': '{"page":"forecast"}',
        'headers': {'origin': 'https://example.com'}, 'requestContext': {'http': {'sourceIp': '1.2.3.4'}}}, None)
    assert response['statusCode'] == 204
    saved = str(ddb.update_item.call_args)
    assert '1.2.3.4' not in saved
    assert '10000' in saved
    assert 'forecast' in saved


@pytest.mark.parametrize('body,origin', [('{}','https://example.com'),
    ('{"page":"forecast","email":"x"}','https://example.com'),
    ('{"page":"forecast"}','https://attacker.example'), ('{"page":[]}', 'https://example.com')])
def test_invalid_beacons_never_write(collector, monkeypatch, body, origin):
    client = Mock()
    monkeypatch.setattr(collector.boto3, 'client', client)
    assert collector.handler({'body': body, 'headers': {'origin': origin}}, None)['statusCode'] in (400, 403)
    client.assert_not_called()
