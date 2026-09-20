import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def coordinator(monkeypatch):
    clients = {name: Mock() for name in ("s3", "dynamodb", "glue", "cloudwatch")}
    class Conflict(Exception):
        pass
    clients["dynamodb"].exceptions = SimpleNamespace(ConditionalCheckFailedException=Conflict)
    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=clients.__getitem__))
    monkeypatch.setenv("DATA_BUCKET", "test-bucket")
    monkeypatch.setenv("RUN_TABLE", "test-runs")
    monkeypatch.setenv("CODE_VERSION", "v1")
    path = Path(__file__).resolve().parents[1] / "aws/coordinator_v2.py"
    spec = importlib.util.spec_from_file_location("coordinator_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, clients


def test_lock_release_is_conditional_on_execution_owner(coordinator):
    module, clients = coordinator
    module.release("execution-one")
    kwargs = clients["dynamodb"].delete_item.call_args.kwargs
    assert kwargs["ConditionExpression"] == "#owner = :owner"
    assert kwargs["ExpressionAttributeNames"]["#owner"] == "owner"
    assert kwargs["ExpressionAttributeValues"][":owner"] == {"S": "execution-one"}


def test_release_does_not_remove_a_different_execution_lock(coordinator):
    module, clients = coordinator
    clients["dynamodb"].delete_item.side_effect = clients["dynamodb"].exceptions.ConditionalCheckFailedException()
    module.release("old-owner")
    assert clients["dynamodb"].delete_item.call_count == 1


def test_duplicate_completion_skips_glue_work(coordinator):
    module, clients = coordinator
    from serviceops.incremental import digest
    registry = {"schema_version": 2, "dataset_sha256": "a" * 64, "batches": [], "max_as_of": "2017-01-01 00:00:00"}
    run_id = digest({"batches": [], "as_of": "2016-05-01 23:59:59", "version": "v1"})[:20]
    previous = {"run_id": run_id, "attempt": "done", "as_of": "2016-05-01 23:59:59", "dataset_sha256": "a" * 64}
    module.get_json = Mock(side_effect=[registry, previous])
    module.publish_web = Mock()
    result = module.handler({"action": "prepare", "owner": "run-one",
                             "input": {"as_of": "2016-05-01 23:59:59"}}, None)
    assert result["skip"] is True
    clients["dynamodb"].delete_item.assert_called_once()


def test_failed_quality_gate_does_not_publish(coordinator):
    module, clients = coordinator
    clients["s3"].get_object.return_value = {
        "Body": io.BytesIO(json.dumps({"quality": {"batch": {"reject_rate": .5}}}).encode())}
    with pytest.raises(ValueError, match="quality gate"):
        module.handler({"action": "publish", "owner": "run-one",
                        "prepared": {"attempt": "attempt-one"}}, None)
    clients["s3"].put_object.assert_not_called()
    clients["glue"].update_table.assert_not_called()


def test_lock_conflict_never_releases_another_execution(coordinator):
    module, clients = coordinator
    clients["dynamodb"].put_item.side_effect = clients["dynamodb"].exceptions.ConditionalCheckFailedException()
    with pytest.raises(clients["dynamodb"].exceptions.ConditionalCheckFailedException):
        module.handler({"action": "prepare", "owner": "second-run", "input": {}}, None)
    clients["dynamodb"].delete_item.assert_not_called()


def test_expired_lease_cannot_publish(coordinator):
    module, clients = coordinator
    module.get_json = Mock(return_value={"quality": {"batch": {"reject_rate": 0}}, "integrity": {"test": True}})
    clients["dynamodb"].get_item.return_value = {"Item": {"owner": {"S": "owner"}, "expires": {"N": "0"}}}
    with pytest.raises(ValueError, match="unexpired lock"):
        module.handler({"action": "publish", "owner": "owner", "prepared": {"attempt": "run"}}, None)
    clients["s3"].put_object.assert_not_called()


def test_catalog_failure_restores_previous_catalog_before_commit(coordinator):
    import time
    module, clients = coordinator
    report = {"quality": {"batch": {"reject_rate": 0}}, "integrity": {"test": True}}
    module.get_json = Mock(side_effect=[report, {}, {"attempt": "previous"}])
    clients["dynamodb"].get_item.return_value = {"Item": {"owner": {"S": "owner"}, "expires": {"N": str(int(time.time()) + 1000)}}}
    module.catalog = Mock(side_effect=[RuntimeError("catalog unavailable"), None])
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        module.handler({"action": "publish", "owner": "owner", "prepared": {"attempt": "next", "run_id": "id"}}, None)
    assert [call.args[0] for call in module.catalog.call_args_list] == ["next", "previous"]
    clients["s3"].put_object.assert_not_called()


def test_failed_publication_is_repaired_on_duplicate_prepare(coordinator):
    module, clients = coordinator
    from serviceops.incremental import digest
    registry = {"schema_version": 2, "dataset_sha256": "a" * 64, "batches": [], "max_as_of": "2017-01-01 00:00:00"}
    run_id = digest({"batches": [], "as_of": "2016-05-01 23:59:59", "version": "v1"})[:20]
    module.get_json = Mock(side_effect=[registry, {"run_id": run_id, "attempt": "committed", "as_of": "2016-05-01 23:59:59", "dataset_sha256": "a" * 64}])
    module.publish_web = Mock()
    result = module.handler({"action": "prepare", "owner": "repair", "input": {"as_of": "2016-05-01 23:59:59"}}, None)
    assert result["skip"]
    module.publish_web.assert_called_once_with("committed")
