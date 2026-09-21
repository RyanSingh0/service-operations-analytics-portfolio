'use strict';
(async () => {
  const page = location.pathname.includes('/forecast/') ? 'forecast' : location.pathname.includes('/resolution/') ? 'resolution' : 'it';
  const base = page === 'it' ? './' : '../';
  const footer = document.querySelector('footer');
  const summary = document.createElement('p');
  summary.id = 'usage-summary';
  summary.textContent = 'Anonymous page-view reporting is loading.';
  footer?.append(summary);
  try {
    const response = await fetch(base + 'forecast/report.json', {cache:'no-store'});
    if (!response.ok) throw new Error('Unavailable');
    const usage = (await response.json()).usage;
    summary.textContent = usage?.status === 'Available' ? `${usage.total_views.toLocaleString()} recorded page views across the three dashboards · ${usage.start} to ${usage.through} UTC · Updated by the daily data pipeline. Counts include repeats and possible bots, not unique people.` : `Page views: ${usage?.status || 'collection not yet enabled'}. Counts are published after each complete UTC day.`;
  } catch (_) { summary.textContent = 'Page-view totals are temporarily unavailable.'; }
  if (!location.hostname.endsWith('.cloudfront.net') || navigator.doNotTrack === '1' || navigator.globalPrivacyControl === true) return;
  try {
    const response = await fetch(base + 'analytics-config.json', {cache:'no-store'});
    if (!response.ok) return;
    const config = await response.json();
    if (!config.endpoint) return;
    await fetch(config.endpoint, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({page}), credentials:'omit', keepalive:true});
  } catch (_) { /* Analytics failure must not interrupt the dashboard. */ }
})();
