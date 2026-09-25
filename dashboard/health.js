'use strict';
(async()=>{const box=document.getElementById('run-health');if(!box)return;
  try{const response=await fetch('/forecast/report.json',{cache:'no-store'});if(!response.ok)throw Error();const report=await response.json(),h=report.run_health;
    const title=document.createElement('h2');title.textContent='Daily forecast worker · run health';box.replaceChildren(title);
    if(!h?.runs?.length){const p=document.createElement('p');p.textContent=h?.note||'Run history starts with the monitoring release; no historical runs are invented.';box.append(p);return;}
    const stats=document.createElement('div');stats.className='health-stats';stats.textContent=`${h.runs.length} recorded attempts · ${h.completed} completed · ${h.success_rate_pct??'—'}% succeeded · p50 ${h.p50_seconds??'—'}s · p95 ${h.p95_seconds??'—'}s`;box.append(stats);
    const cells=document.createElement('div');cells.className='run-cells';for(const r of h.runs){const cell=document.createElement('span');cell.className=r.status.toLowerCase();cell.title=`${r.started_at}: ${r.status}${r.duration_seconds!==undefined?' · '+r.duration_seconds+'s':''}`;cell.setAttribute('aria-label',cell.title);cell.tabIndex=0;cells.append(cell);}box.append(cells);
    const p=document.createElement('p');p.textContent=h.note+' Green: succeeded; orange: failed; gray: unknown. As of '+new Date(report.generated_at).toLocaleString()+'.';box.append(p);
  }catch{box.textContent='Run history unavailable; the last successful dashboard remains available.';}
})();
