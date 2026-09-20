import pandas as pd

from serviceops.domain import TERMINAL


def current_incidents(events, as_of):
    cutoff = pd.Timestamp(as_of)
    visible = events.loc[pd.to_datetime(events.updated_at) <= cutoff].copy()
    if visible.empty:
        raise ValueError("No valid events exist at or before the requested cutoff")
    visible = visible.sort_values(["updated_at", "sys_mod_count", "source_row"])
    visible["observation_order"] = range(len(visible))
    latest = visible.drop_duplicates("incident_id", keep="last").copy()
    first = visible.groupby("incident_id").updated_at.min()
    last_open = visible.loc[~visible.state.isin(TERMINAL)].groupby("incident_id").observation_order.max()
    terminal = visible.loc[visible.state.isin(TERMINAL)
                           & (visible.observation_order > visible.incident_id.map(last_open).fillna(-1))]
    observed_resolution = terminal.groupby("incident_id").updated_at.min()
    latest["first_observed_at"] = latest.incident_id.map(first)
    latest["observed_resolution_at"] = latest.incident_id.map(observed_resolution)
    latest["is_open"] = ~latest.state.isin(TERMINAL)
    # Ignore resolutions from an earlier cycle after an incident has reopened.
    resolved = terminal.loc[terminal.state.eq("Resolved")].groupby("incident_id").updated_at.max()
    latest["observed_resolution_at"] = latest.incident_id.map(resolved).fillna(
        latest.observed_resolution_at
    )
    latest.loc[latest.is_open, "observed_resolution_at"] = None
    latest["resolution_hours"] = (
        pd.to_datetime(latest.observed_resolution_at) - pd.to_datetime(latest.opened_at)
    ).dt.total_seconds() / 3600
    latest["age_hours"] = (
        cutoff - pd.to_datetime(latest.opened_at)
    ).dt.total_seconds() / 3600
    return latest.reset_index(drop=True)


def daily_metrics(events, as_of, days=60):
    cutoff = pd.Timestamp(as_of)
    timestamps = pd.to_datetime(events.updated_at)
    visible = events.loc[timestamps <= cutoff].sort_values(
        ["updated_at", "sys_mod_count", "source_row"]
    )
    by_day = {date: rows for date, rows in visible.groupby("event_date")}
    first_date = pd.to_datetime(visible.event_date.min())
    snapshots = {}
    rows = []
    for day in pd.date_range(first_date, cutoff.normalize(), freq="D"):
        date = day.strftime("%Y-%m-%d")
        opened = 0
        terminal_transitions = 0
        reopened_transitions = 0
        starting_backlog = sum(e["state"] not in TERMINAL for e in snapshots.values())
        for event in by_day.get(date, pd.DataFrame()).to_dict("records"):
            previous = snapshots.get(event["incident_id"])
            opened += previous is None
            if previous and previous["state"] in TERMINAL and event["state"] not in TERMINAL:
                reopened_transitions += 1
            if event["state"] in TERMINAL and (
                previous is None or previous["state"] not in TERMINAL
            ):
                terminal_transitions += 1
            snapshots[event["incident_id"]] = event
        backlog = sum(e["state"] not in TERMINAL for e in snapshots.values())
        rows.append({
            "date": date, "first_observed": opened,
            "resolved_transitions": terminal_transitions,
            "reopened_transitions": reopened_transitions, "starting_backlog": starting_backlog,
            "backlog": backlog,
            "balance_ok": starting_backlog + opened - terminal_transitions + reopened_transitions == backlog,
        })
    return rows[-days:]


def build_report(events, as_of, quality):
    incidents = current_incidents(events, as_of)
    resolved = incidents.loc[~incidents.is_open].resolution_hours.dropna()
    groups = []
    for (group, priority), frame in incidents.groupby(["assignment_group", "priority"]):
        durations = frame.loc[~frame.is_open].resolution_hours.dropna()
        groups.append({
            "group": group, "priority": priority, "incidents": len(frame),
            "open": int(frame.is_open.sum()),
            "reopened": int(frame.reopen_count.gt(0).sum()),
            "reassigned": int(frame.reassignment_count.gt(0).sum()),
            "median_resolution_hours": round(float(durations.median()), 2)
            if len(durations) else None,
        })
    visible = events.loc[pd.to_datetime(events.updated_at) <= pd.Timestamp(as_of)]
    report = {
        "mode": "Historical replay", "as_of": str(as_of),
        "timezone": "Source-local time; original timezone not supplied",
        "source": "UCI Incident Management Process Enriched Event Log (CC BY 4.0)",
        "summary": {
            "events": len(visible), "incidents": len(incidents),
            "backlog": int(incidents.is_open.sum()),
            "resolved": int((~incidents.is_open).sum()),
            "median_resolution_hours": round(float(resolved.median()), 2)
            if len(resolved) else None,
            "p90_resolution_hours": round(float(resolved.quantile(.9)), 2)
            if len(resolved) else None,
            "reopened_pct": round(float(incidents.reopen_count.gt(0).mean() * 100), 2),
        },
        "quality": quality, "groups": groups,
        "daily": daily_metrics(events, as_of),
        "definitions": {
            "backlog": "Latest observed state is neither Resolved nor Closed.",
            "resolution": "Hours from opened_at to the last observed Resolved event in the "
            "latest closing cycle; its first Closed event is the fallback. Open incidents are excluded.",
            "group": "Latest observed assignment, not responsibility for every past event.",
            "reopened": "Incidents with an observed reopen_count greater than zero.",
        },
    }
    return report, incidents
