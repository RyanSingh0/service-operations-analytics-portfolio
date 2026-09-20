import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3


def main():
    parser = argparse.ArgumentParser(description="Verify local/cloud metrics, Athena integrity, and public data boundaries")
    parser.add_argument("--profile", default="serviceops")
    parser.add_argument("--local-report", default="build/incremental/report.json")
    args = parser.parse_args()
    config = json.loads(Path("deployment.local.json").read_text())
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    s3, athena = session.client("s3"), session.client("athena")

    def read(key):
        return json.loads(s3.get_object(Bucket=config["DataBucket"], Key=key)["Body"].read())

    commit = read("internal/committed.json")
    cloud = read(f"runs/{commit['attempt']}/report.json")
    local = json.loads(Path(args.local_report).read_text())
    for field in ("as_of", "summary", "daily", "profile", "groups"):
        assert cloud[field] == local[field], f"Local/cloud mismatch in {field}"
    for field in ("source_rows", "accepted_rows", "rejected_rows", "current_events", "revision_records"):
        assert cloud["quality"][field] == local["quality"][field], field
    assert cloud["integrity"] and all(cloud["integrity"].values())

    def query(sql):
        query_id = athena.start_query_execution(QueryString=sql, WorkGroup=config["Workgroup"],
            QueryExecutionContext={"Database": config["Database"]})["QueryExecutionId"]
        for _ in range(60):
            result = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
            if result["Status"]["State"] != "RUNNING" and result["Status"]["State"] != "QUEUED":
                break
            time.sleep(1)
        assert result["Status"]["State"] == "SUCCEEDED", result["Status"]
        rows = athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
        return [[cell.get("VarCharValue") for cell in row["Data"]] for row in rows], result["Statistics"]["DataScannedInBytes"]

    counts, scanned = query(Path("sql/verify_integrity.sql").read_text())
    values = [int(v) for v in counts[1]]
    assert values == [cloud["summary"]["incidents"], cloud["summary"]["incidents"], cloud["summary"]["backlog"], 0, 0, 0, 0], values
    history, more_scanned = query("SELECT count_if(is_current), count(DISTINCT incident_id) FROM fact_incident_history")
    assert [int(v) for v in history[1]] == [cloud["summary"]["incidents"]] * 2
    daily, extra_scanned = query("SELECT count_if(NOT balance_ok) FROM fact_daily_queue")
    assert int(daily[1][0]) == 0
    for bucket in (config["DataBucket"], config["WebBucket"]):
        assert all(s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"].values())
    with urllib.request.urlopen(config["WebsiteUrl"] + "/report.json", timeout=30) as response:
        public = json.load(response)
        headers = dict(response.headers)
    assert public["as_of"] == cloud["as_of"] and public["summary"] == cloud["summary"]
    serialized = json.dumps(public)
    assert "arn:aws:" not in serialized and "source_sha256" not in serialized
    assert "Content-Security-Policy" in headers or "content-security-policy" in headers
    for path in ("/internal/committed.json", "/source/registry.json"):
        try:
            urllib.request.urlopen(config["WebsiteUrl"] + path, timeout=30)
        except urllib.error.HTTPError as error:
            assert error.code in {403, 404}
        else:
            raise AssertionError("A private path is exposed through the website")
    result = {"local_cloud_parity": True, "athena_integrity": True,
              "public_aggregates_match": True, "private_paths_blocked": True,
              "both_buckets_block_public_access": True, "as_of": cloud["as_of"],
              "summary": cloud["summary"], "quality": cloud["quality"],
              "integrity": cloud["integrity"], "athena_bytes_scanned": scanned + more_scanned + extra_scanned,
              "website": config["WebsiteUrl"]}
    Path("build/verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
