import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime

from serviceops.domain import normalize, validate_headers

MAX_EVENTS = 500_000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def decode_batch(payload, manifest):
    if hashlib.sha256(payload).hexdigest() != manifest["sha256"]:
        raise ValueError("Batch checksum mismatch")
    records = [json.loads(line) for line in gzip.decompress(payload).splitlines() if line]
    if len(records) != manifest["rows"]:
        raise ValueError("Batch row count mismatch")
    if not records or len(records) > MAX_EVENTS:
        raise ValueError("Batch must contain between 1 and 500,000 records")
    return records


def validate_registry(registry):
    if registry.get("schema_version") != 2:
        raise ValueError("Unsupported registry schema")
    seen = set()
    for batch in registry["batches"]:
        if batch["batch_id"] in seen:
            raise ValueError("Duplicate batch identifier in registry")
        seen.add(batch["batch_id"])
        if not re.fullmatch(r"[0-9a-f]{64}", batch["sha256"]):
            raise ValueError("Invalid batch checksum")
        if not batch["key"].startswith("landing/") or ".." in batch["key"]:
            raise ValueError("Batch key must be in landing/")
        if datetime.fromisoformat(batch["available_as_of"]).tzinfo is not None:
            raise ValueError("Batch availability uses source-local time")


def select_batches(registry, processed, as_of):
    validate_registry(registry)
    known = {batch["batch_id"]: batch for batch in registry["batches"]}
    for batch_id, checksum in processed.items():
        if batch_id not in known or known[batch_id]["sha256"] != checksum:
            raise ValueError("A committed batch was removed or changed")
    return sorted((b for b in registry["batches"]
                   if b["batch_id"] not in processed and b["available_as_of"] <= as_of),
                  key=lambda b: (b["available_as_of"], b["batch_id"]))


def merge_batches(previous_history, batches, previous_as_of, received_at):
    history = list(previous_history)
    versions = {(r["event_id"], int(r["revision"])): r for r in history}
    latest = {}
    for record in history:
        old = latest.get(record["event_id"])
        if old is None or record["revision"] > old["revision"]:
            latest[record["event_id"]] = record
    stats = Counter(input_rows=0, valid_rows=0, rejected_rows=0, inserted=0,
                    corrected=0, duplicates=0, stale_revisions=0, late_arrivals=0)
    rejected = []
    reasons = Counter()
    for batch, records in batches:
        for envelope in records:
            stats["input_rows"] += 1
            source = envelope.get("source_sha256", "")
            position, revision = envelope.get("source_row"), envelope.get("revision")
            if (not re.fullmatch(r"[0-9a-f]{64}", source)
                    or type(position) is not int or position < 2
                    or type(revision) is not int or revision < 1):
                raise ValueError("Invalid identity or revision in batch envelope")
            raw = envelope["record"]
            validate_headers(raw)
            event, error = normalize(raw, source, position)
            if error:
                rejected.append({**error, "batch_id": batch["batch_id"],
                                 "revision": revision, "record": raw})
                reasons.update(error["errors"])
                stats["rejected_rows"] += 1
                continue
            stats["valid_rows"] += 1
            checksum = digest(raw)
            key = event["event_id"], revision
            if key in versions:
                if versions[key]["content_hash"] != checksum:
                    raise ValueError("Conflicting payloads for the same event revision")
                stats["duplicates"] += 1
                continue
            old = latest.get(event["event_id"])
            if old and (old["incident_id"] != event["incident_id"]):
                raise ValueError("A correction cannot change an event's incident identity")
            late = bool(previous_as_of and event["updated_at"] <= previous_as_of)
            record = {**event, "revision": revision, "content_hash": checksum,
                      "batch_id": batch["batch_id"], "received_at": received_at,
                      "late_arrival": late}
            history.append(record)
            versions[key] = record
            if old and revision < old["revision"]:
                stats["stale_revisions"] += 1
            else:
                stats["corrected" if old else "inserted"] += 1
                stats["late_arrivals"] += int(late)
                latest[event["event_id"]] = record
    if len(history) > MAX_EVENTS:
        raise ValueError("Revision history exceeds the 500,000-record demonstration limit")
    stats["reject_rate"] = stats["rejected_rows"] / max(1, stats["input_rows"])
    stats["rejection_reasons"] = dict(reasons)
    return history, list(latest.values()), rejected, dict(stats)


def enforce_quality(stats, events):
    if stats["reject_rate"] > .01 or not events:
        raise ValueError("Quality gate failed: over 1% invalid rows or no accepted events")
