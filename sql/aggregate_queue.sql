SELECT
    g.assignment_group AS group_name,
    p.priority,
    COUNT(*) AS incidents,
    SUM(CASE WHEN i.is_open THEN 1 ELSE 0 END) AS open_count,
    SUM(CASE WHEN i.reopen_count > 0 THEN 1 ELSE 0 END) AS reopened,
    SUM(CASE WHEN i.reassignment_count > 0 THEN 1 ELSE 0 END) AS reassigned
FROM fact_incident_snapshot AS i
INNER JOIN dim_assignment_group AS g ON i.group_key = g.group_key
INNER JOIN dim_priority AS p ON i.priority_key = p.priority_key
GROUP BY g.assignment_group, p.priority
