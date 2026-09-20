import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def main():
    config = json.loads(Path("deployment.local.json").read_text())
    session = boto3.Session(profile_name="serviceops", region_name="us-east-1")
    jobs = session.client("glue").get_job_runs(JobName=config["GlueJob"], MaxResults=100)["JobRuns"]
    records = []
    for job in jobs:
        if job["JobRunState"] not in {"SUCCEEDED", "FAILED", "TIMEOUT", "STOPPED"}:
            continue
        # Fixed G.1X workers are one DPU each; preserve AWS's reported DPU seconds too.
        billed_seconds = max(60, job.get("ExecutionTime", 0)) * job.get("NumberOfWorkers", 2)
        records.append({"status": job["JobRunState"], "execution_seconds": job.get("ExecutionTime"),
            "reported_dpu_seconds": job.get("DPUSeconds"), "workers": job.get("NumberOfWorkers"),
            "estimated_compute_usd": round(billed_seconds / 3600 * .44, 5)})
    successful = [r["estimated_compute_usd"] for r in records if r["status"] == "SUCCEEDED"]
    recent = successful[:3]
    typical = sum(recent) / len(recent)
    s3 = session.client("s3")
    storage = {}
    for bucket in (config["DataBucket"], config["WebBucket"]):
        size, objects = 0, 0
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
            for obj in page.get("Versions", []):
                size += obj["Size"]
                objects += 1
        storage[bucket] = {"all_version_bytes": size, "object_versions": objects}
    billing = "Unavailable"
    today = datetime.now(timezone.utc).date()
    try:
        result = session.client("ce").get_cost_and_usage(
            TimePeriod={"Start": today.replace(day=1).isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY", Metrics=["UnblendedCost"])
        billing = result["ResultsByTime"]
    except ClientError as error:
        billing = {"status": "unavailable", "reason": error.response["Error"]["Code"]}
    output = {"measured_at": datetime.now(timezone.utc).isoformat(), "region": "us-east-1",
        "glue_rate_usd_per_dpu_hour": .44, "completed_runs": records,
        "mean_recent_successful_run_compute_usd": round(typical, 5),
        "weekly_schedule_runs_per_month": 52/12,
        "projected_monthly_scheduled_glue_usd": round(typical * 52/12, 3),
        "projected_monthly_glue_with_8_releases_and_2_exercises_usd": round(typical * (52/12 + 10), 3),
        "observed_storage": storage, "account_cost_explorer": billing,
        "interpretation": "Usage-based estimate, not an invoice. Add storage, requests, logs, alarms, "
        "Athena, orchestration, and CDN traffic. Free tiers or credits are not required for the Glue estimate."}
    Path("build/cost-measurement.json").write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
