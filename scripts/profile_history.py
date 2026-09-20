import json
from pathlib import Path

import pandas as pd


def profile(source):
    raw = pd.read_csv(source, dtype=str)
    opened = pd.to_datetime(raw.opened_at, format="%d/%m/%Y %H:%M", errors="coerce")
    updated = pd.to_datetime(raw.sys_updated_at, format="%d/%m/%Y %H:%M", errors="coerce")
    incidents = pd.DataFrame({"incident": raw.number, "opened": opened}).groupby("incident").opened.min()
    arrivals = incidents.dt.normalize().value_counts().sort_index()
    daily = arrivals.reindex(pd.date_range(arrivals.index.min(), arrivals.index.max()), fill_value=0)
    train_end = int(len(daily) * .7)
    tests = []
    for i in range(max(28, train_end), len(daily)):
        actual = float(daily.iloc[i])
        tests.append({"actual": actual, "same_weekday_last_week": float(daily.iloc[i-7]),
                      "zero_control": 0,
                      "previous_four_same_weekdays": float(daily.iloc[[i-7, i-14, i-21, i-28]].mean()),
                      "last_7_days_mean": float(daily.iloc[i-7:i].mean())})
    scores = {}
    for name in ("same_weekday_last_week", "previous_four_same_weekdays", "last_7_days_mean", "zero_control"):
        scores[name] = round(sum(abs(t["actual"] - t[name]) for t in tests) / len(tests), 3)
    return {"event_rows": len(raw), "incidents": len(incidents),
            "update_start": str(updated.min()), "update_end": str(updated.max()),
            "update_calendar_days": (updated.max().normalize() - updated.min().normalize()).days + 1,
            "arrival_start": str(arrivals.index.min().date()), "arrival_end": str(arrivals.index.max().date()),
            "arrival_calendar_days": len(daily), "arrival_days_with_incidents": len(arrivals),
            "arrival_weeks": round(len(daily)/7, 1), "zero_arrival_days_inside_range": int(daily.eq(0).sum()),
            "arrivals_by_month": {str(k): int(v) for k, v in incidents.dt.to_period("M").value_counts().sort_index().items()},
            "date_containing_95_percent_of_arrivals": str(incidents.quantile(.95)),
            "evaluation_mean_daily_arrivals": round(sum(t["actual"] for t in tests)/len(tests), 3),
            "evaluation_start": str(daily.index[max(28, train_end)].date()), "evaluation_days": len(tests),
            "walk_forward_mae_incidents_per_day": scores,
            "evaluation_note": "Last 30% of arrival dates; each baseline uses only earlier actual observations. "
            "No dates beyond the observed arrival window are fabricated as zero demand. "
            "Partial extraction windows and changing coverage limit interpretation."}


if __name__ == "__main__":
    result = profile("data/raw/incident_event_log.csv")
    Path("build").mkdir(exist_ok=True)
    Path("build/history-profile.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
