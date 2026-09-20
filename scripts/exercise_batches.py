import gzip
import hashlib
import json
from pathlib import Path

from replay import run


def main():
    root = Path("build/scenarios")
    root.mkdir(parents=True, exist_ok=True)
    source = hashlib.sha256(b"serviceops-controlled-fixture-v1").hexdigest()

    def record(position, incident="INC900001", state="New", timestamp="1/3/2016 10:00", revision=1, priority="2 - High"):
        return {"source_sha256": source, "source_row": position, "revision": revision,
                "record": {"number": incident, "incident_state": state, "opened_at": "1/3/2016 09:00",
                    "sys_updated_at": timestamp, "sys_mod_count": str(position), "priority": priority,
                    "assignment_group": "Fixture group", "reopen_count": "0", "reassignment_count": "0"}}

    batches = [
        ("first", "2016-03-06 23:59:59", [record(2), record(3, state="Resolved", timestamp="2/3/2016 10:00"), record(4, "INC900002")]),
        ("late-and-corrected", "2016-03-13 23:59:59", [record(2), record(5, state="Active", timestamp="1/3/2016 12:00"), record(4, "INC900002", revision=3, priority="1 - Critical")]),
        ("older-revision", "2016-03-20 23:59:59", [record(4, "INC900002", revision=2, priority="3 - Moderate")]),
        ("bad", "2016-03-27 23:59:59", [record(6, state="not-a-state")]),
    ]
    registry = {"schema_version": 2, "dataset_sha256": source, "max_as_of": batches[-1][1], "batches": []}
    for name, date, records in batches:
        body = gzip.compress("\n".join(json.dumps(r) for r in records).encode(), mtime=0)
        (root / f"{name}.gz").write_bytes(body)
        registry["batches"].append({"batch_id": name, "available_as_of": date, "rows": len(records),
            "key": f"landing/{name}.gz", "sha256": hashlib.sha256(body).hexdigest()})
    registry_path = root / "registry.json"
    registry_path.write_text(json.dumps(registry))
    # Each exercise gets an isolated output; it never changes the published dataset.
    from uuid import uuid4
    output = root / uuid4().hex
    first = run(registry_path, output, batches[0][1])
    repeated = run(registry_path, output, batches[0][1])
    second = run(registry_path, output, batches[1][1])
    third = run(registry_path, output, batches[2][1])
    before = (output / "committed.json").read_bytes()
    try:
        run(registry_path, output, batches[3][1])
    except ValueError as error:
        failure = str(error)
    else:
        raise AssertionError("Invalid batch unexpectedly published")
    assert first["run_id"] == repeated["run_id"]
    assert second["quality"]["batch"]["duplicates"] == 1
    assert second["quality"]["batch"]["late_arrivals"] == 2
    assert second["quality"]["batch"]["corrected"] == 1
    assert third["quality"]["batch"]["stale_revisions"] == 1
    assert third["summary"]["incidents"] == 2 and third["summary"]["backlog"] == 1
    assert (output / "committed.json").read_bytes() == before
    result = {"simulation": True, "same_run_reused": True, "late_and_corrected": second["quality"]["batch"],
              "older_revision": third["quality"]["batch"], "failure": failure, "published_pointer_preserved": True}
    (root / "verification.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
