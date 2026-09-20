import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def job(monkeypatch):
    spec = importlib.util.spec_from_file_location('forecast_job', Path(__file__).parents[1] / 'aws/forecast_job.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for key in ('RUN_TABLE', 'DATA_BUCKET', 'WEB_BUCKET'):
        monkeypatch.setenv(key, key.lower())
    return module


def test_failed_attempt_releases_owned_lease(job, monkeypatch):
    ddb = Mock()
    monkeypatch.setattr(job.boto3, 'client', lambda name: ddb)
    monkeypatch.setattr(job, 'run', Mock(side_effect=ValueError('source failed')))
    with pytest.raises(ValueError, match='source failed'):
        job.handler({}, SimpleNamespace(aws_request_id='attempt-1'))
    assert ddb.put_item.call_args.kwargs['Item']['pk']['S'] == 'forecast-lock'
    assert ddb.delete_item.call_args.kwargs['ExpressionAttributeValues'][':owner']['S'] == 'attempt-1'


def test_busy_lease_never_runs_or_deletes_another_owner(job, monkeypatch):
    ddb = Mock()
    ddb.put_item.side_effect = RuntimeError('already leased')
    monkeypatch.setattr(job.boto3, 'client', lambda name: ddb)
    run = Mock()
    monkeypatch.setattr(job, 'run', run)
    with pytest.raises(RuntimeError, match='already leased'):
        job.handler({}, SimpleNamespace(aws_request_id='attempt-2'))
    run.assert_not_called()
    ddb.delete_item.assert_not_called()


@pytest.mark.parametrize('drill', [True, False])
def test_failure_or_lost_lease_preserves_published_report(job, monkeypatch, drill):
    s3, metrics = Mock(), Mock()
    s3.list_objects_v2.return_value = {}
    monkeypatch.setattr(job.boto3, 'client', lambda name: s3 if name == 's3' else metrics)
    monkeypatch.setattr(job, 'fetch', lambda **kwargs: {'source': {'reporting_lag_days': 2}})
    monkeypatch.setattr(job, 'build', lambda source: {'series': []})
    verify = Mock(side_effect=ValueError('lease lost'))
    with pytest.raises(ValueError):
        job.run({'failure_drill': drill}, verify)
    s3.put_object.assert_not_called()
    metrics.put_metric_data.assert_not_called()
