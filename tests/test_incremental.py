import gzip
import json
from copy import deepcopy

import pandas as pd
import pytest

from serviceops.analytics import build_report
from serviceops.incremental import decode_batch, digest, enforce_quality, merge_batches, select_batches
from serviceops.modeling import build_models, integrity_checks
from test_pipeline import row

SHA = "a" * 64


def envelope(position=2, revision=1, **changes):
    return {"source_sha256": SHA, "source_row": position, "revision": revision,
            "record": row(**changes)}


def merge(history, records, cutoff=None):
    return merge_batches(history, [({"batch_id": "batch"}, records)], cutoff, "2026-09-18T12:00:00Z")


def test_repeated_delivery_does_not_change_event_or_incident_counts():
    history, events, _, _ = merge([], [envelope()])
    newer, current, _, stats = merge(history, [envelope()])
    assert newer == history and current == events
    assert stats["duplicates"] == 1 and stats["inserted"] == 0


def test_correction_replaces_one_event_and_preserves_revision_history():
    history, _, _, _ = merge([], [envelope()])
    history, events, _, stats = merge(history, [envelope(revision=2, state="Resolved")])
    assert len(history) == 2 and len(events) == 1
    assert events[0]["state"] == "Resolved" and stats["corrected"] == 1


def test_conflicting_same_revision_fails_the_batch():
    history, _, _, _ = merge([], [envelope()])
    with pytest.raises(ValueError, match="Conflicting"):
        merge(history, [envelope(state="Resolved")])


def test_stale_revision_cannot_overwrite_newer_data():
    history, _, _, _ = merge([], [envelope(revision=2, state="Resolved")])
    history, events, _, stats = merge(history, [envelope()])
    assert len(history) == 2 and events[0]["revision"] == 2
    assert stats["stale_revisions"] == 1


def test_late_arrival_revises_history_without_changing_latest_state():
    history, _, _, _ = merge([], [envelope(position=3, state="Resolved", update="3/3/2016 10:00")])
    _, events, _, stats = merge(history, [envelope()], "2016-03-04 23:59:59")
    report, _ = build_report(pd.DataFrame(events), "2016-03-05 23:59:59", {})
    assert stats["late_arrivals"] == 1
    assert report["summary"]["incidents"] == 1 and report["summary"]["backlog"] == 0
    assert report["daily"][0]["backlog"] == 1


def test_invalid_correction_preserves_accepted_version_and_fails_quality_gate():
    history, _, _, _ = merge([], [envelope()])
    _, events, rejected, stats = merge(history, [envelope(revision=2, incident_state="bogus")])
    assert events[0]["state"] == "New" and rejected
    with pytest.raises(ValueError, match="Quality gate"):
        enforce_quality(stats, events)


def test_identity_cannot_be_reassigned_to_another_incident():
    history, _, _, _ = merge([], [envelope()])
    with pytest.raises(ValueError, match="identity"):
        merge(history, [envelope(revision=2, number="INC2")])


def test_registry_rejects_changed_or_removed_committed_batches():
    batch = {"batch_id": "first", "sha256": SHA, "key": "landing/one.gz", "available_as_of": "2016-03-06 23:59:59"}
    registry = {"schema_version": 2, "batches": [batch]}
    assert select_batches(registry, {}, "2016-03-05 23:59:59") == []
    assert select_batches(registry, {"first": SHA}, "2016-03-06 23:59:59") == []
    with pytest.raises(ValueError, match="removed or changed"):
        select_batches(registry, {"first": "b" * 64}, "2016-03-06 23:59:59")


def test_corrupt_batch_and_count_mismatch_fail_before_normalization():
    payload = gzip.compress(json.dumps(envelope()).encode())
    import hashlib
    manifest = {"sha256": hashlib.sha256(payload).hexdigest(), "rows": 1}
    assert decode_batch(payload, manifest) == [envelope()]
    with pytest.raises(ValueError, match="checksum"):
        decode_batch(payload + b"broken", manifest)
    with pytest.raises(ValueError, match="row count"):
        decode_batch(payload, {**manifest, "rows": 2})


def test_reopened_then_closed_uses_latest_cycle_for_duration():
    _, events, _, _ = merge([], [envelope(), envelope(3, state="Resolved", update="2/3/2016 10:00"),
        envelope(4, state="Active", update="3/3/2016 10:00"), envelope(5, state="Closed", update="4/3/2016 10:00")])
    report, _ = build_report(pd.DataFrame(events), "2016-03-05 23:59:59", {})
    assert report["summary"]["median_resolution_hours"] == 73
    assert [d["backlog"] for d in report["daily"]] == [1, 0, 1, 0, 0]
    assert all(d["balance_ok"] for d in report["daily"])


def test_model_keys_and_history_intervals_reconcile():
    _, events, _, _ = merge([], [envelope(), envelope(3, state="Resolved", update="2/3/2016 10:00")])
    frame = pd.DataFrame(events)
    report, incidents = build_report(frame, "2016-03-05 23:59:59", {})
    models = build_models(frame, incidents, report["as_of"])
    assert all(integrity_checks(frame, models, report).values())
    assert len(models["dim_date"]) == 5
    broken = deepcopy(models)
    broken["fact_incident_snapshot"].loc[0, "group_key"] = "missing"
    with pytest.raises(ValueError, match="group_foreign_keys_valid"):
        integrity_checks(frame, broken, report)


def test_hash_is_independent_of_dictionary_key_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
