import hashlib

import pandas as pd

from serviceops.domain import TERMINAL


def dimension_key(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def build_models(events, incidents, as_of):
    visible = events.loc[pd.to_datetime(events.updated_at) <= pd.Timestamp(as_of)].copy()
    visible = visible.sort_values(["incident_id", "updated_at", "sys_mod_count", "source_row"])
    for frame in (visible, incidents):
        frame["group_key"] = frame.assignment_group.map(dimension_key)
        frame["priority_key"] = frame.priority.map(dimension_key)
    incidents["snapshot_date_key"] = int(str(as_of)[:10].replace("-", ""))
    incidents["opened_date_key"] = pd.to_datetime(incidents.opened_at).dt.strftime("%Y%m%d").astype(int)
    history = visible[["incident_id", "event_id", "state", "updated_at", "group_key",
                       "priority_key", "sys_mod_count", "source_row"]].copy()
    history = history.rename(columns={"updated_at": "valid_from"})
    history["valid_to"] = history.groupby("incident_id").valid_from.shift(-1)
    history["is_current"] = history.valid_to.isna()
    history["event_order"] = history.groupby("incident_id").cumcount() + 1
    history["previous_state"] = history.groupby("incident_id").state.shift(1)
    history["transition_to_terminal"] = (
        history.state.isin(TERMINAL) & ~history.previous_state.isin(TERMINAL))
    history["reopened_transition"] = (
        ~history.state.isin(TERMINAL) & history.previous_state.isin(TERMINAL))
    groups = visible[["group_key", "assignment_group"]].drop_duplicates()
    priorities = visible[["priority_key", "priority"]].drop_duplicates()
    dates = pd.date_range(pd.to_datetime(visible.opened_at).min().normalize(), pd.Timestamp(as_of).normalize())
    calendar = pd.DataFrame({"date_key": dates.strftime("%Y%m%d").astype(int),
                             "date": dates.strftime("%Y-%m-%d"), "year": dates.year,
                             "month": dates.month, "day": dates.day, "weekday": dates.day_name(),
                             "is_weekend": dates.dayofweek >= 5})
    return {"fact_incident_snapshot": incidents, "fact_incident_history": history,
            "dim_assignment_group": groups, "dim_priority": priorities, "dim_date": calendar}


def integrity_checks(events, models, report):
    fact = models["fact_incident_snapshot"]
    history = models["fact_incident_history"]
    checks = {
        "event_identity_unique": bool(events.event_id.is_unique),
        "incident_grain_unique": bool(fact.incident_id.is_unique),
        "group_dimension_unique": bool(models["dim_assignment_group"].group_key.is_unique),
        "priority_dimension_unique": bool(models["dim_priority"].priority_key.is_unique),
        "date_dimension_unique": bool(models["dim_date"].date_key.is_unique),
        "date_foreign_keys_valid": bool(fact.opened_date_key.isin(models["dim_date"].date_key).all()
                                       and fact.snapshot_date_key.isin(models["dim_date"].date_key).all()),
        "group_foreign_keys_valid": bool(fact.group_key.isin(
            models["dim_assignment_group"].group_key).all()),
        "priority_foreign_keys_valid": bool(fact.priority_key.isin(
            models["dim_priority"].priority_key).all()),
        "one_current_history_row": bool(history.groupby("incident_id").is_current.sum().eq(1).all()),
        "nonnegative_durations": bool(fact.resolution_hours.dropna().ge(0).all()
                                      and fact.age_hours.ge(0).all()),
        "history_intervals_valid": bool((history.valid_to.isna()
                                         | (history.valid_to >= history.valid_from)).all()),
        "no_future_events_in_mart": bool((fact.updated_at <= report["as_of"]).all()),
        "incident_balance": report["summary"]["incidents"] == (
            report["summary"]["backlog"] + report["summary"]["resolved"]),
        "group_totals_reconcile": sum(r["incidents"] for r in report["groups"])
        == report["summary"]["incidents"],
        "last_daily_backlog_reconciles": report["daily"][-1]["backlog"]
        == report["summary"]["backlog"],
        "daily_flow_balance": all(r["balance_ok"] for r in report["daily"]),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError(f"Integrity checks failed: {', '.join(failed)}")
    return checks
