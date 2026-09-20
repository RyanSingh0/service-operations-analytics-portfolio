from datetime import datetime
from hashlib import sha256
import re

SOURCE_URL = (
    "https://archive.ics.uci.edu/static/public/498/"
    "incident%2Bmanagement%2Bprocess%2Benriched%2Bevent%2Blog.zip"
)
SOURCE_PAGE = "https://archive.ics.uci.edu/dataset/498/incident+management+process+enriched+event+log"
STATES = {
    "New", "Active", "Awaiting User Info", "Awaiting Vendor",
    "Awaiting Problem", "Awaiting Evidence", "Resolved", "Closed",
}
TERMINAL = {"Resolved", "Closed"}
REQUIRED = {
    "number", "incident_state", "opened_at", "sys_updated_at", "sys_mod_count",
    "priority", "assignment_group", "reopen_count", "reassignment_count",
}
EVENT_FIELDS = [
    "event_id", "source_sha256", "source_row", "incident_id", "state", "opened_at",
    "updated_at", "event_date", "sys_mod_count", "priority", "assignment_group",
    "category", "contact_type", "reopen_count", "reassignment_count",
]


def parse_time(value):
    if value is None or str(value).strip() in {"", "?"}:
        return None
    return datetime.strptime(str(value).strip(), "%d/%m/%Y %H:%M")


def clean_text(value):
    return "Unknown" if value is None or str(value).strip() in {"", "?"} else str(value).strip()


def normalize(row, source_sha256, source_row):
    errors = []
    incident_id = clean_text(row.get("number"))
    if incident_id == "Unknown":
        errors.append("missing_incident_id")
    elif not re.fullmatch(r"INC\d+", incident_id):
        errors.append("invalid_incident_id")
    state = clean_text(row.get("incident_state"))
    if state not in STATES:
        errors.append("unknown_state")
    dates = {}
    for key in ("opened_at", "sys_updated_at"):
        try:
            dates[key] = parse_time(row.get(key))
            if dates[key] is None:
                errors.append(f"missing_{key}")
        except ValueError:
            dates[key] = None
            errors.append(f"invalid_{key}")
    if all(dates.values()) and dates["sys_updated_at"] < dates["opened_at"]:
        errors.append("update_before_open")
    counts = {}
    for key in ("sys_mod_count", "reopen_count", "reassignment_count"):
        try:
            if not re.fullmatch(r"\d+", str(row.get(key, "")).strip()):
                if str(row.get(key, "")).strip().startswith("-"):
                    errors.append(f"negative_{key}")
                raise ValueError("Counter must be a nonnegative integer")
            counts[key] = int(row.get(key, ""))
            if counts[key] < 0:
                errors.append(f"negative_{key}")
        except (TypeError, ValueError):
            counts[key] = 0
            errors.append(f"invalid_{key}")
    # Row position preserves legitimate identical events in the published extract.
    event_id = sha256(f"{source_sha256}:{source_row}".encode()).hexdigest()
    if errors:
        return None, {"event_id": event_id, "source_row": source_row, "errors": errors}
    opened = dates["opened_at"].isoformat(sep=" ")
    updated = dates["sys_updated_at"].isoformat(sep=" ")
    event = {
        "event_id": event_id, "source_sha256": source_sha256, "source_row": source_row,
        "incident_id": incident_id, "state": state, "opened_at": opened,
        "updated_at": updated, "event_date": updated[:10], **counts,
        "priority": clean_text(row.get("priority")),
        "assignment_group": clean_text(row.get("assignment_group")),
        "category": clean_text(row.get("category")),
        "contact_type": clean_text(row.get("contact_type")),
    }
    return event, None


def validate_headers(headers):
    missing = REQUIRED - set(headers)
    if missing:
        raise ValueError(f"Source schema is missing columns: {', '.join(sorted(missing))}")
