import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from serviceops.incremental import digest, select_batches

s3 = boto3.client("s3")
ddb = boto3.client("dynamodb")
glue = boto3.client("glue")
cloudwatch = boto3.client("cloudwatch")
BUCKET = os.environ.get("DATA_BUCKET", "")
TABLE = os.environ.get("RUN_TABLE", "")


def publish_web(attempt):
    report = get_json(f"runs/{attempt}/report.json")
    # Only aggregate report fields cross into the website bucket.
    public = {key: report[key] for key in ["mode", "as_of", "timezone", "source", "summary",
              "quality", "groups", "daily", "definitions", "generated_at", "integrity", "profile", "workflow"]}
    public["quality"] = {k: v for k, v in public["quality"].items() if k != "source_sha256"}
    s3.put_object(Bucket=os.environ["WEB_BUCKET"], Key="report.json",
                  Body=json.dumps(public, allow_nan=False).encode(), ContentType="application/json",
                  CacheControl="no-cache, max-age=0, must-revalidate")

SCHEMAS = {
    "incidents": "incident_id:string,state:string,opened_at:string,updated_at:string,priority:string,assignment_group:string,category:string,is_open:boolean,reopen_count:bigint,reassignment_count:bigint,resolution_hours:double,age_hours:double,group_key:string,priority_key:string",
    "fact_incident_history": "incident_id:string,event_id:string,state:string,valid_from:string,valid_to:string,is_current:boolean,event_order:bigint,previous_state:string,transition_to_terminal:boolean,reopened_transition:boolean,group_key:string,priority_key:string",
    "dim_assignment_group": "group_key:string,assignment_group:string",
    "dim_priority": "priority_key:string,priority:string",
    "fact_daily_queue": "date:string,first_observed:bigint,resolved_transitions:bigint,reopened_transitions:bigint,starting_backlog:bigint,backlog:bigint,balance_ok:boolean",
    "event_revisions": "event_id:string,incident_id:string,revision:bigint,content_hash:string,batch_id:string,received_at:string,late_arrival:boolean,state:string,updated_at:string",
    "dim_date": "date_key:bigint,date:string,year:bigint,month:bigint,day:bigint,weekday:string,is_weekend:boolean",
}
SCHEMAS["fact_incident_snapshot"] = SCHEMAS["incidents"] + ",opened_date_key:bigint,snapshot_date_key:bigint"


def get_json(key, optional=False):
    try:
        return json.loads(s3.get_object(Bucket=BUCKET, Key=key)["Body"].read())
    except ClientError as error:
        if optional and error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
            return {}
        raise


def put_json(key, value):
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(value, allow_nan=False).encode(),
                  ContentType="application/json", CacheControl="no-store")


def release(owner):
    try:
        ddb.delete_item(TableName=TABLE, Key={"pk": {"S": "pipeline-lock"}},
                        ConditionExpression="#owner = :owner",
                        ExpressionAttributeNames={"#owner": "owner"},
                        ExpressionAttributeValues={":owner": {"S": owner}})
    except ddb.exceptions.ConditionalCheckFailedException:
        pass


def catalog(attempt):
    for name, columns in SCHEMAS.items():
        location = "fact_incident_snapshot" if name == "incidents" else name
        table = {"Name": name, "TableType": "EXTERNAL_TABLE",
                 "Parameters": {"classification": "parquet", "snapshot": attempt},
                 "StorageDescriptor": {
                     "Location": f"s3://{BUCKET}/runs/{attempt}/{location}/",
                     "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                     "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                     "SerdeInfo": {"SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"},
                     "Columns": [{"Name": c.split(":")[0], "Type": c.split(":")[1]}
                                 for c in columns.split(",")]}}
        try:
            glue.update_table(DatabaseName=os.environ["DATABASE"], TableInput=table)
        except glue.exceptions.EntityNotFoundException:
            glue.create_table(DatabaseName=os.environ["DATABASE"], TableInput=table)


def handler(event, context):
    action = event["action"]
    if action == "freshness":
        current = get_json("internal/committed.json", optional=True)
        age = ((datetime.now(timezone.utc) - datetime.fromisoformat(current["generated_at"])).total_seconds()
               / 86400) if current else 999
        registry = get_json("source/registry.json")
        pending = select_batches(registry, current.get("processed", {}), registry["max_as_of"])
        stale = int(bool(pending) and age > 9)
        cloudwatch.put_metric_data(Namespace="ServiceOperations", MetricData=[{
            "MetricName": "StalePipeline", "Value": stale, "Unit": "Count",
            "Dimensions": [{"Name": "Project", "Value": "serviceops-demo"}]}])
        return {"stale": bool(stale), "days_since_publication": age,
                "pending_batches": len(pending)}
    owner = event["owner"]
    if action == "release":
        release(owner)
        return {"released": True}
    if action == "prepare":
        now = int(time.time())
        ddb.put_item(TableName=TABLE, Item={"pk": {"S": "pipeline-lock"},
                     "owner": {"S": owner}, "expires": {"N": str(now + 3600)}},
                     ConditionExpression="attribute_not_exists(pk) OR expires < :now",
                     ExpressionAttributeValues={":now": {"N": str(now)}})
        try:
            registry = get_json("source/registry.json")
            previous = get_json("internal/committed.json", optional=True)
            request = event.get("input", {})
            requested = request.get("as_of")
            if requested:
                cutoff = datetime.fromisoformat(requested)
            else:
                cutoff = min(datetime.fromisoformat(previous.get("as_of", "2016-04-24 23:59:59"))
                             + timedelta(days=7), datetime.fromisoformat(registry["max_as_of"]))
            if cutoff.tzinfo is not None:
                raise ValueError("Use source-local timestamps without a timezone suffix")
            as_of = cutoff.isoformat(sep=" ")
            if previous and as_of < previous["as_of"]:
                raise ValueError("Committed cutoff cannot move backwards; use local replay for historical analysis")
            if previous and previous["dataset_sha256"] != registry["dataset_sha256"]:
                raise ValueError("Dataset identity changed")
            batches = select_batches(registry, previous.get("processed", {}), as_of)
            selected = [b for b in registry["batches"] if b["available_as_of"] <= as_of]
            run_id = digest({"batches": selected, "as_of": as_of,
                             "version": os.environ["CODE_VERSION"]})[:20]
            if previous.get("run_id") == run_id and not request.get("failure_drill"):
                publish_web(previous["attempt"])
                release(owner)
                return {"skip": True, "run_id": run_id}
            attempt = run_id + "-" + hashlib.sha256(owner.encode()).hexdigest()[:8]
            input_key = f"runs/{attempt}/input.json"
            put_json(input_key, {"previous": previous, "batches": batches,
                     "dataset_sha256": registry["dataset_sha256"], "max_as_of": registry["max_as_of"],
                     "failure_drill": bool(request.get("failure_drill"))})
            return {"skip": False, "run_id": run_id, "attempt": attempt,
                    "as_of": as_of, "input_key": input_key, "owner": owner}
        except Exception:
            release(owner)
            raise
    if action == "publish":
        prepared = event["prepared"]
        report = get_json(f"runs/{prepared['attempt']}/report.json")
        if (report["quality"]["batch"]["reject_rate"] > .01
                or not report.get("integrity") or not all(report["integrity"].values())):
            raise ValueError("Refusing to publish a failed quality gate")
        lock = ddb.get_item(TableName=TABLE, Key={"pk": {"S": "pipeline-lock"}},
                            ConsistentRead=True).get("Item", {})
        if lock.get("owner", {}).get("S") != owner or int(lock.get("expires", {}).get("N", "0")) <= time.time():
            raise ValueError("Publication requires the current unexpired lock")
        commit = get_json(f"runs/{prepared['attempt']}/commit.json")
        commit["run_id"] = prepared["run_id"]
        old = get_json("internal/committed.json", optional=True)
        try:
            catalog(prepared["attempt"])
        except Exception:
            if old:
                catalog(old["attempt"])
            raise
        # A single pointer is the commit boundary used by readers and the next run.
        put_json("internal/committed.json", commit)
        publish_web(prepared["attempt"])
        release(owner)
        return {"status": "published", "as_of": prepared["as_of"], "attempt": prepared["attempt"]}
    raise ValueError(f"Unsupported action: {action}")
