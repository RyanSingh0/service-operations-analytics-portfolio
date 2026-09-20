SELECT
    COUNT(*) AS snapshot_rows,
    COUNT(DISTINCT i.incident_id) AS unique_incidents,
    COUNT_IF(i.is_open) AS backlog,
    COUNT_IF(g.group_key IS NULL) AS missing_group,
    COUNT_IF(p.priority_key IS NULL) AS missing_priority,
    COUNT_IF(d.date_key IS NULL) AS missing_opened_date,
    COUNT_IF(i.resolution_hours < 0) AS negative_resolution
FROM fact_incident_snapshot AS i
LEFT JOIN dim_assignment_group AS g ON i.group_key = g.group_key
LEFT JOIN dim_priority AS p ON i.priority_key = p.priority_key
LEFT JOIN dim_date AS d ON i.opened_date_key = d.date_key
