import pandas as pd

from serviceops.analytics import build_report
from serviceops.modeling import build_models, integrity_checks


def assemble(current, history, stats, previous, spec, as_of, generated_at, run_id):
    events = pd.DataFrame(current)
    prior_quality = previous.get("quality", {})
    total = prior_quality.get("source_rows", 0) + stats["input_rows"]
    bad = prior_quality.get("rejected_rows", 0) + stats["rejected_rows"]
    quality = {"source_rows": total, "accepted_rows": total - bad, "rejected_rows": bad,
               "reject_rate": bad / max(1, total), "current_events": len(current),
               "revision_records": len(history), "batch": stats,
               "source_sha256": spec["dataset_sha256"]}
    report, incidents = build_report(events, as_of, quality)
    models = build_models(events, incidents, as_of)
    report.update(run_id=run_id, generated_at=generated_at,
                  integrity=integrity_checks(events, models, report),
                  mode="Incremental historical replay")
    report["profile"] = {
        "unknown_values": {c: int(events[c].eq("Unknown").sum())
                           for c in ["priority", "assignment_group", "category", "contact_type"]},
        "opened_at_conflicts": int(events.groupby("incident_id").opened_at.nunique().gt(1).sum()),
        "states": {k: int(v) for k, v in events.state.value_counts().items()},
        "min_event_time": events.updated_at.min(), "max_event_time": events.updated_at.max(),
    }
    processed = dict(previous.get("processed", {}))
    processed.update({b["batch_id"]: b["sha256"] for b in spec["batches"]})
    report["workflow"] = {"processed_batches": len(processed), "new_batches": len(spec["batches"]),
                          "previous_as_of": previous.get("as_of"),
                          "schedule": "Weekly on Monday at 15:00 UTC",
                          "source_exhausted": as_of >= spec["max_as_of"]}
    return report, models, processed
