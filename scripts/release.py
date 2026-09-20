import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[1]


def zip_files(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return stream.getvalue()


def artifacts():
    files = [(p, str(p.relative_to(ROOT / "src")).replace("\\", "/"))
             for p in sorted((ROOT / "src/serviceops").glob("*.py"))]
    package = zip_files(files)
    handler = ROOT / "aws/coordinator_v2.py"
    job = (ROOT / "aws/incremental_job.py").read_bytes()
    html, js = [(ROOT / "dashboard" / name).read_bytes() for name in ["index.html", "app.js"]]
    sql = {p.name: p.read_bytes() for p in sorted((ROOT / "sql").glob("*.sql"))}
    version = hashlib.sha256(package + handler.read_bytes() + job + html + js + b"".join(sql.values())).hexdigest()[:16]
    return version, {"serviceops.zip": package, "glue_job.py": job, **sql,
                     "lambda.zip": zip_files([(handler, "handler.py"), *files])}


def upload(session, bucket, web_bucket):
    s3 = session.client("s3")
    version, files = artifacts()
    for name, content in files.items():
        s3.put_object(Bucket=bucket, Key=f"artifacts/{version}/{name}", Body=content)
    for name, mime in [("index.html", "text/html; charset=utf-8"), ("app.js", "text/javascript; charset=utf-8")]:
        s3.put_object(Bucket=web_bucket, Key=name, Body=(ROOT / "dashboard" / name).read_bytes(),
                      ContentType=mime, CacheControl="max-age=60, must-revalidate")
    return version


def release(session, config):
    ddb, function = session.client("dynamodb"), session.client("lambda")
    owner = "deploy-" + os.environ.get("GITHUB_RUN_ID", str(int(time.time())))
    ddb.put_item(TableName=config["RunTable"], Item={"pk": {"S": "pipeline-lock"},
        "owner": {"S": owner}, "expires": {"N": str(int(time.time()) + 3600)}},
        ConditionExpression="attribute_not_exists(pk) OR expires < :now",
        ExpressionAttributeValues={":now": {"N": str(int(time.time()))}})
    try:
        version = upload(session, config["DataBucket"], config["WebBucket"])
        existing = function.get_function_configuration(FunctionName=config["CoordinatorName"])
        if existing["Environment"]["Variables"].get("CODE_VERSION") != version:
            glue = session.client("glue")
            current = glue.get_job(JobName=config["GlueJob"])["Job"]
            allowed = ["Role", "GlueVersion", "WorkerType", "NumberOfWorkers", "Timeout", "MaxRetries", "ExecutionProperty"]
            update = {key: current[key] for key in allowed if key in current}
            update["Command"] = {**current["Command"], "ScriptLocation": f"s3://{config['DataBucket']}/artifacts/{version}/glue_job.py"}
            update["DefaultArguments"] = {**current["DefaultArguments"],
                "--SQL_PREFIX": f"artifacts/{version}",
                "--extra-py-files": f"s3://{config['DataBucket']}/artifacts/{version}/serviceops.zip"}
            glue.update_job(JobName=config["GlueJob"], JobUpdate=update)
            function.update_function_code(FunctionName=config["CoordinatorName"], S3Bucket=config["DataBucket"],
                                          S3Key=f"artifacts/{version}/lambda.zip")
            function.get_waiter("function_updated").wait(FunctionName=config["CoordinatorName"])
            variables = {**existing["Environment"]["Variables"], "CODE_VERSION": version}
            function.update_function_configuration(FunctionName=config["CoordinatorName"], Environment={"Variables": variables})
            function.get_waiter("function_updated").wait(FunctionName=config["CoordinatorName"])
        print(f"Application release ready: {version}", flush=True)
    finally:
        ddb.delete_item(TableName=config["RunTable"], Key={"pk": {"S": "pipeline-lock"}},
                        ConditionExpression="#owner = :owner", ExpressionAttributeNames={"#owner": "owner"},
                        ExpressionAttributeValues={":owner": {"S": owner}})
    states = session.client("stepfunctions")
    s3 = session.client("s3")
    commit = json.loads(s3.get_object(Bucket=config["DataBucket"], Key="internal/committed.json")["Body"].read())
    result = states.start_execution(stateMachineArn=config["WorkflowArn"], name=owner,
                                    input=json.dumps({"as_of": commit["as_of"]}))
    for _ in range(100):
        execution = states.describe_execution(executionArn=result["executionArn"])
        if execution["status"] != "RUNNING":
            break
        time.sleep(10)
    if execution["status"] != "SUCCEEDED":
        raise RuntimeError(f"Deployment smoke run: {execution['status']}")
    print(json.dumps({"version": version, "execution": result["executionArn"], "status": execution["status"]}))


if __name__ == "__main__":
    config = {key: os.environ[key] for key in ["DataBucket", "WebBucket", "CoordinatorName", "GlueJob", "RunTable", "WorkflowArn"]}
    release(boto3.Session(region_name=os.environ.get("AWS_REGION", "us-east-1")), config)
