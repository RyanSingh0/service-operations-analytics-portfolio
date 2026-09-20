import argparse
import json
import time
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser(description="Verify failure isolation, recovery, and duplicate suppression in AWS")
    parser.add_argument("--profile", default="serviceops")
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    config = json.loads(Path("deployment.local.json").read_text())
    s3, states = session.client("s3"), session.client("stepfunctions")

    def read(bucket, key):
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    def execute(label, payload):
        arn = states.start_execution(stateMachineArn=config["WorkflowArn"],
            name=f"exercise-{label}-{int(time.time())}", input=json.dumps(payload))["executionArn"]
        print(f"Started {label}: {arn}", flush=True)
        for _ in range(100):
            result = states.describe_execution(executionArn=arn)
            if result["status"] != "RUNNING":
                print(f"{label}: {result['status']}", flush=True)
                return arn, result
            time.sleep(10)
        raise TimeoutError("Exercise execution has not completed")

    before = read(config["DataBucket"], "internal/committed.json")
    public_before = read(config["WebBucket"], "report.json")
    failed_arn, failed = execute("failure", {"as_of": args.as_of, "failure_drill": True})
    assert failed["status"] == "FAILED", failed
    assert read(config["DataBucket"], "internal/committed.json") == before
    assert read(config["WebBucket"], "report.json") == public_before
    lock = session.client("dynamodb").get_item(TableName=config["RunTable"],
        Key={"pk": {"S": "pipeline-lock"}}, ConsistentRead=True)
    assert "Item" not in lock, "Failure cleanup left an active lock"
    recovered_arn, recovered = execute("recovery", {"as_of": args.as_of})
    assert recovered["status"] == "SUCCEEDED", recovered
    after = json.loads(read(config["DataBucket"], "internal/committed.json"))
    public_after = json.loads(read(config["WebBucket"], "report.json"))
    assert after["as_of"] == args.as_of == public_after["as_of"]
    duplicate_arn, duplicate = execute("duplicate", {"as_of": args.as_of})
    assert duplicate["status"] == "SUCCEEDED"
    events = states.get_execution_history(executionArn=duplicate_arn)["events"]
    entered = [r["stateEnteredEventDetails"]["name"] for r in events if "stateEnteredEventDetails" in r]
    assert "Transform" not in entered
    freshness = session.client("lambda").invoke(FunctionName=config["CoordinatorName"],
        Payload=json.dumps({"action": "freshness"}).encode())
    assert "FunctionError" not in freshness
    result = {"failure_execution": failed_arn, "recovery_execution": recovered_arn,
              "duplicate_execution": duplicate_arn, "previous_pointer_preserved_on_failure": True,
              "public_report_preserved_on_failure": True, "failure_lock_released": True,
              "recovery_status": recovered["status"], "duplicate_states": entered,
              "freshness": json.loads(freshness["Payload"].read()),
              "as_of": args.as_of, "summary": public_after["summary"]}
    Path("build/cloud-recovery.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
