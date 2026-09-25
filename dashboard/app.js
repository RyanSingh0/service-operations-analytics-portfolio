const el = id => document.getElementById(id);
const fmt = n => n == null ? '—' : Number(n).toLocaleString(undefined, {maximumFractionDigits: 1});
let report, expanded = false;
const ns = 'http://www.w3.org/2000/svg';

function textNode(tag, text, cls) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function rows(target, values) {
  el(target).replaceChildren();
  for (const [label, value] of values) {
    const row = textNode('div', '', 'quality-row');
    row.append(textNode('span', label), textNode('strong', value));
    el(target).append(row);
  }
}

function render() {
  el('loading').hidden = true;
  el('content').hidden = false;
  el('asof').textContent = `Historical snapshot · ${report.as_of.slice(0, 10)}`;
  const age = (Date.now() - Date.parse(report.generated_at)) / 86400000;
  const exhausted = report.workflow?.source_exhausted;
  const healthy = Object.values(report.integrity || {}).every(Boolean);
  el('freshness').textContent = !healthy ? 'Integrity check failed' : exhausted ? 'Replay complete' : age > 9 ? 'Update overdue' : 'Pipeline current';
  el('freshness').className = 'badge ' + ((!healthy || (age > 9 && !exhausted)) ? 'warning' : 'healthy');
  el('published').textContent = `Last successful publication: ${new Date(report.generated_at).toLocaleString()}`;
  el('metrics').replaceChildren();
  const cards = [
    ['Incidents observed', fmt(report.summary.incidents), 'Unique incidents at the snapshot cutoff'],
    ['Open backlog', fmt(report.summary.backlog), 'Latest state is neither Resolved nor Closed'],
    ['Median resolution', fmt(report.summary.median_resolution_hours) + ' h', 'Observed closing cycle; resolved incidents only'],
    ['Reopened incidents', fmt(report.summary.reopened_pct) + '%', 'Latest recorded reopen count greater than zero'],
  ];
  for (const [label, value, detail] of cards) {
    const card = textNode('section', '', 'card');
    card.append(textNode('div', label, 'label'), textNode('div', value, 'value'), textNode('div', detail, 'detail'));
    el('metrics').append(card);
  }
  const q = report.quality, batch = q.batch || {};
  const aggregate = label => report.groups.filter(r => r.group === label).reduce((sum,r) => ({incidents:sum.incidents+r.incidents,open:sum.open+r.open,reassigned:sum.reassigned+r.reassigned}), {incidents:0,open:0,reassigned:0});
  const group9 = aggregate('Group 9'), unknown = aggregate('Unknown');
  el('findings').replaceChildren();
  const insights = [
    `Group 9 holds ${fmt(group9.open)} open incidents out of ${fmt(group9.incidents)} at this cutoff. This concentration merits review of the underlying audit history, not a performance ranking. In the separate May 8 audit, all 215 incidents reached a terminal state later in the extract.`,
    `${fmt(unknown.incidents)} incidents have no recorded assignment group, including ${fmt(unknown.reassigned)} with a nonzero reassignment count. Missing current ownership and past reassignment are different fields; one does not invalidate the other.`,
    `The p90 observed resolution time is ${fmt(report.summary.p90_resolution_hours)} hours, compared with a median of ${fmt(report.summary.median_resolution_hours)} hours. The long tail matters; an average alone would hide this variation. Open incidents are excluded from these duration metrics.`,
    `${fmt(q.rejected_rows)} of ${fmt(q.source_rows)} consumed deliveries were quarantined. Missing optional categories remain visible as Unknown instead of silently disappearing from the analysis.`
  ];
  insights.forEach(text => el('findings').append(textNode('li',text)));
  rows('quality', [['Deliveries checked', fmt(q.source_rows)], ['Valid deliveries', fmt(q.accepted_rows)],
    ['Quarantined deliveries', fmt(q.rejected_rows)], ['Accepted rate', ((1 - q.reject_rate) * 100).toFixed(3) + '%']]);
  rows('batch', [['New batches', fmt(report.workflow?.new_batches)], ['Input rows', fmt(batch.input_rows)],
    ['Inserted events', fmt(batch.inserted)], ['Corrections applied', fmt(batch.corrected)],
    ['Duplicate deliveries ignored', fmt(batch.duplicates)], ['Older revisions retained', fmt(batch.stale_revisions)],
    ['Late arrivals applied', fmt(batch.late_arrivals)]]);
  rows('profile', Object.entries(report.profile?.unknown_values || {}).map(([k, v]) => [k.replaceAll('_', ' ') + ' missing', fmt(v)]));
  rows('reasons', Object.entries(batch.rejection_reasons || {}).length
    ? Object.entries(batch.rejection_reasons).map(([k, v]) => [k.replaceAll('_', ' '), fmt(v)])
    : [['Latest batch', 'No rejected records']]);
  el('checks').replaceChildren();
  for (const [name, passed] of Object.entries(report.integrity || {})) {
    const check = textNode('div', '', 'check');
    check.append(textNode('span', passed ? '✓' : '!', passed ? 'check-icon' : 'warning'), textNode('span', name.replaceAll('_', ' ')));
    el('checks').append(check);
  }
  rows('workflow', [['Processed batches', fmt(report.workflow?.processed_batches)],
    ['Current event versions', fmt(q.current_events || report.summary.events)],
    ['Retained event revisions', fmt(q.revision_records)],
    ['Previous snapshot', report.workflow?.previous_as_of || 'Initial load'],
    ['Schedule', report.workflow?.schedule || 'Local run'],
    ['Source status', exhausted ? 'All historical batches processed' : 'Historical batches remaining']]);
  const selected = el('priority').value;
  el('priority').replaceChildren(new Option('All priorities', 'all'));
  for (const priority of [...new Set(report.groups.map(g => g.priority))].sort()) el('priority').add(new Option(priority, priority));
  if ([...el('priority').options].some(o => o.value === selected)) el('priority').value = selected;
  el('definitions').replaceChildren();
  for (const [name, definition] of Object.entries(report.definitions)) {
    const p = textNode('p', '');
    p.append(textNode('strong', name + ': '), document.createTextNode(definition));
    el('definitions').append(p);
  }
  renderChart(); renderGroups(); ChartKit.backlog(report.daily);
}

function filteredGroups() {
  const totals = new Map();
  for (const g of report.groups) {
    if (el('priority').value !== 'all' && g.priority !== el('priority').value) continue;
    if (!g.group.toLowerCase().includes(el('search').value.trim().toLowerCase())) continue;
    const row = totals.get(g.group) || {group: g.group, incidents: 0, open: 0, reopened: 0, reassigned: 0};
    for (const key of ['incidents', 'open', 'reopened', 'reassigned']) row[key] += g[key];
    totals.set(g.group, row);
  }
  return [...totals.values()].sort((a, b) => b.open - a.open || a.group.localeCompare(b.group));
}

function renderGroups() {
  const data = filteredGroups();
  el('groups').replaceChildren();
  for (const group of data.slice(0, expanded ? data.length : 12)) {
    const tr = document.createElement('tr');
    for (const key of ['group', 'incidents', 'open', 'reopened', 'reassigned']) tr.append(textNode('td', key === 'group' ? group[key] : fmt(group[key]), key === 'group' ? '' : 'num'));
    el('groups').append(tr);
  }
  if (!data.length) {
    const tr = document.createElement('tr'), td = textNode('td', 'No groups match these filters.');
    td.colSpan = 5; tr.append(td); el('groups').append(tr);
  }
  el('group-count').textContent = `${data.length} groups · Filters affect this table and its CSV download only.`;
  el('more').textContent = expanded ? 'Show top 12' : 'Show all groups';
  el('more').hidden = data.length <= 12;
}

function renderChart() {
  const svg = el('chart'), metric = el('chart-metric').value;
  const daily = report.daily.slice(-Number(el('range').value));
  svg.replaceChildren();
  const maximum = Math.max(1, ...daily.map(d => d[metric]));
  function shape(type, attributes, text) {
    const node = document.createElementNS(ns, type);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    svg.append(node); return node;
  }
  for (let i = 0; i < 4; i++) {
    const y = 20 + i * 55;
    shape('line', {x1: 55, x2: 625, y1: y, y2: y, stroke: '#e4eae3'});
    shape('text', {x: 46, y: y + 4, 'text-anchor': 'end', class: 'axis'}, fmt(maximum * (1 - i / 3)));
  }
  const points = daily.map((d, i) => [55 + i * 570 / Math.max(1, daily.length - 1), 185 - d[metric] / maximum * 165]);
  if (points.length) {
    const path = points.map((p, i) => (i ? 'L' : 'M') + p.join(',')).join(' ');
    shape('path', {d: path + ` L${points.at(-1)[0]},185 L55,185 Z`, class: 'area'});
    shape('path', {d: path, class: 'line'});
    daily.forEach((d, i) => {
      const circle = shape('circle', {cx: points[i][0], cy: points[i][1], r: 5, fill: '#267566', tabindex: '0'});
      const title = document.createElementNS(ns, 'title');
      title.textContent = `${d.date}: ${fmt(d[metric])}`; circle.append(title);
      circle.addEventListener('focus', () => { el('chart-range').textContent = title.textContent; });
      circle.addEventListener('mouseenter', () => { el('chart-range').textContent = title.textContent; });
    });
    el('chart-range').textContent = `${daily[0].date} to ${daily.at(-1).date} · Hover or focus a point for its value.`;
  }
  el('chart').setAttribute('aria-label', `${el('chart-metric').selectedOptions[0].textContent} over the last ${daily.length} days`);
}

function download(content, type, name) {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function load() {
  el('refresh').disabled = true;
  try {
    const embedded = el('report').textContent.trim();
    if (embedded.startsWith('{')) report = JSON.parse(embedded);
    else {
      const response = await fetch('./report.json', {cache: 'no-store'});
      if (!response.ok) throw new Error(`Report request failed (${response.status})`);
      report = await response.json();
    }
    render(); el('error').hidden = true;
  } catch (error) {
    el('error').textContent = `The latest report could not be loaded. ${report ? 'The last loaded results remain visible.' : 'Please try Refresh shortly.'}`;
    el('error').hidden = false;
  } finally { el('refresh').disabled = false; }
}

for (const id of ['priority', 'search']) el(id).addEventListener(id === 'search' ? 'input' : 'change', renderGroups);
for (const id of ['chart-metric', 'range']) el(id).addEventListener('change', renderChart);
el('more').addEventListener('click', () => { expanded = !expanded; renderGroups(); });
el('refresh').addEventListener('click', load);
el('download').addEventListener('click', () => download(JSON.stringify(report, null, 2), 'application/json', 'service-operations-report.json'));
el('csv').addEventListener('click', () => {
  const keys = ['group', 'incidents', 'open', 'reopened', 'reassigned'];
  const quote = value => '"' + String(value).replaceAll('"', '""') + '"';
  download([keys.join(','), ...filteredGroups().map(g => keys.map(k => quote(g[k])).join(','))].join('\n'), 'text/csv', 'queue-health.csv');
});
for (const tab of document.querySelectorAll('[data-tab]')) tab.addEventListener('click', () => {
  for (const button of document.querySelectorAll('[data-tab]')) button.setAttribute('aria-selected', String(button === tab));
  for (const panel of document.querySelectorAll('[data-panel]')) panel.hidden = panel.dataset.panel !== tab.dataset.tab;
});
load();
if (!el('report').textContent.trim().startsWith('{')) setInterval(load, 300000);
