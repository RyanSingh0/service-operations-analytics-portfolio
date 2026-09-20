SELECT
    i.*
FROM incident_stage AS i
INNER JOIN dim_assignment_group AS g ON i.group_key = g.group_key
INNER JOIN dim_priority AS p ON i.priority_key = p.priority_key
INNER JOIN dim_date AS opened ON i.opened_date_key = opened.date_key
INNER JOIN dim_date AS snapshot ON i.snapshot_date_key = snapshot.date_key
