import csv
import json

import pytest

from serviceops.analytics import build_report
from serviceops.domain import normalize
from serviceops.pipeline import read_source, run_pipeline


def row(incident="INC1", state="New", update="1/3/2016 10:00", **changes):
    result = {
        "number": incident, "incident_state": state, "opened_at": "1/3/2016 09:00",
        "sys_updated_at": update, "sys_mod_count": "0", "priority": "2 - High",
        "assignment_group": "Group 1", "category": "Category 1", "contact_type": "Phone",
        "reopen_count": "0", "reassignment_count": "0",
        "resolved_at": "9/3/2016 09:00", "closed_at": "10/3/2016 09:00",
    }
    result.update(changes)
    return result


def source(tmp_path, rows):
    path = tmp_path / "source.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_future_outcomes_never_enter_event_schema():
    event, error = normalize(row(), "abc", 2)
    assert error is None
    assert "resolved_at" not in event and "closed_at" not in event


def test_identical_source_rows_are_distinct_events():
    first, _ = normalize(row(), "abc", 2)
    second, _ = normalize(row(), "abc", 3)
    assert first["event_id"] != second["event_id"]


@pytest.mark.parametrize("changes,reason", [
    ({"incident_state": "-100"}, "unknown_state"),
    ({"sys_updated_at": "bad date"}, "invalid_sys_updated_at"),
    ({"sys_updated_at": "1/3/2016 08:00"}, "update_before_open"),
    ({"reopen_count": "-1"}, "negative_reopen_count"),
    ({"number": "?"}, "missing_incident_id"),
])
def test_invalid_records_are_quarantined(changes, reason):
    event, error = normalize(row(**changes), "abc", 2)
    assert event is None
    assert reason in error["errors"]


def test_snapshot_ignores_future_events_and_handles_reopening(tmp_path):
    path = source(tmp_path, [row(), row(state="Resolved", update="2/3/2016 10:00"),
        row(state="Active", update="3/3/2016 10:00", reopen_count="1")])
    events, _, _ = read_source(path)
    early, _ = build_report(events, "2016-03-01 23:59:59", {})
    middle, _ = build_report(events, "2016-03-02 23:59:59", {})
    later, _ = build_report(events, "2016-03-03 23:59:59", {})
    assert early["summary"]["backlog"] == 1
    assert middle["summary"]["backlog"] == 0
    assert middle["summary"]["median_resolution_hours"] == 25
    assert later["summary"]["backlog"] == 1
    assert later["summary"]["median_resolution_hours"] is None
    assert [d["backlog"] for d in later["daily"]] == [1, 0, 1]


def test_modified_order_breaks_timestamp_ties(tmp_path):
    path = source(tmp_path, [row(state="Closed", sys_mod_count="3"), row(sys_mod_count="1")])
    events, _, _ = read_source(path)
    report, _ = build_report(events, "2016-03-02", {})
    assert report["summary"]["backlog"] == 0


def test_replay_is_idempotent_and_quality_failure_preserves_latest(tmp_path):
    path = source(tmp_path, [row(), row("INC2")])
    output = tmp_path / "out"
    first = run_pipeline(path, output)
    second = run_pipeline(path, output)
    assert first["run_id"] == second["run_id"]
    assert second["reused"] is True
    previous = (output / "latest.json").read_text()
    source(tmp_path, [row(incident_state="-100")])
    with pytest.raises(ValueError, match="Quality gate"):
        run_pipeline(path, output)
    assert (output / "latest.json").read_text() == previous
    assert not (output / ".run.lock").exists()
    assert len(list((output / "runs").iterdir())) == 1


def test_schema_failure_does_not_publish(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("other\nvalue\n")
    with pytest.raises(ValueError, match="missing columns"):
        run_pipeline(path, tmp_path / "out")
    assert not (tmp_path / "out/latest.json").exists()


def test_dashboard_escapes_untrusted_data(tmp_path):
    from serviceops.pipeline import render_dashboard
    template = tmp_path / "template.html"
    template.write_text('<script type="application/json">__REPORT_JSON__</script>')
    report = {"group": "</script><script>alert(1)</script>"}
    html = render_dashboard(template, report)
    assert html.count("</script>") == 1
    assert "\\u003c" in html
    assert json.loads(html.split(">", 1)[1].split("</script>")[0]) == report
