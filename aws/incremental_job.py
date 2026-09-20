import gzip
import json
import sys
from datetime import datetime, timezone

import boto3
import pandas as pd
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import functions as F

from serviceops.incremental import decode_batch, enforce_quality, merge_batches
from serviceops.reporting import assemble

args = getResolvedOptions(sys.argv, [
    "JOB_NAME", "DATA_BUCKET", "INPUT_KEY", "RUN_ID", "AS_OF", "DATABASE", "SQL_PREFIX",
])
glue = GlueContext(SparkContext.getOrCreate())
spark = glue.spark_session
job = Job(glue)
job.init(args["JOB_NAME"], args)
s3 = boto3.client("s3")
bucket, run_id = args["DATA_BUCKET"], args["RUN_ID"]
prefix = f"runs/{run_id}"
root = f"s3://{bucket}/{prefix}"


def read(key):
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read()


def put_json(key, value):
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(value, allow_nan=False).encode(),
                  ContentType="application/json")


spec = json.loads(read(args["INPUT_KEY"]))
previous = spec.get("previous", {})
history = json.loads(gzip.decompress(read(previous["history_key"]))) if previous else []
batches = [(batch, decode_batch(read(batch["key"]), batch)) for batch in spec["batches"]]
received_at = datetime.now(timezone.utc).isoformat()
history, current, rejected, stats = merge_batches(
    history, batches, previous.get("as_of"), received_at)
put_json(f"{prefix}/quarantine.json", rejected)
put_json(f"{prefix}/batch-quality.json", stats)
enforce_quality(stats, current)
if spec.get("failure_drill"):
    raise ValueError("Controlled recovery exercise: failure before publication")
events = pd.DataFrame(current)
report, models, processed = assemble(current, history, stats, previous, spec,
                                      args["AS_OF"], received_at, run_id)
quality = report["quality"]


def write_frame(frame, name, partition=None):
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    distributed = spark.read.json(spark.sparkContext.parallelize([json.dumps(r) for r in records]))
    for column in ("resolution_hours", "age_hours"):
        if column in distributed.columns:
            distributed = distributed.withColumn(column, F.col(column).cast("double"))
    distributed.createOrReplaceTempView("incident_stage" if name == "fact_incident_snapshot" else name)
    if name == "fact_incident_snapshot":
        distributed = spark.sql(read(args["SQL_PREFIX"] + "/fact_incident_snapshot.sql").decode())
        if distributed.count() != len(frame):
            raise ValueError("SQL dimensional joins changed the incident grain")
        distributed.createOrReplaceTempView(name)
    writer = distributed.write.mode("overwrite")
    if partition:
        writer = writer.partitionBy(partition)
    writer.parquet(f"{root}/{name}")


write_frame(events, "events", "event_date")
write_frame(pd.DataFrame(history), "event_revisions")
for name, frame in sorted(models.items(), key=lambda item: not item[0].startswith("dim_")):
    write_frame(frame, name)
queue = spark.sql(read(args["SQL_PREFIX"] + "/aggregate_queue.sql").decode())
actual = sorted((r.group_name, r.priority, r.incidents, r.open_count, r.reopened, r.reassigned)
                for r in queue.collect())
expected = sorted((r["group"], r["priority"], r["incidents"], r["open"], r["reopened"], r["reassigned"])
                  for r in report["groups"])
if actual != expected:
    raise ValueError("SQL queue aggregates differ from the independently calculated report")
report["integrity"]["sql_group_aggregates_reconcile"] = True
queue.write.mode("overwrite").parquet(f"{root}/aggregate_queue")
write_frame(pd.DataFrame(report["daily"]), "fact_daily_queue")
history_key = f"{prefix}/history.json.gz"
s3.put_object(Bucket=bucket, Key=history_key,
              Body=gzip.compress(json.dumps(history, allow_nan=False).encode()),
              ContentType="application/gzip")
put_json(f"{prefix}/report.json", report)
put_json(f"{prefix}/commit.json", {"attempt": run_id, "as_of": args["AS_OF"],
         "history_key": history_key, "processed": processed, "quality": quality,
         "dataset_sha256": spec["dataset_sha256"], "generated_at": received_at})
job.commit()
