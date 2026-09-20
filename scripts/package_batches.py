import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from serviceops.domain import parse_time, validate_headers


def package(source, destination):
    raw = Path(source).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    validate_headers(reader.fieldnames or [])
    batches = defaultdict(list)
    for position, row in enumerate(reader, 2):
        try:
            timestamp = parse_time(row["sys_updated_at"]) or datetime(2016, 3, 1)
        except ValueError:
            timestamp = datetime(2016, 3, 1)
        sunday = timestamp.date() + timedelta(days=6-timestamp.weekday())
        batches[str(sunday)].append({"source_sha256": checksum, "source_row": position,
                                     "revision": 1, "record": row})
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    registry = {"schema_version": 2, "dataset_sha256": checksum, "batches": []}
    for date, records in sorted(batches.items()):
        payload = gzip.compress("\n".join(json.dumps(r, sort_keys=True) for r in records).encode(), mtime=0)
        digest = hashlib.sha256(payload).hexdigest()
        name = f"uci-{date}-{digest[:12]}.jsonl.gz"
        (destination / name).write_bytes(payload)
        registry["batches"].append({"batch_id": f"uci-{date}", "sha256": digest,
                                   "key": f"landing/{name}", "rows": len(records),
                                   "available_as_of": f"{date} 23:59:59"})
    registry["max_as_of"] = max(b["available_as_of"] for b in registry["batches"])
    (destination / "registry.json").write_text(json.dumps(registry, indent=2))
    return registry


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/raw/incident_event_log.csv")
    parser.add_argument("--output", default="build/batches")
    args = parser.parse_args()
    result = package(args.source, args.output)
    print(json.dumps({"batches": len(result["batches"]), "rows": sum(b["rows"] for b in result["batches"]),
                      "max_as_of": result["max_as_of"]}))
