'use strict';
window.ChartKit = (() => {
  const palette={ink:'#193038',green:'#287466',orange:'#b76532',blue:'#516b9c',line:'#dae2df'};
  const num=v=>Math.round(v).toLocaleString('en-US');
  function node(tag,attrs={},text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
  function frame(id,title,height=300){const s=node('svg',{viewBox:`0 0 720 ${height}`,role:'img','aria-label':title});s.append(node('title',{},title));document.getElementById(id).replaceChildren(s);return s;}
  function label(s,x,y,text,attrs={}){s.append(node('text',{x,y,...attrs},text));}
  function line(s,points,color,dash=''){s.append(node('polyline',{points:points.map(p=>p.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':3,'stroke-dasharray':dash}));}
  function heatmap(d){const s=frame('heatmap','Retrospective WAPE by target weekday and future lead time',350),cells=d.heatmap,max=Math.max(1,...cells.map(c=>c.wape_pct||0));
    ['1–3 days','4–7 days','8–14 days*'].forEach((v,i)=>label(s,210+i*175,25,v,{'text-anchor':'middle'}));
    const week=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    cells.forEach((c,i)=>{const x=130+i%3*175,y=42+c.weekday*38,ratio=(c.wape_pct||0)/max;
      const rect=node('rect',{x,y,width:160,height:32,rx:4,fill:c.wape_pct===null?'#eee':`hsl(166 35% ${94-ratio*61}%)`});rect.append(node('title',{},`${week[c.weekday]}, ${c.lead} days: ${c.wape_pct??'unavailable'}% WAPE; ${c.predictions} forecasts, ${c.dates} dates`));s.append(rect);
      label(s,x+80,y+22,c.wape_pct===null?'No data':c.wape_pct+'%',{'text-anchor':'middle',style:`fill:${ratio>.6?'white':palette.ink}`});
      if(i%3===0)label(s,110,y+22,week[c.weekday],{'text-anchor':'end'});
    });label(s,130,330,'Darker = greater error · *Only leads 8–12 are available in this replay.');
    const worst=cells.filter(c=>c.wape_pct!==null).sort((a,b)=>b.wape_pct-a.wape_pct)[0];
    document.getElementById('heatmap-note').textContent=worst?`Weakest replay cell: ${week[worst.weekday]}, ${worst.lead} days (${worst.wape_pct}% WAPE; ${worst.dates} distinct dates). Overlapping forecasts are not independent.`:'Not enough retrospective observations.';
  }
  function calibration(d){const s=frame('calibration','Nominal interval coverage versus held-out coverage',350),x=v=>80+(v-40)/60*560,y=v=>280-v/100*220;
    for(const v of [0,25,50,75,100]){s.append(node('line',{x1:80,x2:640,y1:y(v),y2:y(v),stroke:palette.line}));label(s,65,y(v)+4,v+'%',{'text-anchor':'end'});}
    for(const v of [40,60,80,100])label(s,x(v),303,v+'%',{'text-anchor':'middle'});
    line(s,[[x(40),y(40)],[x(100),y(100)]],palette.blue,'5 5');
    line(s,d.calibration_curve.map(r=>[x(r.nominal_pct),y(r.actual_pct)]),palette.green);
    d.calibration_curve.forEach(r=>{const c=node('circle',{cx:x(r.nominal_pct),cy:y(r.actual_pct),r:4,fill:palette.green});c.append(node('title',{},`${r.nominal_pct}% nominal; ${r.actual_pct}% actual; ±${num(r.half_width)} requests`));s.append(c);});
    label(s,80,20,'Actual coverage ↑');label(s,360,333,'Nominal coverage →',{'text-anchor':'middle'});label(s,95,55,'Dashed: ideal calibration');
    const p=d.calibration_curve.find(r=>r.nominal_pct===90);label(s,640,20,`90% target → ${p.actual_pct}% observed`,{'text-anchor':'end'});
    document.getElementById('calibration-note').textContent=`${p.actual_pct>90?'Wider-than-target coverage':p.actual_pct<90?'Coverage below target':'Coverage meets target'} on ${d.calibration_test_dates} held-out dates. Each width uses the earlier 42-day calibration set; no independent-coverage guarantee.`;
  }
  function capacity(rows,capacity){const s=frame('capacity-curve','Daily capacity versus total requests above capacity');const max=Math.max(1,...rows.map(r=>r.upper)),gap=(c,key)=>rows.reduce((a,r)=>a+Math.max(0,r[key]-c),0),top=Math.max(1,gap(0,'upper')),x=c=>70+c/max*590,y=v=>245-v/top*195;
    for(let i=0;i<=3;i++){const v=top*i/3;s.append(node('line',{x1:70,x2:660,y1:y(v),y2:y(v),stroke:palette.line}));label(s,60,y(v)+4,num(v),{'text-anchor':'end'});label(s,x(max*i/3),269,num(max*i/3),{'text-anchor':'middle'});}
    for(const [key,color,dash] of [['upper',palette.blue,'4 4'],['forecast',palette.green,'']])line(s,Array.from({length:61},(_,i)=>[x(i*max/60),y(gap(i*max/60,key))]),color,dash);
    const cx=x(Math.min(capacity,max)),cy=y(gap(capacity,'forecast'));s.append(node('circle',{cx,cy,r:6,fill:palette.orange}));
    label(s,70,20,`${num(gap(capacity,'forecast'))} above capacity over ${rows.length} days at ${num(capacity)}/day`);
    label(s,360,294,'Daily processing capacity →',{'text-anchor':'middle'});
    document.getElementById('capacity-note').textContent=`At ${num(Math.max(...rows.map(r=>r.forecast)))}/day, no forecast day exceeds capacity. Dashed curve uses all daily upper bounds as a stress scenario, not a joint confidence bound. Excludes backlog and carryover.`;
  }
  function retrospective(d){const s=frame('retro-chart','Retrospective weekly error from simulated daily forecast origins',210),rows=d.weekly,max=Math.max(10,...rows.map(r=>r.wape_pct||0)),x=i=>65+i*595/Math.max(1,rows.length-1),y=v=>155-v/max*105;
    line(s,rows.map((r,i)=>[x(i),y(r.wape_pct||0)]),palette.orange,'5 4');rows.forEach((r,i)=>{label(s,x(i),y(r.wape_pct||0)-12,(r.wape_pct??'—')+'%',{'text-anchor':'middle'});label(s,x(i),181,r.week.slice(5),{'text-anchor':'middle'});});label(s,65,22,'Retrospective only · revised extract · target week');
  }
  function backlog(rows){const data=rows.slice(-14),s=frame('backlog-flow','Daily observed arrivals, reopenings and resolutions',330);if(!data.length)return;
    const max=Math.max(1,...data.map(r=>Math.max(r.first_observed+r.reopened_transitions,r.resolved_transitions))),y=v=>165-v/max*100,step=580/data.length;
    s.append(node('line',{x1:70,x2:670,y1:y(0),y2:y(0),stroke:palette.ink}));
    for(const v of [-max,0,max])label(s,60,y(v)+4,num(v),{'text-anchor':'end'});
    data.forEach((r,i)=>{const x=80+i*step,w=step*.65;let total=0;
      for(const [value,color,title] of [[r.first_observed,palette.orange,'First observed'],[r.reopened_transitions,palette.blue,'Reopened']]){const bar=node('rect',{x,y:y(total+value),width:w,height:value/max*100,fill:color});bar.append(node('title',{},`${r.date}: ${title} ${value}`));s.append(bar);total+=value;}
      const bar=node('rect',{x,y:y(0),width:w,height:r.resolved_transitions/max*100,fill:palette.green});bar.append(node('title',{},`${r.date}: Resolved ${r.resolved_transitions}; ending backlog ${r.backlog}`));s.append(bar);
      if(i%2===0)label(s,x+w/2,286,r.date.slice(5),{'text-anchor':'middle'});
    });const first=data[0].starting_backlog,last=data.at(-1).backlog;
    label(s,70,22,`Backlog ${num(first)} → ${num(last)} · net ${last-first>=0?'+':''}${num(last-first)}`);
    label(s,70,45,'Orange: first observed · blue: reopened · green: resolutions below zero');
    const valid=data.every(r=>r.balance_ok&&r.starting_backlog+r.first_observed+r.reopened_transitions-r.resolved_transitions===r.backlog);
    document.getElementById('backlog-note').textContent=`${valid?'Daily balances reconcile.':'Balance check failed; investigate before using.'} ${last>first?'Arrivals and reopenings exceed resolutions':'Resolutions meet or exceed arrivals and reopenings'} over these ${data.length} days. First observed is an audit arrival, not necessarily the creation date.`;
  }
  function survival(candidate,row,predict,report){const s=frame('priority-curves','Critical versus moderate probability of remaining unresolved'),x=t=>65+t/168*590,y=v=>245-v*190;
    for(const v of [0,.5,1]){s.append(node('line',{x1:65,x2:655,y1:y(v),y2:y(v),stroke:palette.line}));label(s,55,y(v)+4,v*100+'%',{'text-anchor':'end'});}
    for(const [priority,color] of [['1 - Critical',palette.orange],['3 - Moderate',palette.green]]){const profile={...row,priority},times=new Set(Array.from({length:169},(_,i)=>i));
      if(candidate!=='piecewise_hazard'){const km=candidate==='global_median'?report.model.global_km:report.model.priority_km[priority]||report.model.global_km;km.forEach(([t])=>{if(t<=168&&t>=0){times.add(Math.max(0,t-1e-7));times.add(t);}});}
      line(s,[...times].sort((a,b)=>a-b).map(t=>[x(t),y(predict(candidate,profile,t))]),color);
    }
    label(s,65,20,'Orange: critical · green: moderate · other inputs held equal');[0,24,72,168].forEach(t=>label(s,x(t),274,t+' h',{'text-anchor':'middle'}));
    const c=report.test_by_priority['1 - Critical']?.[candidate]?.n,m=report.test_by_priority['3 - Moderate']?.[candidate]?.n;
    document.getElementById('priority-note').textContent=`Critical test cases: ${c??0}; moderate: ${m??0}. ${candidate==='global_median'?'Both curves coincide because the pooled baseline ignores priority.':'These are model estimates for the selected scenario, not causal priority effects; small critical samples limit conclusions.'}`;
  }
  return {heatmap,calibration,capacity,retrospective,backlog,survival};
})();
