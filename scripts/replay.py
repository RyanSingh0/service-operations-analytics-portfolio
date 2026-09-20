import argparse
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from package_batches import package
from serviceops.incremental import decode_batch, digest, enforce_quality, merge_batches, select_batches
from serviceops.pipeline import render_dashboard
from serviceops.reporting import assemble

ROOT = Path(__file__).resolve().parents[1]


def run(registry_path, output, as_of, failure_drill=False):
    registry_path, output = Path(registry_path), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".run.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        registry = json.loads(registry_path.read_text())
        commit_file = output / "committed.json"
        previous = json.loads(commit_file.read_text()) if commit_file.exists() else {}
        if previous and as_of < previous["as_of"]:
            raise ValueError("Cutoff cannot move backwards in this output directory")
        selected = select_batches(registry, previous.get("processed", {}), as_of)
        version = digest({p.name: p.read_text(encoding="utf-8")
                          for p in sorted((ROOT / "src/serviceops").glob("*.py"))})
        identity = digest({"selected": [b for b in registry["batches"] if b["available_as_of"] <= as_of],
                           "as_of": as_of, "version": version})[:20]
        if previous.get("run_id") == identity and not failure_drill:
            return json.loads((output / previous["attempt"] / "report.json").read_text())
        attempt = identity + "-" + uuid4().hex[:8]
        destination = output / attempt
        destination.mkdir()
        spec = {"batches": selected, "dataset_sha256": registry["dataset_sha256"],
                "max_as_of": registry["max_as_of"]}
        history = json.loads(gzip.decompress((output / previous["history_key"]).read_bytes())) if previous else []
        batches = [(b, decode_batch((registry_path.parent / Path(b["key"]).name).read_bytes(), b))
                   for b in selected]
        generated = datetime.now(timezone.utc).isoformat()
        history, current, rejected, stats = merge_batches(history, batches, previous.get("as_of"), generated)
        (destination / "quarantine.json").write_text(json.dumps(rejected, indent=2))
        enforce_quality(stats, current)
        if failure_drill:
            raise ValueError("Controlled failure before publication")
        report, models, processed = assemble(current, history, stats, previous, spec,
                                              as_of, generated, identity)
        for name, frame in models.items():
            frame.to_parquet(destination / f"{name}.parquet", index=False)
        pd.DataFrame(current).to_parquet(destination / "events.parquet", index=False)
        pd.DataFrame(history).to_parquet(destination / "event_revisions.parquet", index=False)
        pd.DataFrame(report["daily"]).to_parquet(destination / "fact_daily_queue.parquet", index=False)
        (destination / "report.json").write_text(json.dumps(report, allow_nan=False))
        history_key = f"{attempt}/history.json.gz"
        (output / history_key).write_bytes(gzip.compress(json.dumps(history).encode()))
        commit = {"attempt": attempt, "run_id": identity, "history_key": history_key,
                  "processed": processed, "as_of": as_of, "quality": report["quality"],
                  "dataset_sha256": registry["dataset_sha256"]}
        temporary = output / "committed.tmp"
        temporary.write_text(json.dumps(commit))
        temporary.replace(commit_file)
        (output / "report.json").write_text(json.dumps(report, allow_nan=False))
        (output / "index.html").write_text(render_dashboard(ROOT / "dashboard/index.html", report), encoding="utf-8")
        return report
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the same incremental transformations locally")
    parser.add_argument("--as-of", default="2016-05-01 23:59:59")
    parser.add_argument("--output", default="build/incremental")
    parser.add_argument("--registry", default="build/batches/registry.json")
    parser.add_argument("--failure-drill", action="store_true")
    args = parser.parse_args()
    if not Path(args.registry).exists():
        package(ROOT / "data/raw/incident_event_log.csv", Path(args.registry).parent)
    result = run(args.registry, args.output, args.as_of, args.failure_drill)
    print(json.dumps({"summary": result["summary"], "quality": result["quality"],
                      "integrity": result["integrity"]}, indent=2))
