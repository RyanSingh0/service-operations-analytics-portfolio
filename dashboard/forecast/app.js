'use strict';
let report;
const $ = id => document.getElementById(id);
const number = value => new Intl.NumberFormat('en-US').format(Math.round(value));
const names = {same_weekday: 'Same weekday', four_week_mean: 'Four-week mean', seasonal_ridge: 'Seasonal regression', weather_calendar_ridge: 'Weather + calendar (challenger)'};
function cell(row, value) { const td = document.createElement('td'); td.textContent = value; row.append(td); }
function svgNode(name, attributes = {}) { const element = document.createElementNS('http://www.w3.org/2000/svg', name); Object.entries(attributes).forEach(([k,v]) => element.setAttribute(k,String(v))); return element; }
function chart(history, forecast) {
  const svg = svgNode('svg', {viewBox:'0 0 720 300', role:'img', 'aria-label':'Recent observed requests, forecast, and uncertainty band'});
  const all = [...history.map(r => r.requests), ...forecast.map(r => r.upper)];
  const max = Math.max(...all, 1)*1.12, count = history.length+forecast.length;
  const x = i => 60+i*640/(count-1), y = value => 260-value/max*230;
  for(let i=0;i<4;i++){ const value=max*i/3, line=svgNode('line',{x1:60,x2:700,y1:y(value),y2:y(value),stroke:'#e2e8e4'});svg.append(line);const label=svgNode('text',{x:50,y:y(value)+4,'text-anchor':'end'});label.textContent=number(value);svg.append(label); }
  const band = [...forecast.map((r,i)=>`${x(history.length+i)},${y(r.upper)}`), ...forecast.map((r,i)=>`${x(history.length+i)},${y(r.lower)}`).reverse()].join(' ');
  svg.append(svgNode('polygon',{points:band,fill:'#efd3b7',opacity:.65}));
  svg.append(svgNode('polyline',{points:history.map((r,i)=>`${x(i)},${y(r.requests)}`).join(' '),fill:'none',stroke:'#2d746a','stroke-width':2.5}));
  svg.append(svgNode('polyline',{points:forecast.map((r,i)=>`${x(history.length+i)},${y(r.forecast)}`).join(' '),fill:'none',stroke:'#bd642c','stroke-width':2.5}));
  svg.append(svgNode('line',{x1:x(history.length-.5),x2:x(history.length-.5),y1:20,y2:260,stroke:'#7b8c88','stroke-dasharray':'4 4'}));
  forecast.forEach((r,i)=>{const point=svgNode('circle',{cx:x(history.length+i),cy:y(r.forecast),r:4,fill:'#bd642c',tabindex:0,'aria-label':`${r.date}: ${r.forecast} requests; range ${r.lower} to ${r.upper}`});const title=svgNode('title');title.textContent=`${r.date}: ${number(r.forecast)} (${number(r.lower)}–${number(r.upper)})`;point.append(title);svg.append(point);});
  [[history[0].date,60,'start'],[forecast.at(-1).date,700,'end']].forEach(([text,pos,anchor])=>{const label=svgNode('text',{x:pos,y:286,'text-anchor':anchor});label.textContent=text;svg.append(label);});
  $('chart').replaceChildren(svg);
}
function selectedRows(){return report.series[$('borough').value].forecast.slice(0,Number($('horizon').value));}
function render(resetCapacity=false){
  const name=$('borough').value, series=report.series[name], rows=selectedRows();
  const total=rows.reduce((s,r)=>s+r.forecast,0), average=total/rows.length;
  if(resetCapacity){$('capacity').max=String(Math.ceil(average*2/100)*100);$('capacity').step=String(Math.max(1,Math.round(average/100)));$('capacity').value=String(Math.round(average));}
  const capacity=Number($('capacity').value), peak=rows.reduce((a,b)=>a.forecast>b.forecast?a:b);
  $('capacity-label').textContent=number(capacity)+' requests';$('total').textContent=number(total);$('period').textContent=rows[0].date+' to '+rows.at(-1).date;
  $('peak').textContent=number(peak.forecast);$('peak-day').textContent=peak.date;
  $('error-rate').textContent=series.test_metrics[series.selected_model].wape_pct+'%';
  $('excess').textContent=number(rows.reduce((s,r)=>s+Math.max(0,r.forecast-capacity),0));
  $('selected').textContent='Selected: '+names[series.selected_model];$('comparison').replaceChildren();
  Object.entries(series.test_metrics).forEach(([key,m])=>{const row=document.createElement('tr');cell(row,names[key]+(key===series.selected_model?' ✓':''));cell(row,number(m.mae));cell(row,m.wape_pct+'%');$('comparison').append(row);});
  $('coverage').textContent='Test band coverage: '+series.test_interval_coverage_pct+'%. MAE is the mean absolute error in requests per day. Bands were calibrated on '+series.interval.calibration_days+' separate dates.';
  $('daily').replaceChildren();rows.forEach(r=>{const row=document.createElement('tr');[r.date,number(r.forecast),number(r.lower),number(r.upper),number(Math.max(0,r.forecast-capacity))].forEach(v=>cell(row,v));$('daily').append(row);});
  monitoring(name, series);
  ChartKit.capacity(rows,capacity);
  if(series.diagnostics){ChartKit.heatmap(series.diagnostics);ChartKit.calibration(series.diagnostics);ChartKit.retrospective(series.diagnostics);$('retro-note').textContent=series.diagnostics.method;}
  else for(const id of ['heatmap','calibration','retro-chart']) $(id).textContent='Diagnostics will appear after the next successful model publication.';
  chart(series.history.slice(-42),rows);$('range-label').textContent=name+' · 42 observed days and '+rows.length+' estimated days.';
}
function download(name,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const anchor=document.createElement('a');anchor.href=url;anchor.download=name;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function load(){
  $('refresh').disabled=true;
  try {const response=await fetch('report.json',{cache:'no-store'});if(!response.ok)throw new Error('Report unavailable');const next=await response.json();if(!next.series||!next.source)throw new Error('Invalid report');report=next;
    const old=$('borough').value;$('borough').replaceChildren();['NYC TOTAL',...Object.keys(report.series).filter(k=>k!=='NYC TOTAL')].forEach(name=>{const option=document.createElement('option');option.value=name;option.textContent=name;$('borough').append(option);});if(old&&report.series[old])$('borough').value=old;
    $('data-through').textContent='Observed data through '+report.source.data_through;$('updated').textContent='Forecast generated '+new Date(report.generated_at).toLocaleString();
    const age=(Date.now()-Date.parse(report.generated_at))/86400000,sourceAge=(Date.now()-Date.parse(report.source.data_through+'T00:00:00Z'))/86400000;
    $('freshness').textContent=age>3||sourceAge>7?'Update delayed':'Daily forecast current';$('freshness').className='badge'+(age>3||sourceAge>7?' warning':'');
    $('evaluation').textContent=`Selection: ${report.evaluation.selection_start}–${report.evaluation.selection_end}. Calibration: ${report.evaluation.calibration_start}–${report.evaluation.calibration_end}. Untouched test: ${report.evaluation.test_start}–${report.evaluation.test_end}. ${report.evaluation.method}`;
    $('quality').textContent=`Validated ${report.quality.days} complete daily observations per borough. Missing borough-days fail publication rather than becoming zeros. Unknown-borough requests retained in city totals: ${number(report.quality.unknown_borough_requests)}.`;
    $('error').hidden=true;$('content').hidden=false;render(!old);
  }catch(error){$('error').textContent='Could not refresh the forecast. '+(report?'The last loaded report remains visible.':'Please try again later.');$('error').hidden=false;$('freshness').textContent='Refresh failed';$('freshness').className='badge warning';}
  finally{$('refresh').disabled=false;}
}
$('borough').addEventListener('change',()=>render(true));$('horizon').addEventListener('change',()=>render());$('capacity').addEventListener('input',()=>render());$('refresh').addEventListener('click',load);
$('csv').addEventListener('click',()=>{const capacity=Number($('capacity').value);const text=['date,borough,forecast,lower,upper,daily_capacity,demand_above_capacity',...selectedRows().map(r=>[r.date,$('borough').value,r.forecast,r.lower,r.upper,capacity,Math.max(0,r.forecast-capacity)].join(','))].join('\n');download('nyc311-forecast.csv',text,'text/csv;charset=utf-8');});
$('json').addEventListener('click',()=>download('nyc311-forecast-report.json',JSON.stringify(report,null,2),'application/json'));
load();setInterval(load,15*60*1000);

function monitoring(name, series) {
  const monitor=report.monitoring, m=monitor?.series?.[name];
  $('monitor-weeks').replaceChildren(); $('monitor-chart').replaceChildren();
  $('monitor-status').textContent=m ? `${m.status} · ${m.scored_predictions} scored forecasts across ${m.distinct_target_dates} target dates` : 'Prospective monitoring starts with the next successful publication.';
  $('monitor-status').style.color=m?.status==='Undercoverage warning'?'#a0411f':'#245d55';
  $('monitor-detail').textContent=m ? `${m.awaiting_mature_actuals} forecasts await mature actuals. Recorded band coverage: ${m.coverage_pct===null?'not yet measurable':m.coverage_pct+'%'}. Recent 28-day demand change: ${m.demand_shift_pct??'unavailable'}%${m.demand_shift_warning?' — investigate the shift':''}.` : '';
  const weekly=m?.weekly||[];
  weekly.forEach(w=>{const tr=document.createElement('tr');[w.week,w.predictions,w.dates,w.wape_pct===null?'—':w.wape_pct+'%',w.coverage_pct+'%'].forEach(v=>cell(tr,v));$('monitor-weeks').append(tr);});
  if(weekly.length){const svg=svgNode('svg',{viewBox:'0 0 720 190',role:'img','aria-label':'Weekly error for previously published forecasts'});const max=Math.max(10,...weekly.map(w=>w.wape_pct||0));weekly.forEach((w,i)=>{const x=55+i*620/Math.max(1,weekly.length-1),y=150-(w.wape_pct||0)/max*115;svg.append(svgNode('line',{x1:x,x2:x,y1:150,y2:y,stroke:'#287466','stroke-width':16}));const t=svgNode('text',{x,y:y-10,'text-anchor':'middle'});t.textContent=w.wape_pct+'%';svg.append(t);const label=svgNode('text',{x,y:177,'text-anchor':'middle'});label.textContent=w.week.slice(5);svg.append(label);});$('monitor-chart').append(svg);}
  else $('monitor-chart').textContent='The chart will populate as published forecasts receive mature actuals. Historical test scores are kept separate.';
  $('monitor-leads').textContent=m ? 'Error by lead time: '+m.by_lead.map(v=>`${v.lead} days: ${v.wape_pct===null?'pending':v.wape_pct+'% WAPE'} (${v.predictions} forecasts)`).join(' · ') : '';
  const revision=monitor?.source_revisions;
  $('revision-info').textContent=revision?.changed_city_dates!==undefined ? `Source corrections since the previous extract: ${revision.changed_city_dates} city dates changed; ${number(revision.absolute_revised_requests)} requests of absolute revision. These describe published records, not a causal demand change.` : revision?.status||'';
  const v=series.selection_metrics;
  $('selection-reason').textContent=`The selected ${names[series.selected_model]} had validation MAE ${v[series.selected_model].mae}; seasonal regression had ${v.seasonal_ridge.mae}. Regression needs a 2% improvement to replace the better baseline. `+(series.selected_model==='four_week_mean'?'The same four observed matching weekdays inform each future weekday, so week two repeats week one exactly. This is expected baseline behavior. ':'Model selection is specific to this borough and evaluation window. ')+(series.test_interval_coverage_pct<80?'Retrospective warning: the nominal 90% band covered fewer than 80% of test dates.':'');
  $('weather-info').textContent=report.weather?.through ? `Weather/calendar challenger evaluated with federal-holiday indicators and lagged temperature/rain at a central NYC grid cell. Weather ends five days before each demand origin; latest weather ${report.weather.through}. Its retrospective results appear above, but it does not replace the selected model. Its published future predictions are retained for prospective comparison.` : 'Weather challenger unavailable for this run. The validated demand models continue without it.';
}
