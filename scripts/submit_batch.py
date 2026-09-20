import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from serviceops.incremental import decode_batch, validate_registry


def main():
    parser = argparse.ArgumentParser(description="Register an immutable incident delivery")
    parser.add_argument("file")
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--available-as-of", required=True)
    parser.add_argument("--rows", required=True, type=int)
    parser.add_argument("--profile", default="serviceops")
    args = parser.parse_args()
    timestamp = datetime.fromisoformat(args.available_as_of)
    if timestamp.tzinfo:
        raise ValueError("Use source-local availability timestamps")
    config = json.loads(Path("deployment.local.json").read_text())
    s3 = boto3.Session(profile_name=args.profile, region_name="us-east-1").client("s3")
    bucket = config["DataBucket"]
    body = Path(args.file).read_bytes()
    checksum = hashlib.sha256(body).hexdigest()
    manifest = {"batch_id": args.batch_id, "sha256": checksum, "rows": args.rows,
                "available_as_of": timestamp.isoformat(sep=" "), "key": f"landing/{checksum}.jsonl.gz"}
    decode_batch(body, manifest)
    response = s3.get_object(Bucket=bucket, Key="source/registry.json")
    registry = json.loads(response["Body"].read())
    existing = next((b for b in registry["batches"] if b["batch_id"] == args.batch_id), None)
    if existing:
        if existing["sha256"] != checksum or existing["available_as_of"] != manifest["available_as_of"]:
            raise ValueError("Batch identity already exists with different content or availability")
        print("This batch is already registered")
        return
    registry["batches"].append(manifest)
    registry["max_as_of"] = max(registry["max_as_of"], manifest["available_as_of"])
    validate_registry(registry)
    try:
        s3.put_object(Bucket=bucket, Key=manifest["key"], Body=body, IfNoneMatch="*")
    except ClientError as error:
        if error.response["Error"]["Code"] != "PreconditionFailed":
            raise
        if hashlib.sha256(s3.get_object(Bucket=bucket, Key=manifest["key"])["Body"].read()).hexdigest() != checksum:
            raise ValueError("Stored batch checksum mismatch")
    s3.put_object(Bucket=bucket, Key="source/registry.json", Body=json.dumps(registry).encode(),
                  ContentType="application/json", IfMatch=response["ETag"])
    print("Batch registered; the next scheduled run will select it when its availability cutoff is reached")


if __name__ == "__main__":
    main()
