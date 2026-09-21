import argparse
import csv
import gzip
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from serviceops.domain import parse_time, validate_headers

ROOT = Path(__file__).resolve().parents[1]


def deploy_stack(client, name, template, parameters):
    args = {"StackName": name, "TemplateBody": template.read_text(),
            "Parameters": [{"ParameterKey": k, "ParameterValue": str(v)} for k, v in parameters.items()],
            "Capabilities": ["CAPABILITY_IAM"],
            "Tags": [{"Key": "Project", "Value": "service-operations-analytics"}]}
    try:
        client.describe_stacks(StackName=name)
    except ClientError as error:
        if "does not exist" not in str(error):
            raise
        client.create_stack(**args)
        operation = "create"
    else:
        try:
            client.update_stack(**args)
        except ClientError as error:
            if "No updates are to be performed" not in str(error):
                raise
            return client.describe_stacks(StackName=name)["Stacks"][0]
        operation = "update"
    print(f"Waiting for {name} ({operation})...", flush=True)
    client.get_waiter(f"stack_{operation}_complete").wait(
        StackName=name, WaiterConfig={"Delay": 10, "MaxAttempts": 120})
    return client.describe_stacks(StackName=name)["Stacks"][0]


def outputs(stack):
    return {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}


def zip_bytes(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def package_source(path):
    data = path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    validate_headers(reader.fieldnames or [])
    buffer = io.BytesIO()
    times = []
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as zipped:
        for line, row in enumerate(reader, 2):
            row["source_row"] = line
            zipped.write((json.dumps(row) + "\n").encode())
            try:
                timestamp = parse_time(row["sys_updated_at"])
                if timestamp:
                    times.append(timestamp)
            except ValueError:
                pass
    return checksum, buffer.getvalue(), max(times).isoformat(sep=" ")


def main():
    parser = argparse.ArgumentParser(description="Deploy and operate the AWS demonstration")
    parser.add_argument("command", choices=["deploy", "run", "status", "dashboard", "enable", "disable", "query"])
    parser.add_argument("--profile", default="serviceops")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack", default="serviceops-demo")
    parser.add_argument("--alert-email", default="")
    parser.add_argument("--as-of")
    parser.add_argument("--advance-checkpoint", action="store_true")
    parser.add_argument("--failure-drill", action="store_true")
    parser.add_argument("--execution")
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cf, s3 = session.client("cloudformation"), session.client("s3", config=Config(signature_version="s3v4"))
    if args.command == "deploy":
        source = ROOT / "data/raw/incident_event_log.csv"
        if not source.exists():
            raise SystemExit("Download the source with serviceops download before deployment")
        identity = session.client("sts").get_caller_identity()
        print(f"Target account: {identity['Account']}; region: {args.region}", flush=True)
        bootstrap = deploy_stack(cf, args.stack + "-storage", ROOT / "infrastructure/bootstrap.yaml", {})
        bucket = outputs(bootstrap)["DataBucket"]
        from package_batches import package
        from release import upload
        website_parameters = {}
        try:
            existing_website = cf.describe_stacks(StackName=args.stack + "-website")["Stacks"][0]
            website_parameters = {p["ParameterKey"]: p["ParameterValue"]
                                  for p in existing_website["Parameters"]
                                  if p["ParameterKey"] == "AnalyticsOrigin"}
        except ClientError as error:
            if "does not exist" not in str(error):
                raise
        website = outputs(deploy_stack(cf, args.stack + "-website", ROOT / "infrastructure/website.yaml", website_parameters))
        version = upload(session, bucket, website["WebBucket"])
        registry = package(source, ROOT / "build/batches")
        try:
            existing = json.loads(s3.get_object(Bucket=bucket, Key="source/registry.json")["Body"].read())
        except ClientError as error:
            if error.response["Error"]["Code"] != "NoSuchKey":
                raise
            existing = None
        if existing and existing["dataset_sha256"] != registry["dataset_sha256"]:
            raise ValueError("Refusing to replace the existing dataset identity")
        for batch in registry["batches"]:
            body = (ROOT / "build/batches" / Path(batch["key"]).name).read_bytes()
            try:
                s3.put_object(Bucket=bucket, Key=batch["key"], Body=body, IfNoneMatch="*")
            except ClientError as error:
                if error.response["Error"]["Code"] != "PreconditionFailed":
                    raise
                stored = s3.get_object(Bucket=bucket, Key=batch["key"])["Body"].read()
                if hashlib.sha256(stored).hexdigest() != batch["sha256"]:
                    raise ValueError("Existing immutable batch checksum mismatch")
        if existing is None:
            s3.put_object(Bucket=bucket, Key="source/registry.json", Body=json.dumps(registry).encode(), IfNoneMatch="*")
        stack = deploy_stack(cf, args.stack, ROOT / "infrastructure/pipeline.yaml", {
            "DataBucket": bucket, "WebBucket": website["WebBucket"], "CodeVersion": version,
            "AlertEmail": args.alert_email, "ScheduleState": "DISABLED",
        })
        result = {**outputs(stack), **website}
        (ROOT / "deployment.local.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        return
    out = outputs(cf.describe_stacks(StackName=args.stack)["Stacks"][0])
    states = session.client("stepfunctions")
    if args.command == "run":
        payload = {"failure_drill": args.failure_drill}
        if args.as_of:
            payload["as_of"] = args.as_of
        result = states.start_execution(stateMachineArn=out["WorkflowArn"],
            name=f"manual-{int(time.time())}", input=json.dumps(payload))
        print(result["executionArn"])
    elif args.command == "status":
        if args.execution:
            result = states.describe_execution(executionArn=args.execution)
            print(json.dumps({k: str(v) for k, v in result.items() if k != "ResponseMetadata"}, indent=2))
        else:
            results = states.list_executions(stateMachineArn=out["WorkflowArn"], maxResults=5)
            print(json.dumps(results["executions"], default=str, indent=2))
    elif args.command == "dashboard":
        print(outputs(cf.describe_stacks(StackName=args.stack + "-website")["Stacks"][0])["WebsiteUrl"])
    elif args.command in {"enable", "disable"}:
        scheduler = session.client("scheduler")
        schedule = scheduler.get_schedule(Name=out["ScheduleName"])
        scheduler.update_schedule(Name=out["ScheduleName"], State="ENABLED" if args.command == "enable" else "DISABLED",
            ScheduleExpression=schedule["ScheduleExpression"], FlexibleTimeWindow=schedule["FlexibleTimeWindow"],
            ScheduleExpressionTimezone=schedule["ScheduleExpressionTimezone"], Target=schedule["Target"])
        print(f"Weekly replay schedule {args.command}d")
    elif args.command == "query":
        athena = session.client("athena")
        sql = (ROOT / "sql/queue_health.sql").read_text()
        result = athena.start_query_execution(QueryString=sql, WorkGroup=out["Workgroup"],
            QueryExecutionContext={"Database": out["Database"]})
        query_id = result["QueryExecutionId"]
        for _ in range(60):
            query = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
            status = query["Status"]["State"]
            if status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(1)
        if status != "SUCCEEDED":
            raise RuntimeError(query["Status"])
        print(json.dumps({"query_id": query_id, "statistics": query["Statistics"],
            "rows": athena.get_query_results(QueryExecutionId=query_id, MaxResults=15)["ResultSet"]["Rows"]}, indent=2))


if __name__ == "__main__":
    main()
