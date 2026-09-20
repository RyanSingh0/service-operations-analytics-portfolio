import csv
import hashlib
import io
import json
import os
import shutil
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from serviceops.analytics import build_report
from serviceops.domain import EVENT_FIELDS, SOURCE_URL, normalize, validate_headers


def download_source(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "service-operations-analytics/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = next(n for n in archive.namelist() if n.endswith("incident_event_log.csv"))
        destination.write_bytes(archive.read(name))
    return destination


def read_source(path):
    payload = Path(path).read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    validate_headers(reader.fieldnames or [])
    accepted, rejected = [], []
    for line, row in enumerate(reader, 2):
        event, error = normalize(row, checksum, line)
        if error:
            rejected.append(error)
        else:
            accepted.append(event)
    return pd.DataFrame(accepted, columns=EVENT_FIELDS), rejected, checksum


def render_dashboard(template_path, report):
    payload = json.dumps(report, allow_nan=False).replace("<", "\\u003c")
    template = Path(template_path)
    html = template.read_text(encoding="utf-8").replace("__REPORT_JSON__", payload)
    app = template.parent / "app.js"
    if app.exists():
        html = html.replace('<script src="app.js"></script>', '<script>' + app.read_text(encoding="utf-8") + '</script>')
    return html


def run_pipeline(source, output, as_of=None, max_reject_rate=.01, template=None):
    started = time.perf_counter()
    if not 0 <= max_reject_rate <= 1:
        raise ValueError("max_reject_rate must be between 0 and 1")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".run.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another run owns this output folder; inspect .run.lock before recovery")
    os.close(descriptor)
    try:
        events, rejected, checksum = read_source(source)
        total = len(events) + len(rejected)
        quality = {
            "source_rows": total, "accepted_rows": len(events),
            "rejected_rows": len(rejected),
            "reject_rate": len(rejected) / total if total else 1.0,
            "source_sha256": checksum,
        }
        quarantine = output / "quarantine"
        quarantine.mkdir(exist_ok=True)
        (quarantine / f"{checksum}.json").write_text(json.dumps(rejected, indent=2))
        if not total or events.empty or quality["reject_rate"] > max_reject_rate:
            raise ValueError(f"Quality gate failed: {quality}; previous published report is unchanged")
        cutoff = str(pd.Timestamp(as_of)) if as_of else events.updated_at.max()
        run_id = hashlib.sha256(f"{checksum}|{cutoff}|v1".encode()).hexdigest()[:20]
        destination = output / "runs" / run_id
        manifest_path = destination / "manifest.json"
        reused = manifest_path.exists()
        if reused:
            report = json.loads((destination / "report.json").read_text())
        else:
            stage = output / f"stage-{uuid4().hex}"
            stage.mkdir()
            try:
                report, incidents = build_report(events, cutoff, quality)
                report["run_id"] = run_id
                report["generated_at"] = datetime.now(timezone.utc).isoformat()
                events.to_parquet(stage / "events", partition_cols=["event_date"], index=False)
                incidents.to_parquet(stage / "incidents.parquet", index=False)
                (stage / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
                manifest = {"run_id": run_id, "as_of": cutoff, "quality": quality,
                            "elapsed_seconds": round(time.perf_counter() - started, 3)}
                (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
                destination.parent.mkdir(exist_ok=True)
                stage.rename(destination)
            finally:
                if stage.exists():
                    stage.resolve().relative_to(output.resolve())
                    shutil.rmtree(stage)
        if template:
            temporary = output / "index.html.tmp"
            temporary.write_text(render_dashboard(template, report), encoding="utf-8")
            temporary.replace(output / "index.html")
        pointer = output / "latest.json.tmp"
        pointer.write_text(json.dumps({"run_id": run_id, "path": str(destination)}))
        pointer.replace(output / "latest.json")
        return {"run_id": run_id, "reused": reused, "as_of": cutoff,
                "quality": quality, "summary": report["summary"]}
    finally:
        lock.unlink(missing_ok=True)
