SELECT
    assignment_group,
    COUNT(*) AS incidents,
    COUNT_IF(is_open) AS open_incidents,
    COUNT_IF(reopen_count > 0) AS reopened_incidents,
    ROUND(AVG(CASE WHEN NOT is_open THEN resolution_hours END), 2) AS mean_resolution_hours,
    ROUND(APPROX_PERCENTILE(CASE WHEN NOT is_open THEN resolution_hours END, 0.9), 2)
        AS p90_resolution_hours
FROM incidents
GROUP BY assignment_group
ORDER BY open_incidents DESC, incidents DESC;
