(() => {
  const $ = (s) => document.querySelector(s);
  const state = { snapshot:null, selected:null, interior:null, run:'auto', live:true, timer:null, view:'map', buildingQuery:'' };
  const map = $('#worldMap');
  const inspector = $('#agentInspector');
  const convList = $('#conversationList');
  const runSelect = $('#runSelect');
  const connection = $('#connectionState');
  const interiorOverlay = $('#interiorOverlay');
  const buildingDirectory = $('#buildingDirectory');

  const esc = (v='') => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const clamp = (v,min=0,max=100) => Math.max(min,Math.min(max,Number(v)||0));
  const timeLabel = raw => raw ? raw.replaceAll('-',' • ').replace('Y','Year ').replace('W','Week ') : 'Waiting for simulation output';
  const short = (t,n=160) => String(t||'').length>n ? String(t).slice(0,n-1)+'…' : String(t||'');

  function personFigure(a, large=false){
    const gender = ['masculine','feminine','neutral'].includes(a.gender_presentation) ? a.gender_presentation : 'neutral';
    const leaderClass = a.name==='Morbeious' ? ' leader-morbeious' : (a.name==='TGOT' ? ' leader-tgot' : '');
    return `<span class="person-figure ${large?'large':''} gender-${gender} c${a.color_index}${leaderClass}" aria-hidden="true">
      <span class="hair hair-back"></span>
      <span class="head"><span class="face-dot eye-left"></span><span class="face-dot eye-right"></span></span>
      <span class="hair hair-front"></span>
      <span class="neck"></span>
      <span class="body-core"><span class="body-mark">${esc(a.initials)}</span></span>
      <span class="arm arm-left"></span><span class="arm arm-right"></span>
      <span class="leg leg-left"></span><span class="leg leg-right"></span>
    </span>`;
  }

  function layoutGrid(n){
    const cols = n <= 4 ? 2 : n <= 9 ? 3 : 4;
    const rows = Math.ceil(n/cols);
    const gap=1.8, pad=1.2;
    return Array.from({length:n},(_,i)=>{
      const c=i%cols,r=Math.floor(i/cols);
      const w=(100-pad*2-gap*(cols-1))/cols,h=(100-pad*2-gap*(rows-1))/rows;
      return {left:pad+c*(w+gap),top:pad+r*(h+gap),w,h};
    });
  }

  function agentPosition(agent, occupants, box){
    const total=occupants.length;
    const local=occupants.findIndex(a=>a.name===agent.name);
    const cols=Math.max(1,Math.ceil(Math.sqrt(total)));
    const rows=Math.ceil(total/cols);
    const x=(local%cols+1)/(cols+1), y=(Math.floor(local/cols)+1)/(rows+1);
    return {left:box.left+box.w*x,top:box.top+box.h*y};
  }

  function renderMap(){
    const s=state.snapshot;if(!s||!s.ok)return;

    // Neighborhood remains readable by showing occupied spaces, HQs and public
    // buildings first. Every location (including empty homes) is still available
    // in the Buildings directory and has the same Interior View.
    const allLocs=s.locations||[];
    let locs=allLocs.filter(l=>Number(l.occupied_count||0)>0 || l.hq || l.kind==='public');
    if(!locs.length)locs=allLocs.slice(0,28);
    locs=locs.slice(0,36);
    const boxes=layoutGrid(Math.max(1,locs.length));
    map.innerHTML='';
    const cardMap=new Map(); // AGENTOPIA_NEIGHBORHOOD_FIT_V17451

    locs.forEach((loc,i)=>{
      const b=boxes[i]; const d=document.createElement('div');
      const hqClass=loc.hq?` location-hq hq-${loc.faction_id||'unknown'}`:'';
      d.className=`location-card location-${loc.kind||'derived'} clickable-location${hqClass}`;
      d.style.cssText=`left:${b.left}%;top:${b.top}%;width:${b.w}%;height:${b.h}%`;
      d.dataset.location=loc.name;
      d.tabIndex=0;
      d.setAttribute('role','button');
      d.setAttribute('aria-label',`Open interior of ${loc.display_name||loc.name}`);
      const type=loc.hq?'FACTION HQ':(loc.kind||'derived').toUpperCase();
      const members=(loc.member_names||[]);
      const occupants=(loc.occupant_names||[]);
      const roster=loc.hq?`<div class="hq-roster"><strong>${Number(loc.member_count||members.length)} faction members</strong><span>${esc(members.slice(0,8).join(' • '))}${members.length>8?` • +${members.length-8}`:''}</span></div>`:'';
      const occupancy=`<div class="location-occupancy">${occupants.length?`${occupants.length} inside`:'empty'} • click to enter</div>`;
      d.innerHTML=`<div class="location-type">${esc(type)}</div><div class="location-name">${esc(loc.display_name||loc.name)}</div>${roster}${occupancy}`;
      const enter=()=>openInterior(loc.name);
      d.addEventListener('click',enter);
      d.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();enter();}});
      map.appendChild(d); cardMap.set(loc.name,d);
    });

    const locMap=new Map(locs.map((l,i)=>[l.name,i]));
    const stage=(s.current_time_parsed?.stage||'').toLowerCase();
    const last=s.messages[s.messages.length-1];
    s.agents.forEach((a)=>{
      if(!locMap.has(a.location))return;
      const li=locMap.get(a.location);
      const occupants=s.agents.filter(x=>x.location===a.location);
      const card=cardMap.get(a.location); if(!card)return;
      const p=agentPosition(a,occupants,{left:6,top:20,w:88,h:58});
      const b=boxes[li];
      const densityScale=Math.max(.28,Math.min(.78,1.15/Math.sqrt(Math.max(1,occupants.length))));
      const geometryScale=Math.max(.28,Math.min(.78,Number(b.h||10)/24,Number(b.w||20)/18));
      const mapScale=Math.min(densityScale,geometryScale);
      const btn=document.createElement('button');
      const talking=!!last && last.sender===a.name;
      btn.className=`agent-human map-agent${s.agents.length>35?' dense':''}${state.selected===a.name?' selected':''}${stage==='activity'?' walking':' idle'}${talking?' talking':''}`;
      btn.dataset.name=a.name; btn.style.left=p.left+'%';btn.style.top=p.top+'%';
      btn.style.setProperty('--map-scale',String(mapScale));
      btn.style.setProperty('--map-hover-scale',String(Math.min(.90,mapScale*1.10)));
      btn.setAttribute('aria-label',`${a.name}, ${a.gender||'gender unspecified'}, ${a.job}, at ${a.location}`);
      const fmark=a.faction&&a.faction.name?`<span class="faction-mark ${a.faction.id==='thai_guardians'?'guardian':'obsidian'}">${a.faction.id==='thai_guardians'?'G':'O'}</span>`:'';
      btn.innerHTML=`${personFigure(a)}<span class="activity-dot"></span>${fmark}<span class="agent-name">${esc(a.name)}</span>`;
      btn.addEventListener('click',e=>{e.stopPropagation();selectAgent(a.name);}); card.appendChild(btn);
    });

    if(last){
      const sender=s.agents.find(a=>a.name===last.sender);
      if(sender&&locMap.has(sender.location)){
        const li=locMap.get(sender.location);
        const occupants=s.agents.filter(x=>x.location===sender.location);
        const card=cardMap.get(sender.location); if(!card)return;
        const p=agentPosition(sender,occupants,{left:6,top:20,w:88,h:58});
        const bubble=document.createElement('div');bubble.className='bubble map-bubble';bubble.style.left=p.left+'%';bubble.style.top=p.top+'%';
        bubble.innerHTML=`<strong>${esc(last.sender)}</strong> → ${esc(last.recipient)}<br>${esc(short(last.content,120))}`;card.appendChild(bubble);
      }
    }
  }

  function locationByName(name){
    return state.snapshot?.locations?.find(l=>l.name===name)||null;
  }

  function openInterior(name){
    if(!name)return;
    state.interior=name;
    renderInterior();
  }

  function closeInterior(){
    state.interior=null;
    interiorOverlay.classList.remove('open');
    interiorOverlay.setAttribute('aria-hidden','true');
  }

  function roomAgentPosition(index,total){
    const presets=[
      [18,60],[38,48],[60,60],[78,46],[27,29],[52,28],[75,27],[14,33],
      [88,63],[42,70],[66,72],[28,76],[84,31],[55,48],[70,42],[18,46]
    ];
    if(index<presets.length)return {left:presets[index][0],top:presets[index][1]};
    const cols=Math.max(1,Math.ceil(Math.sqrt(total)));const row=Math.floor(index/cols),col=index%cols;
    return {left:12+(76*(col+1)/(cols+1)),top:22+(58*(row+1)/(Math.ceil(total/cols)+1))};
  }

  function renderInterior(){
    const s=state.snapshot;if(!s||!s.ok||!state.interior){if(!state.interior)closeInterior();return;}
    const loc=locationByName(state.interior);
    if(!loc){closeInterior();return;}
    const occupants=s.agents.filter(a=>a.location===loc.name);
    const names=new Set(occupants.map(a=>a.name));
    const roomMessages=(s.messages||[]).filter(m=>names.has(m.sender)&&names.has(m.recipient)).slice(-12);
    const latest=roomMessages[roomMessages.length-1];

    $('#interiorType').textContent=loc.hq?'FACTION HQ':String(loc.kind||'building').toUpperCase();
    $('#interiorTitle').textContent=loc.display_name||loc.name;
    $('#interiorSubtitle').textContent=loc.description||((loc.kind==='private')?'Private residence':'Agentopia location');
    $('#interiorCount').textContent=occupants.length;

    const stage=$('#interiorStage');
    stage.className=`interior-stage interior-${loc.hq?'hq':(loc.kind||'public')}${loc.faction_id?` interior-${loc.faction_id}`:''}`;
    let decor='';
    if(loc.hq)decor='<div class="decor command-wall">OPS WALL</div><div class="decor command-table"></div><div class="decor terminal t1"></div><div class="decor terminal t2"></div>';
    else if(loc.kind==='private')decor='<div class="decor sofa"></div><div class="decor home-table"></div><div class="decor lamp"></div><div class="decor rug"></div>';
    else decor='<div class="decor public-table"></div><div class="decor plant p1"></div><div class="decor plant p2"></div><div class="decor wall-display">AGENTOPIA DETROIT</div>';
    stage.innerHTML=decor;

    occupants.forEach((a,i)=>{
      const p=roomAgentPosition(i,occupants.length);
      const btn=document.createElement('button');
      const talking=!!latest&&latest.sender===a.name;
      btn.className=`interior-agent agent-human${talking?' talking':''}`;
      btn.style.left=p.left+'%';btn.style.top=p.top+'%';
      const fmark=a.faction&&a.faction.name?`<span class="faction-mark ${a.faction.id==='thai_guardians'?'guardian':'obsidian'}">${a.faction.id==='thai_guardians'?'G':'O'}</span>`:'';
      btn.innerHTML=`${personFigure(a)}${fmark}<span class="agent-name">${esc(a.name)}</span>`;
      btn.addEventListener('click',()=>selectAgent(a.name));
      stage.appendChild(btn);
    });

    if(latest){
      const sender=occupants.find(a=>a.name===latest.sender);const idx=sender?occupants.findIndex(a=>a.name===sender.name):-1;
      if(idx>=0){const p=roomAgentPosition(idx,occupants.length);const bubble=document.createElement('div');bubble.className='interior-bubble';bubble.style.left=p.left+'%';bubble.style.top=Math.max(8,p.top-25)+'%';bubble.innerHTML=`<strong>${esc(latest.sender)}</strong><br>${esc(short(latest.content,150))}`;stage.appendChild(bubble);}
    }

    $('#interiorRoster').innerHTML=occupants.length?occupants.map(a=>`<button class="roster-person" data-name="${esc(a.name)}"><span>${personFigure(a)}</span><span><strong>${esc(a.name)}</strong><small>${esc(a.activity||'')}</small></span></button>`).join(''):'<div class="empty-state">Nobody is inside right now.</div>';
    $('#interiorRoster').querySelectorAll('.roster-person').forEach(b=>b.addEventListener('click',()=>selectAgent(b.dataset.name)));
    $('#interiorMessages').innerHTML=roomMessages.length?roomMessages.slice().reverse().map(m=>`<div class="room-message"><strong>${esc(m.sender)} → ${esc(m.recipient)}</strong><span>${esc(m.time||'')}</span><p>${esc(m.content)}</p></div>`).join(''):'<div class="empty-state">No recent messages between the citizens currently in this room.</div>';
    const objs=(loc.objects||[]);
    $('#interiorObjects').innerHTML=objs.length?`<strong>Objects here</strong>${objs.map(x=>`<span>${esc(x)}</span>`).join('')}`:'<strong>Objects here</strong><span>Environment details will appear when Agentopia defines them.</span>';

    interiorOverlay.classList.add('open');
    interiorOverlay.setAttribute('aria-hidden','false');
  }

  function renderBuildings(){
    const s=state.snapshot;if(!s||!s.ok||!buildingDirectory)return;
    const q=(state.buildingQuery||'').trim().toLowerCase();
    const rows=(s.locations||[]).filter(l=>{
      if(!q)return true;
      return [l.display_name,l.name,l.owner,l.kind,(l.occupant_names||[]).join(' ')].join(' ').toLowerCase().includes(q);
    });
    buildingDirectory.innerHTML=rows.length?rows.map(loc=>{
      const occ=loc.occupant_names||[];const type=loc.hq?'FACTION HQ':String(loc.kind||'building').toUpperCase();
      return `<button class="building-card ${loc.hq?'building-hq':''}" data-location="${esc(loc.name)}"><span class="building-type">${esc(type)}</span><strong>${esc(loc.display_name||loc.name)}</strong><small>${esc(short(loc.description||'',130))}</small><span class="building-count">${occ.length?`${occ.length} inside • ${esc(occ.slice(0,4).join(', '))}${occ.length>4?'…':''}`:'Empty'} </span></button>`;
    }).join(''):'<div class="empty-state">No buildings match that search.</div>';
    buildingDirectory.querySelectorAll('.building-card').forEach(b=>b.addEventListener('click',()=>openInterior(b.dataset.location)));
  }

  function meter(label,val){const v=clamp(val);return `<div class="meter"><label><span>${esc(label)}</span><b>${Math.round(v)}</b></label><div class="bar"><i style="width:${v}%"></i></div></div>`}
  function selectAgent(name){state.selected=name;renderMap();renderNetwork();renderInspector();}
  function renderInspector(){
    const s=state.snapshot;if(!s||!s.ok)return;
    const a=s.agents.find(x=>x.name===state.selected);
    if(!a){ inspector.className='empty-state'; inspector.textContent='Click any citizen to inspect current state, work, goals, memories, and relationships.'; $('#selectedLocation').textContent='Select an agent'; return; }
    inspector.className=''; $('#selectedLocation').textContent=a.location||'Unknown location';
    const memories=(a.memories||[]).slice(0,4).map(m=>`<div class="memory"><strong>${esc(m.person)}</strong><p>${esc(short(m.summary,220))}</p></div>`).join('') || '<div class="memory"><p>No relationship memory written yet.</p></div>';
    inspector.innerHTML=`
      <div class="identity"><div class="avatar-person">${personFigure(a,true)}</div><div><h2>${esc(a.name)} <span class="gender-chip">${esc(a.gender_symbol||'•')} ${esc(a.gender||'Unspecified')}</span></h2><p>${esc(a.job)}</p><p>${esc(short(a.intro,130))}</p></div></div>
      <div class="now-card"><div class="eyebrow">Right now</div><strong>${esc(a.activity||'Unscheduled')}</strong><div class="muted">${esc(a.activity_time||'No activity timestamp yet')}</div>${a.outcome?`<p>${esc(short(a.outcome,260))}</p>`:''}</div>
      <div class="meters">${meter('Mood',a.state.mood)}${meter('Social',a.state.social)}${meter('Esteem',a.state.esteem)}${meter('Material',a.state.material)}${meter('Vitality',a.state.vitality)}</div>
      <div class="facts"><div class="fact"><span>Faction</span><strong>${esc(a.faction?.name||'Neutral')}${a.faction?.role?' • '+esc(a.faction.role):''}</strong></div><div class="fact"><span>Civic status</span><strong>${a.founding_citizen?`Founding Citizen • ${esc(a.founder_id)}`:esc((a.lineage?.type||'resident').replaceAll('_',' '))}</strong></div><div class="fact"><span>Civic origin</span><strong>${esc([a.origin?.city,a.origin?.region,a.origin?.country].filter(Boolean).join(', ')||'Detroit')}</strong></div><div class="fact"><span>Founder lineage</span><strong>${esc((a.lineage?.founder_names||[]).join(', ')||'—')}</strong></div><div class="fact"><span>Gender</span><strong>${esc(a.gender||'Unspecified')}</strong></div><div class="fact"><span>Money</span><strong>$${Number(a.state.deposit||0).toLocaleString()}</strong></div><div class="fact"><span>Possessions</span><strong>${(a.state.possessions||[]).length}</strong></div><div class="fact"><span>Core motivation</span><strong>${esc(short(a.profile.core_motivation||'—',80))}</strong></div><div class="fact"><span>Values</span><strong>${esc(short(a.profile.values||'—',80))}</strong></div></div>
      <div class="memory-list"><div class="mini-title">Relationship memory</div>${memories}</div>`;
  }

  function renderConversations(){
    const s=state.snapshot;if(!s||!s.ok)return;
    $('#conversationBadge').textContent=`${s.messages.length} messages`;
    const msgs=s.messages.slice(-30).reverse();
    convList.innerHTML=msgs.length?msgs.map(m=>`<div class="message"><div class="message-head"><strong>${esc(m.sender)} → ${esc(m.recipient)}</strong><span>${esc(m.time||'')}</span></div><p>${esc(m.content)}</p></div>`).join(''):'<div class="empty-state">No contact messages written yet.</div>';
  }

  function renderEvents(){
    const s=state.snapshot;if(!s||!s.ok)return;
    const e=s.public_events||[];$('#eventsList').innerHTML=e.length?e.slice().reverse().map(x=>{
      const name=x.event_name||x.name||x.title||'Public event';const desc=x.description||x.event_description||x.content||'';
      return `<div class="event-card"><strong>${esc(name)}</strong><p>${esc(short(desc,220))}</p></div>`
    }).join(''):'<div class="muted">No public events written yet.</div>';
  }

  function networkPositions(agents){
    const cx=500,cy=310,R=Math.min(250,38+agents.length*7);return new Map(agents.map((a,i)=>{const ang=-Math.PI/2+(Math.PI*2*i/Math.max(agents.length,1));return [a.name,{x:cx+Math.cos(ang)*R,y:cy+Math.sin(ang)*R}]}));
  }
  function renderNetwork(){
    const s=state.snapshot;if(!s||!s.ok)return;const svg=$('#networkSvg');const pos=networkPositions(s.agents);let html='';
    for(const e of s.relationships){const a=pos.get(e.a),b=pos.get(e.b);if(!a||!b)continue;html+=`<line class="edge" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke-width="${1+Math.min(7,e.strength*6)}"><title>${esc(e.a)} ↔ ${esc(e.b)}: ${e.interactions} observed messages</title></line>`}
    for(const a of s.agents){const p=pos.get(a.name);const dense=s.agents.length>50;const r=dense?17:25;const label=dense?'':(a.name.length>18?a.name.slice(0,16)+'…':a.name);html+=`<g class="node" data-name="${esc(a.name)}" transform="translate(${p.x},${p.y})"><circle r="${r}" class="c${a.color_index}"></circle><text y="4">${esc(a.gender_symbol||'•')}</text>${label?`<text y="42">${esc(label)}</text>`:''}</g>`}
    svg.innerHTML=html;svg.querySelectorAll('.node').forEach(n=>n.addEventListener('click',()=>selectAgent(n.dataset.name)));
  }

  function renderHumanity(){
    const s=state.snapshot;if(!s||!s.ok)return;const h=s.humanity||{};
    const stats=$('#humanityStats'),ages=$('#humanityAges'),kin=$('#humanityKin'),beliefs=$('#humanityBeliefs'),safe=$('#humanitySafety');
    if(!stats||!ages||!kin||!beliefs||!safe)return;
    $('#humanityUpdated').textContent=h.updated_at?`Updated ${h.updated_at.replace('T',' ').slice(0,19)} UTC`:'Waiting for lifecycle sidecar';
    const ls=h.life_stages||{}, rel=h.kinship_presence||{}, bl=h.beliefs||{};
    stats.innerHTML=`<div class="human-stat"><span>Citizens</span><strong>${Number(h.population||0)}</strong></div><div class="human-stat"><span>Households</span><strong>${Number(h.households||0)}</strong></div><div class="human-stat"><span>Babies</span><strong>${Number(ls.baby||0)}</strong></div><div class="human-stat"><span>Teens</span><strong>${Number(ls.teen||0)}</strong></div><div class="human-stat"><span>Seniors + elders</span><strong>${Number(ls.senior||0)+Number(ls.elder||0)}</strong></div><div class="human-stat"><span>Support reviews</span><strong>${Number(h.interventions||0)}</strong></div>`;
    ages.innerHTML=Object.entries(ls).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="human-row"><span>${esc(k.replaceAll('_',' '))}</span><b>${v}</b></div>`).join('')||'<div class="muted">No demographic state yet.</div>';
    const labels={parents:'people with parents',children:'parents',siblings:'people with siblings',grandparents:'people with grandparents',grandchildren:'grandparents',aunts_uncles:'aunts / uncles',nieces_nephews:'aunts / uncles with nieces or nephews',cousins:'people with cousins',partners:'people with partners'};
    kin.innerHTML=Object.entries(rel).map(([k,v])=>`<div class="human-row"><span>${esc(labels[k]||k)}</span><b>${v}</b></div>`).join('')||'<div class="muted">Kinship graph is initializing.</div>';
    beliefs.innerHTML=Object.entries(bl).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`<div class="human-row"><span>${esc(k)}</span><b>${v}</b></div>`).join('')||'<div class="muted">Belief profiles are initializing.</div>';
    safe.innerHTML=`<div class="human-note"><strong>Religion is not a threat signal.</strong><p>Radicalization is modeled separately from faith, using behavioral factors such as grievance, isolation, propaganda exposure, conspiracy adoption, out-group hostility, and acceptance of violence.</p></div><div class="human-note"><strong>Children stay lightweight.</strong><p>Babies and children are persistent background citizens. Teens enter an activation queue; full LLM citizenship is reserved for socially relevant agents.</p></div>`;
  }

  function renderCognition(){
    const s=state.snapshot;if(!s||!s.ok)return;
    const c=s.cognition||{};
    const stats=$('#cognitionStats'), drift=$('#cognitionDrift'), routing=$('#cognitionRouting'), inst=$('#cognitionInstitutions'), culture=$('#cognitionCulture');
    if(!stats||!drift||!routing||!inst||!culture)return;
    $('#cognitionUpdated').textContent=c.updated_at?`Updated ${c.updated_at.replace('T',' ').slice(0,19)} UTC`:'Waiting for cognition sidecar';
    const dc=c.drift||{}, rc=c.routing||{}, rcounts=rc.counts||{};
    const modelRows=Object.entries(rcounts).map(([k,v])=>`<div class="cog-route"><strong>${esc(k)}</strong><span>${Number(v)||0} citizens</span></div>`).join('')||'<div class="muted">Routing data is initializing.</div>';
    stats.innerHTML=`<div class="cog-stat"><span>Belief models</span><strong>${Number(c.beliefs?.citizens||0)}</strong></div><div class="cog-stat"><span>Active citizens</span><strong>${Number(c.active_citizens||0)}</strong></div><div class="cog-stat"><span>Stable personas</span><strong>${Number(dc.stable||0)}</strong></div><div class="cog-stat"><span>Drift watch/high</span><strong>${Number(dc.watch||0)+Number(dc.high||0)}</strong></div><div class="cog-stat"><span>Inference backend</span><strong>${esc(rc.backend||'initializing')}</strong></div>`;
    const agentRows=Object.entries(c.agents||{}).sort((a,b)=>Number(b[1]?.drift_score||0)-Number(a[1]?.drift_score||0)).slice(0,12);
    drift.innerHTML=agentRows.length?agentRows.map(([name,x])=>`<div class="cog-row"><span><strong>${esc(name)}</strong><small>${esc(x.drift_status||'unknown')}</small></span><b>${Math.round(Number(x.drift_score||0)*100)}%</b></div>`).join(''):'<div class="muted">Persona baselines are initializing.</div>';
    routing.innerHTML=modelRows;
    inst.innerHTML=(c.institutions||[]).slice(0,10).map(x=>`<div class="cog-row"><span><strong>${esc(x.name)}</strong><small>persistent memory</small></span><b>${Number(x.memory_count||0)}</b></div>`).join('')||'<div class="muted">Institutional memory is initializing.</div>';
    culture.innerHTML=(c.culture||[]).slice(0,8).map(x=>`<div class="culture-row"><span>${esc(x.signal)}</span><div><i style="width:${Math.round(Number(x.strength||0)*100)}%"></i></div><b>${Math.round(Number(x.strength||0)*100)}</b></div>`).join('')||'<div class="muted">Cultural signals are initializing.</div>';
  }

  function renderEngine(){
    const s=state.snapshot;if(!s||!s.ok)return;const e=s.engine||{};
    const engine=$('#engineState'), badge=$('#engineBadge');
    const label=(e.state||'unknown').toUpperCase();
    engine.textContent=label;engine.className='state-'+(e.state||'waiting');
    badge.textContent=e.process_running?'Process running':'Process stopped';
    $('#phaseName').textContent=(e.phase||'initializing').replaceAll('_',' ');
    const age=e.last_write_age;$('#lastWrite').textContent=age==null?'No writes yet':age<1?'just now':`${Math.round(age)} sec ago`;
    $('#lastWritePath').textContent=e.last_write_path||'Waiting for generated data';
    let help='';
    if(e.state==='live') help='Agentopia is writing data now. The map is following the active run.';
    else if(e.state==='thinking') help='Agentopia is running but is between file writes — usually waiting on an LLM response.';
    else if(e.state==='waiting') help='The process is alive but has not written data recently. Check the engine log for model/API errors.';
    else if(e.state==='booting') help='Agentopia is loading its local model pools. The persistent world is preserved and the engine will start automatically.';
    else if(e.state==='stopped') help='Agentopia is not running. Relaunch the society from the Desktop launcher.';
    else help='Waiting for Agentopia initialization.';
    $('#engineHelp').textContent=help;
    const lines=e.log_tail||[];$('#engineLog').textContent=lines.length?lines.join('\n'):'No Agentopia log lines yet.';
  }
  function renderHeader(){const s=state.snapshot;if(!s||!s.ok)return;$('#simTime').textContent=timeLabel(s.current_time);$('#agentCount').textContent=s.population_total?`${s.population_total} (${s.agent_count} active)`:s.agent_count;$('#messageCount').textContent=s.messages.length;$('#runName').textContent=s.run;renderEngine();}
  function renderRuns(){const s=state.snapshot;if(!s)return;const selected=state.run||'auto';const rows=[`<option value="auto" ${selected==='auto'?'selected':''}>AUTO • follow active run</option>`];rows.push(...(s.runs||[]).filter(r=>r.generated).map(r=>`<option value="${esc(r.name)}" ${r.name===selected?'selected':''}>${esc(r.name)}${r.active?' • active':''}</option>`));runSelect.innerHTML=rows.join('');}
  function renderDetroitTimeline(){
    const s=state.snapshot;if(!s||!s.ok)return;
    const host=$('#detroitTimeline');if(!host)return;
    const rows=s.detroit_history?.timeline||[];
    if(!rows.length){host.innerHTML='<div class="empty-state">Detroit history is loading…</div>';return;}
    host.innerHTML=rows.map(x=>`<div class="timeline-item ${x.kind==='fiction'?'future':''}"><span class="timeline-year">${esc(x.year)}</span><span><strong>${esc(x.era)}</strong><small>${esc(x.text)}</small></span></div>`).join('');
  }

  function renderSpeed(){
    const s=state.snapshot;if(!s||!s.ok)return;
    const mode=s.speed?.mode||'normal';
    document.querySelectorAll('.speed-btn').forEach(b=>b.classList.toggle('active',b.dataset.speed===mode));
  }

  async function setSpeed(mode){
    try{
      document.querySelectorAll('.speed-btn').forEach(b=>b.classList.toggle('active',b.dataset.speed===mode));
      connection.textContent=`Setting simulation speed • ${mode}`;
      const r=await fetch('/api/speed',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
      const data=await r.json();
      if(!data.ok)throw new Error(data.error||'speed change failed');
      await load();
    }catch(err){connection.textContent=`Speed change failed • ${err.message}`;connection.className='status-dot error';}
  }

  function renderAll(){renderHeader();renderRuns();renderMap();renderBuildings();renderNetwork();renderCognition();renderHumanity();renderInspector();renderConversations();renderEvents();renderDetroitTimeline();renderSpeed();renderInterior();if(window.AgentopiaV161Finance)window.AgentopiaV161Finance(state.snapshot);if(window.AgentopiaV1614Career)window.AgentopiaV1614Career(state.snapshot);if(window.AgentopiaV170Economy)window.AgentopiaV170Economy(state.snapshot);if(window.AgentopiaV171Business)window.AgentopiaV171Business(state.snapshot);if(window.AgentopiaV172Education)window.AgentopiaV172Education(state.snapshot);if(window.AgentopiaV173Health)window.AgentopiaV173Health(state.snapshot);if(window.AgentopiaV174Mobility)window.AgentopiaV174Mobility(state.snapshot);}

  async function load(){
    try{
      const q=`?run=${encodeURIComponent(state.run||'auto')}`;const res=await fetch('/api/snapshot'+q,{cache:'no-store'});const data=await res.json();
      if(!data.ok){state.snapshot=data;const e=data.engine||{};connection.textContent=(e.process_running?'Agentopia initializing':'Agentopia not running')+' • '+(data.error||'Waiting for run');connection.className='status-dot';return;}
      state.snapshot=data;
      if(state.selected&&!data.agents.some(a=>a.name===state.selected))state.selected=null;
      const mode=state.run==='auto'?'AUTO → ':'';const pop=data.population_total||data.agent_count;connection.textContent=`Connected • ${mode}${data.run} • ${data.agent_count} active / ${pop} citizens`;connection.className='status-dot online';renderAll();
    }catch(err){connection.textContent='Connection error: '+err.message;connection.className='status-dot error';}
  }
  function schedule(){clearInterval(state.timer);if(state.live)state.timer=setInterval(load,2000)}

  $('#refreshBtn').addEventListener('click',load);$('#autoRefresh').addEventListener('change',e=>{state.live=e.target.checked;schedule()});runSelect.addEventListener('change',e=>{state.run=e.target.value;state.selected=null;load()});
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{state.view=btn.dataset.view;document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x===btn));$('#mapView').classList.toggle('active',state.view==='map');$('#buildingsView').classList.toggle('active',state.view==='buildings');$('#networkView').classList.toggle('active',state.view==='network')}));
  // AGENTOPIA_HUMANITY_TAB_V140
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const hv=$('#humanityView');if(hv)hv.classList.toggle('active',btn.dataset.view==='humanity');}));
  // AGENTOPIA_COGNITION_TAB_V130
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const cv=$('#cognitionView');if(cv)cv.classList.toggle('active',btn.dataset.view==='cognition');}));
  document.querySelectorAll('.speed-btn').forEach(btn=>btn.addEventListener('click',()=>setSpeed(btn.dataset.speed)));
  $('#closeInterior').addEventListener('click',closeInterior);
  interiorOverlay.addEventListener('click',e=>{if(e.target===interiorOverlay)closeInterior();});
  $('#buildingSearch').addEventListener('input',e=>{state.buildingQuery=e.target.value;renderBuildings();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&state.interior)closeInterior();});
  load();schedule();
})();

/* AGENTOPIA_PHASE_TIMERS_V1442_START */
(() => {
  const VERSION = '1.4.4.2';
  const $id = id => document.getElementById(id);
  const phaseEl = $id('phaseName');
  const engineEl = $id('engineState');
  const lastWriteEl = $id('lastWrite');
  const engineLogEl = $id('engineLog');
  const simTimeEl = $id('simTime');
  const runNameEl = $id('runName');
  if (!phaseEl || !engineEl) return;

  const cssClass = (el, cls, on) => el && el.classList.toggle(cls, !!on);
  const pad = n => String(Math.max(0, Math.floor(n))).padStart(2, '0');
  function fmtSeconds(raw) {
    const s = Math.max(0, Math.floor(Number(raw) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0 ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
  }

  function parseLocalTimestamp(raw) {
    const m = String(raw || '').match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:,(\d{1,3}))?/);
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6]), Number(m[7] || 0)).getTime();
  }

  function normalizeStage(raw) {
    return String(raw || '').trim().toLowerCase().replace(/[ _]+/g, '_');
  }

  function stageLabel(stage, tail='') {
    const s = normalizeStage(stage);
    if (s === 'contact') {
      const m = String(tail).match(/slot=(\d+)/i);
      return m ? `CONTACT S${m[1]}` : 'CONTACT';
    }
    if (s === 'activity') {
      const m = String(tail).match(/day=(\d+)/i);
      return m ? `ACTIVITY D${m[1]}` : 'ACTIVITY';
    }
    return s.replaceAll('_', ' ').toUpperCase();
  }

  function stageEvents() {
    const text = engineLogEl ? engineLogEl.textContent || '' : '';
    const re = /(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:,\d{1,3})?)\s+-\s+world\s+-\s+INFO\s+-\s+==\s+(.+?)\s+STAGE\s+==([^\n]*)/g;
    const out = [];
    let m;
    while ((m = re.exec(text)) !== null) {
      const ms = parseLocalTimestamp(m[1]);
      if (ms == null) continue;
      const stage = normalizeStage(m[2]);
      out.push({ms, stage, tail: m[3] || '', label: stageLabel(stage, m[3] || '')});
    }
    out.sort((a,b) => a.ms - b.ms);
    return out;
  }

  function ensureUI() {
    let p = $id('phaseElapsed');
    if (!p) {
      p = document.createElement('span');
      p.id = 'phaseElapsed';
      p.className = 'phase-clock phase-clock-active';
      p.title = 'Elapsed time in the current simulation phase';
      phaseEl.insertAdjacentElement('afterend', p);
    }
    let e = $id('engineElapsed');
    if (!e) {
      e = document.createElement('span');
      e.id = 'engineElapsed';
      e.className = 'phase-clock';
      e.title = 'When THINKING: time since Agentopia last wrote data while waiting on LLM work';
      engineEl.insertAdjacentElement('afterend', e);
    }
    let strip = $id('phaseTimingStrip');
    if (!strip) {
      strip = document.createElement('section');
      strip.id = 'phaseTimingStrip';
      strip.className = 'phase-timing-strip';
      strip.innerHTML = '<span class="phase-timing-title">⏱ PHASE TIMING</span><div id="phaseTimingHistory" class="phase-timing-history">Collecting stage timing…</div>';
      const hud = document.querySelector('.hud-row');
      if (hud && hud.parentNode) hud.insertAdjacentElement('afterend', strip);
    }
    return {p,e,strip};
  }

  function parseWriteAgeSeconds() {
    const t = String(lastWriteEl ? lastWriteEl.textContent : '').toLowerCase();
    let m = t.match(/(\d+)\s*sec/);
    if (m) return Number(m[1]);
    m = t.match(/(\d+)\s*min(?:ute)?s?/);
    if (m) return Number(m[1]) * 60;
    m = t.match(/(\d+)\s*hour/);
    if (m) return Number(m[1]) * 3600;
    if (/just now|now|<\s*1/.test(t)) return 0;
    return null;
  }

  function fallbackPhaseStart(currentPhase) {
    const world = String(runNameEl ? runNameEl.textContent : 'world').trim();
    const sim = String(simTimeEl ? simTimeEl.textContent : '').trim();
    const key = `agentopia-phase-start|${world}|${sim}|${currentPhase}`;
    let val = Number(localStorage.getItem(key) || 0);
    if (!val) {
      val = Date.now();
      try { localStorage.setItem(key, String(val)); } catch (_) {}
    }
    return val;
  }

  function renderClocks() {
    const ui = ensureUI();
    const now = Date.now();
    let phase = normalizeStage(phaseEl.textContent || '');
    const events = stageEvents();
    const latest = events.length ? events[events.length - 1] : null;
    if (latest) {
      phase = latest.stage;
      phaseEl.textContent = latest.label;
      phaseEl.title = 'Authoritative phase from the newest Agentopia engine log marker';
    }
    const phaseStart = latest ? latest.ms : fallbackPhaseStart(phase);
    const elapsed = Math.max(0, Math.floor((now - phaseStart) / 1000));
    ui.p.textContent = `⏱ ${fmtSeconds(elapsed)}`;

    const engine = String(engineEl.textContent || '').trim().toUpperCase();
    const writeAge = parseWriteAgeSeconds();
    if (engine.includes('THINK')) {
      ui.e.textContent = `⏱ ${fmtSeconds(writeAge == null ? 0 : writeAge)}`;
      ui.e.title = 'LLM wait: elapsed time since the last Agentopia data write';
      cssClass(ui.e, 'phase-clock-thinking', true);
      cssClass(ui.e, 'phase-clock-live', false);
    } else if (engine.includes('LIVE') || engine.includes('RUN')) {
      ui.e.textContent = '● active';
      cssClass(ui.e, 'phase-clock-thinking', false);
      cssClass(ui.e, 'phase-clock-live', true);
    } else {
      ui.e.textContent = writeAge == null ? '' : `⏱ ${fmtSeconds(writeAge)}`;
      cssClass(ui.e, 'phase-clock-thinking', false);
      cssClass(ui.e, 'phase-clock-live', false);
    }

    const hist = $id('phaseTimingHistory');
    if (hist) {
      const rows = [];
      const begin = Math.max(0, events.length - 7);
      for (let i = begin; i < events.length; i++) {
        const ev = events[i];
        const stop = i + 1 < events.length ? events[i + 1].ms : now;
        const secs = Math.max(0, Math.floor((stop - ev.ms) / 1000));
        const active = i === events.length - 1;
        rows.push(`<span class="phase-timing-chip${active ? ' active' : ''}"><b>${ev.label}</b> ${fmtSeconds(secs)}${active ? ' • NOW' : ''}</span>`);
      }
      if (!rows.length) rows.push(`<span class="phase-timing-chip active"><b>${String(phase || 'PHASE').replaceAll('_',' ').toUpperCase()}</b> ${fmtSeconds(elapsed)} • NOW</span>`);
      hist.innerHTML = rows.join('');
    }
  }

  ensureUI();
  renderClocks();
  window.setInterval(renderClocks, 1000);
  console.info(`[Agentopia] Live phase timers v${VERSION} active`);
})();
/* AGENTOPIA_PHASE_TIMERS_V1442_END */

/* AGENTOPIA_SOCIAL_TELEMETRY_V145_JS_START */
(() => {
  const VERSION='1.4.5';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  function ensureStrip(){
    let strip=document.getElementById('socialTelemetryStrip');
    if(strip)return strip;
    strip=document.createElement('section');
    strip.id='socialTelemetryStrip';
    strip.className='social-telemetry-strip';
    strip.innerHTML='<span class="social-telemetry-title">SOCIETY TELEMETRY</span><div id="socialQualityMetrics" class="social-quality-metrics"></div><div id="modelPoolMetrics" class="model-pool-metrics"></div>';
    const timing=document.getElementById('phaseTimingStrip');
    if(timing&&timing.parentNode)timing.insertAdjacentElement('afterend',strip);
    else {const hud=document.querySelector('.hud-row');if(hud)hud.insertAdjacentElement('afterend',strip);}
    return strip;
  }
  function pctClass(v){return Number(v||0)<=10?'good':Number(v||0)<=25?'warn':'bad'}
  window.AgentopiaV145Telemetry=function(s){
    if(!s||!s.ok)return;
    ensureStrip();
    const q=s.conversation_quality||{};
    const qel=document.getElementById('socialQualityMetrics');
    if(qel){
      qel.innerHTML=`<span class="telemetry-chip"><b>${Number(q.current_slot_messages||0)}</b> this slot</span>`+
        `<span class="telemetry-chip"><b>${Number(q.unique_speakers||0)}</b> speakers</span>`+
        `<span class="telemetry-chip"><b>${Number(q.unique_pairs||0)}</b> pairs</span>`+
        `<span class="telemetry-chip ${pctClass(q.repeat_pct)}"><b>${Number(q.repeat_pct||0).toFixed(1)}%</b> repeated text</span>`;
    }
    const pel=document.getElementById('modelPoolMetrics');
    const pools=Array.isArray(s.model_pools)?s.model_pools:[];
    if(pel){
      pel.innerHTML=pools.map(p=>{const total=Number(p.total||p.configured||0),busy=Number(p.busy||0);const pc=total?Math.round(busy*100/total):0;return `<span class="pool-chip ${p.online?'online':'offline'}"><b>${esc(p.name)}</b> ${busy}/${total}<i><em style="width:${pc}%"></em></i></span>`}).join('');
    }
  };
  ensureStrip();
  console.info(`[Agentopia] Social Quality + Telemetry v${VERSION} active`);
})();
/* AGENTOPIA_SOCIAL_TELEMETRY_V145_JS_END */

/* AGENTOPIA_MISSIONS_V160_JS_START */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const money=v=>'$'+Number(v||0).toLocaleString();
  const row=(k,v)=>`<div class="mission-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`;
  const statusBadge=v=>`<span class="mission-badge">${esc(String(v||'unknown').replaceAll('_',' '))}</span>`;
  function renderList(el,items,fn,empty){if(!el)return;el.innerHTML=(items||[]).length?(items||[]).map(fn).join(''):`<div class="muted">${esc(empty)}</div>`;}
  window.AgentopiaV160Missions=function(s){
    if(!s||!s.ok)return;
    const m=s.mission_power||{},o=m.obsidian||{},g=m.guardians||{},gov=m.government||{};
    const up=document.getElementById('missionUpdated');if(up)up.textContent=m.updated_at?`Updated ${m.updated_at.replace('T',' ').slice(0,19)} UTC`:'Waiting for mission engine';
    const stats=document.getElementById('missionStats');if(stats)stats.innerHTML=
      `<div class="mission-stat"><span>Active missions</span><strong>${(m.active_missions||[]).length}</strong></div>`+
      `<div class="mission-stat"><span>Open cases</span><strong>${(m.open_cases||[]).length}</strong></div>`+
      `<div class="mission-stat"><span>Obsidian treasury</span><strong>${money(o.treasury)}</strong></div>`+
      `<div class="mission-stat"><span>Morbeious wealth rank</span><strong>${o.leader_wealth_rank?('#'+o.leader_wealth_rank):'—'}</strong></div>`+
      `<div class="mission-stat"><span>Guardian recovered</span><strong>${money(g.assets_recovered)}</strong></div>`+
      `<div class="mission-stat"><span>Police heat</span><strong>${Number(o.heat||0)}/100</strong></div>`;
    const oe=document.getElementById('missionObsidian');if(oe)oe.innerHTML=row('Permanent mission','Become #1 in wealth + power')+row('Power',`${Number(o.power||0)}/100`)+row('Influence',`${Number(o.influence||0)}/100`)+row('Treasury',money(o.treasury))+row('Effective leader wealth',money(o.leader_effective_wealth))+row('Police heat',`${Number(o.heat||0)}/100`)+row('Operations',Number(o.operations||0));
    const ge=document.getElementById('missionGuardians');if(ge)ge.innerHTML=row('Permanent mission','Protect Agentopia')+row('Power',`${Number(g.power||0)}/100`)+row('Citizen trust',`${Number(g.citizen_trust||0)}/100`)+row('Hardening',`${Number(g.hardening||0)}/100`)+row('Incidents contained',Number(g.incidents_contained||0))+row('Assets recovered',money(g.assets_recovered));
    const pe=document.getElementById('missionGovernment');if(pe)pe.innerHTML=row('Institution',gov.law_enforcement||'Agentopia Public Safety Bureau')+row('Open cases',Number(gov.open_cases||0))+row('Active warrants',Number(gov.warrants_active||0))+row('Arrests',Number(gov.arrests||0))+row('Convictions',Number(gov.convictions||0))+row('Acquittals',Number(gov.acquittals||0))+row('Incarcerated',Number(gov.incarcerated||0))+row('Juvenile diversions',Number(gov.juvenile_diversions||0));
    renderList(document.getElementById('missionActive'),m.active_missions,(x)=>`<article class="mission-item"><div><strong>${esc(x.title||x.mission_id)}</strong>${statusBadge(x.status)}</div><p>${esc(x.objective||'')}</p><small>${esc(x.world_week||'')} · ${esc(x.side||'')}</small></article>`,'No active missions.');
    renderList(document.getElementById('missionCases'),m.open_cases,(x)=>`<article class="mission-item"><div><strong>${esc(x.case_id)}</strong>${statusBadge(x.status)}</div><p>${esc(x.target||'')} · evidence ${Number(x.evidence||0)}/100</p><small>${esc(x.attribution||'unknown attribution')}${(x.named_suspects||[]).length?' · suspects: '+esc((x.named_suspects||[]).join(', ')):''}</small></article>`,'No open cases.');
    renderList(document.getElementById('missionFactions'),m.emergent_factions,(x)=>`<article class="mission-item"><div><strong>${esc(x.name)}</strong>${statusBadge(x.status)}</div><p>Leader: ${esc(x.leader)} · rival of ${esc(x.rival_of||'')}</p><small>${(x.members||[]).map(esc).join(' · ')}</small></article>`,'No splinter factions yet.');
    renderList(document.getElementById('missionEvents'),(m.recent_events||[]).slice().reverse().slice(0,12),(x)=>`<article class="mission-item"><div><strong>${esc(String(x.event||'event').replaceAll('_',' '))}</strong></div><p>${esc(x.world_week||'')} ${x.person?'· '+esc(x.person):''} ${x.case_id?'· '+esc(x.case_id):''}</p><small>${x.gross_loss!=null?'loss '+money(x.gross_loss)+' · recovered '+money(x.recovered||0):esc(x.target||x.disposition||'')}</small></article>`,'Mission events will appear as the world progresses.');
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('missionsView');if(v)v.classList.toggle('active',btn.dataset.view==='missions');try{if(typeof state!=='undefined'&&state.snapshot)window.AgentopiaV160Missions(state.snapshot)}catch(_e){}}));
  console.info('[Agentopia] Mission, Crime & Justice Engine v1.6.0 dashboard active');
})();
/* AGENTOPIA_MISSIONS_V160_JS_END */

/* AGENTOPIA_FINANCE_V161_JS_START */
(() => {
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const money=v=>'$'+Number(v||0).toLocaleString();
  const badge=v=>`<span class="finance-badge">${esc(String(v||'').replaceAll('_',' '))}</span>`;
  const list=(el,items,fn,empty)=>{if(!el)return;el.innerHTML=(items||[]).length?(items||[]).map(fn).join(''):`<div class="muted">${esc(empty)}</div>`;};
  window.AgentopiaV161Finance=function(s){
    if(!s||!s.ok)return; const f=s.financial_network||{};
    const u=document.getElementById('financeUpdated'); if(u)u.textContent=f.updated_at?`Updated ${f.updated_at.replace('T',' ').slice(0,19)} UTC`:'Waiting for finance engine';
    const st=document.getElementById('financeStats'); if(st)st.innerHTML=
      `<div class="finance-stat"><span>Institutions</span><strong>${Object.keys(f.institutions||{}).length}</strong></div>`+
      `<div class="finance-stat"><span>Accounts</span><strong>${Number(f.account_count||0)}</strong></div>`+
      `<div class="finance-stat"><span>Citizen deposits</span><strong>${money(f.total_citizen_deposits)}</strong></div>`+
      `<div class="finance-stat"><span>Institutional assets</span><strong>${money(f.total_institutional_assets)}</strong></div>`+
      `<div class="finance-stat"><span>Obsidian treasury</span><strong>${money(f.obsidian_treasury)}</strong></div>`+
      `<div class="finance-stat"><span>Open alerts</span><strong>${(f.active_alerts||[]).length}</strong></div>`;
    list(document.getElementById('financeInstitutions'),Object.entries(f.institutions||{}),(kv)=>{const [id,x]=kv;return `<article class="finance-item"><div><strong>${esc(x.name||id)}</strong>${badge(x.type)}</div><small>risk ${Number(x.risk||0)}/100</small></article>`;},'No institutions loaded.');
    list(document.getElementById('financeLedger'),(f.recent_transactions||[]).slice().reverse().slice(0,30),(x)=>`<article class="finance-item tx"><div><strong>${money(x.amount)}</strong>${badge(x.type)}</div><p>${esc(x.from_name)} → ${esc(x.to_name)}</p><small>${esc(x.world_week||'')} · ${esc(x.description||'')}</small></article>`,'No posted transfers yet.');
    list(document.getElementById('financeAlerts'),(f.active_alerts||[]).slice().reverse().slice(0,20),(x)=>`<article class="finance-item"><div><strong>${esc(x.institution||'Institution')}</strong>${badge(x.status)}</div><p>${esc(String(x.type||'alert').replaceAll('_',' '))} · risk ${Number(x.risk_score||0)}/100</p><small>${money(x.amount)} · ${esc(x.world_week||'')}</small></article>`,'No active alerts.');
    list(document.getElementById('financeAccounts'),(f.largest_accounts||[]).slice(0,20),(x)=>`<article class="finance-item"><div><strong>${esc(x.name)}</strong>${badge(x.owner_type)}</div><p>${money(x.balance)}${Number(x.frozen||0)>0?' · frozen '+money(x.frozen):''}</p><small>${esc(x.bank_id||'')}</small></article>`,'No accounts.');
    list(document.getElementById('financeMarkets'),Object.entries(f.markets||{}),(kv)=>{const [sym,x]=kv;const p=Number(x.change_pct||0);return `<article class="finance-item"><div><strong>${esc(sym)} · ${esc(x.name||'')}</strong>${badge((p>=0?'+':'')+p.toFixed(2)+'%')}</div><p>${money(Number(x.price||0).toFixed(2))}</p><small>${esc(x.last_event||x.world_week||'')}</small></article>`;},'No market data.');
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('financeView');if(v)v.classList.toggle('active',btn.dataset.view==='finance');try{if(typeof state!=='undefined'&&state.snapshot)window.AgentopiaV161Finance(state.snapshot)}catch(_e){}}));
  console.info('[Agentopia] Financial Network v1.6.1 dashboard active');
})();
/* AGENTOPIA_FINANCE_V161_JS_END */

/* AGENTOPIA_CITY_PULSE_V1613_START */
(() => {
  const VERSION = '1.7.4.5.1-right-sizing';
  const API = 'http://127.0.0.1:8767/api/telemetry';
  const fmtAge = v => {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
    const s = Math.max(0, Math.floor(Number(v)));
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60), rs = s % 60;
    if (m < 60) return `${m}m ${rs}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  };
  const fmtPct = v => (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : `${Number(v).toFixed(1)}%`;
  const fmtMs = v => (v === null || v === undefined || Number.isNaN(Number(v))) ? '—' : (Number(v) >= 1000 ? `${(Number(v)/1000).toFixed(2)}s` : `${Math.round(Number(v))}ms`);
  const esc = s => String(s ?? '');
  const tierOrder = ['350M','1.2B','2.6B','specialist','other'];

  function ensurePanel() {
    let panel = document.getElementById('agentopiaCityPulse');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'agentopiaCityPulse';
    panel.className = 'agentopia-city-pulse';
    panel.innerHTML = `
      <div class="city-pulse-head">
        <div><span class="city-pulse-kicker">RIGHT-SIZING PERFORMANCE</span><strong>How much intelligence can we keep local?</strong></div>
        <span id="cityPulseVersion">v${VERSION}</span>
      </div>

      <div class="rs-summary-grid">
        <article><span>CPU</span><b id="rsCpu">—</b><small id="rsCpuMeta">host utilization</small></article>
        <article><span>MEMORY</span><b id="rsMemory">—</b><small id="rsMemoryMeta">system / unified</small></article>
        <article><span>CORE MODEL SLOTS</span><b id="rsSlots">—</b><small>350M + 1.2B + 2.6B</small></article>
        <article><span>INFERENCE CALLS</span><b id="rsRequests">—</b><small id="rsSuccess">uncached local calls</small></article>
        <article><span>AVG LATENCY</span><b id="rsLatency">—</b><small>observed end-to-end</small></article>
      </div>

      <div class="rs-architecture">
        <div class="rs-arch-title"><span>LIVE ROUTING DISTRIBUTION</span><small id="rsWindowNote">waiting for requests</small></div>
        <div id="rsDistribution" class="rs-distribution"></div>
      </div>

      <div class="city-pulse-grid">
        <div class="city-pulse-card"><span>Engine</span><b id="cpEngine">Connecting…</b><small id="cpHeartbeat">heartbeat —</small></div>
        <div class="city-pulse-card"><span>Phase activity</span><b id="cpProgress">Collecting…</b><div class="cp-progress"><i id="cpProgressBar"></i></div></div>
        <div class="city-pulse-card"><span>World commit</span><b id="cpWorldWrite">—</b><small id="cpWorldSource">—</small></div>
      </div>

      <div class="city-pulse-body">
        <div class="city-pulse-models-wrap"><div class="city-pulse-subhead">MODEL POOLS <span>live slot usage + workload</span></div><div id="cpModels" class="city-pulse-models"></div></div>
        <div class="city-pulse-stream-wrap"><div class="city-pulse-subhead">CITY PULSE <span>latest simulation activity</span></div><div id="cpStream" class="city-pulse-stream"><div class="cp-empty">Waiting for engine activity…</div></div></div>
      </div>`;
    const anchor = document.getElementById('phaseTimingStrip') || document.querySelector('.hud-row') || document.querySelector('main') || document.body.firstElementChild;
    if (anchor && anchor.parentNode) anchor.insertAdjacentElement('afterend', panel);
    else document.body.prepend(panel);
    return panel;
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = esc(value);
  }

  function distMap(perf) {
    const m = new Map();
    for (const row of (perf.distribution || [])) m.set(String(row.tier || 'other'), row);
    return m;
  }

  function renderDistribution(perf) {
    const host = document.getElementById('rsDistribution');
    if (!host) return;
    host.replaceChildren();
    const map = distMap(perf);
    const labels = {'350M':'SOCIAL 350M','1.2B':'CITIZEN 1.2B','2.6B':'STRATEGY 2.6B','specialist':'SPECIALIST','other':'OTHER'};
    for (const tier of tierOrder) {
      const row = map.get(tier) || {requests:0,share_percent:0,avg_latency_ms:null,recent_60s:0};
      if ((tier === 'specialist' || tier === 'other') && !row.requests) continue;
      const wrap = document.createElement('div');
      wrap.className = `rs-dist-row rs-tier-${tier.replace('.','-')}`;
      const top = document.createElement('div');
      top.className = 'rs-dist-top';
      const name = document.createElement('strong');
      name.textContent = labels[tier] || tier;
      const meta = document.createElement('span');
      meta.textContent = `${Number(row.requests||0).toLocaleString()} calls • ${fmtPct(row.share_percent)} • ${fmtMs(row.avg_latency_ms)} avg • ${Number(row.recent_60s||0)}/min`;
      top.append(name, meta);
      const track = document.createElement('div');
      track.className = 'rs-dist-track';
      const fill = document.createElement('i');
      fill.style.width = `${Math.max(0, Math.min(100, Number(row.share_percent||0)))}%`;
      track.appendChild(fill);
      wrap.append(top, track);
      host.appendChild(wrap);
    }
    if (!host.children.length) {
      const empty = document.createElement('div');
      empty.className = 'cp-empty';
      empty.textContent = 'Waiting for the first local inference call…';
      host.appendChild(empty);
    }
  }

  function render(data) {
    ensurePanel();
    const engine = data.engine || {};
    const phase = data.phase || {};
    const progress = data.progress || {};
    const write = data.world_write || {};
    const perf = data.performance || {};

    setText('rsCpu', fmtPct(perf.cpu_percent));
    setText('rsCpuMeta', perf.cpu_count ? `${perf.cpu_count} logical CPUs` : 'host utilization');
    setText('rsMemory', perf.memory_used_gb != null ? `${perf.memory_used_gb} / ${perf.memory_total_gb ?? '—'} GB` : '—');
    setText('rsMemoryMeta', fmtPct(perf.memory_percent));
    setText('rsSlots', perf.core_total_slots != null ? `${perf.core_busy_slots || 0} / ${perf.core_total_slots}` : '—');
    setText('rsRequests', Number(perf.requests || 0).toLocaleString());
    setText('rsSuccess', perf.success_percent == null ? 'uncached local calls' : `${fmtPct(perf.success_percent)} successful`);
    setText('rsLatency', fmtMs(perf.avg_latency_ms));
    setText('rsWindowNote', perf.window_note || 'waiting for requests');
    renderDistribution(perf);

    const engineText = engine.alive ? ((engine.heartbeat_age ?? 999) < 20 ? 'ACTIVE' : 'ALIVE / WAITING') : 'OFFLINE';
    setText('cpEngine', engineText);
    setText('cpHeartbeat', `heartbeat ${fmtAge(engine.heartbeat_age)} • ${phase.name || 'UNKNOWN'} ${fmtAge(phase.elapsed_seconds)}`);
    setText('cpProgress', progress.text || 'Collecting phase progress…');
    const bar = document.getElementById('cpProgressBar');
    if (bar) bar.style.width = `${Math.max(0, Math.min(100, Number(progress.percent || 0)))}%`;
    setText('cpWorldWrite', write.age == null ? 'No commit detected' : `${fmtAge(write.age)} ago`);
    setText('cpWorldSource', write.source || '—');

    const distribution = distMap(perf);
    const modelTier = {social:'350M', citizen:'1.2B', strategy:'2.6B', cyber:'specialist'};
    const models = document.getElementById('cpModels');
    if (models) {
      models.replaceChildren();
      for (const m of (data.models || [])) {
        const row = document.createElement('div');
        const ratio = (m.busy != null && m.slots) ? Number(m.busy)/Number(m.slots) : 0;
        row.className = `cp-model ${m.healthy ? 'healthy' : 'down'} ${ratio >= 1 ? 'cp-saturated' : ratio >= .75 ? 'cp-busy' : ''}`;
        const left = document.createElement('span');
        left.textContent = m.label || m.name || 'model';
        const right = document.createElement('div');
        right.className = 'rs-model-right';
        const busy = document.createElement('b');
        busy.textContent = (m.busy != null && m.slots != null) ? `${m.busy}/${m.slots} busy` : (m.healthy ? 'READY' : 'OFFLINE');
        const t = distribution.get(modelTier[m.name]);
        const work = document.createElement('small');
        work.textContent = t ? `${Number(t.requests||0).toLocaleString()} calls • ${fmtMs(t.avg_latency_ms)} avg` : 'no calls recorded';
        right.append(busy, work);
        row.append(left, right);
        models.appendChild(row);
      }
    }

    const stream = document.getElementById('cpStream');
    if (stream) {
      stream.replaceChildren();
      const pulse = Array.isArray(data.pulse) ? data.pulse.slice().reverse() : [];
      if (!pulse.length) {
        const empty = document.createElement('div');
        empty.className = 'cp-empty';
        empty.textContent = 'Waiting for engine activity…';
        stream.appendChild(empty);
      } else {
        for (const item of pulse) {
          const row = document.createElement('div');
          row.className = 'cp-pulse-row';
          const t = document.createElement('time'); t.textContent = item.time || '';
          const msg = document.createElement('span'); msg.textContent = item.text || '';
          row.append(t, msg); stream.appendChild(row);
        }
      }
    }
  }

  async function poll() {
    ensurePanel();
    try {
      const r = await fetch(`${API}?t=${Date.now()}`, {cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      render(await r.json());
    } catch (err) {
      setText('cpEngine', 'TELEMETRY OFFLINE');
      setText('cpHeartbeat', 'The simulation may still be running; telemetry service is reconnecting.');
      setText('rsCpu', '—');
      setText('rsMemory', '—');
      setText('rsSlots', '—');
    }
  }

  ensurePanel();
  poll();
  window.setInterval(poll, 2000);
  console.info(`[Agentopia] Right-Sizing Performance v${VERSION} active`);
})();
/* AGENTOPIA_CITY_PULSE_V1613_END */

/* AGENTOPIA_CAREER_V1614_JS_START */
(() => {
  const escCareer=(v='')=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const money=n=>'$'+Number(n||0).toLocaleString();
  const list=(el,rows,fn,empty='No data yet.')=>{if(!el)return;el.innerHTML=rows.length?rows.map(fn).join(''):`<div class="career-empty">${escCareer(empty)}</div>`;};
  window.AgentopiaV1614Career=function(s){
    if(!s||!s.ok)return;
    const c=s.career_economy||{};
    const up=document.getElementById('careerUpdated');if(up)up.textContent=c.updated_at?`Updated ${String(c.updated_at).replace('T',' ').slice(0,19)} UTC`:'Waiting...';
    const st=document.getElementById('careerStats');
    if(st)st.innerHTML=[
      ['Professions',c.catalog_count||0],['Employed',c.employed||0],['Unemployed',c.unemployed||0],['Students',c.students||0],
      ['Entrepreneurs',c.entrepreneurs||0],['Median / week',money(c.median_weekly_income||0)],['Businesses',c.business_count||0],['Open jobs',c.vacancy_count||0]
    ].map(x=>`<article class="career-stat"><span>${escCareer(x[0])}</span><strong>${escCareer(x[1])}</strong></article>`).join('');
    list(document.getElementById('careerTopEarners'),Array.isArray(c.top_earners)?c.top_earners:[],x=>`<article class="career-item"><div><strong>${escCareer(x.name)}</strong><span class="career-badge">T${Number(x.tier||0)}</span></div><p>${escCareer(x.title)} - ${escCareer(x.organization||'')}</p><small>${money(x.weekly_income)}/week</small></article>`);
    list(document.getElementById('careerEvents'),Array.isArray(c.recent_events)?[...c.recent_events].reverse().slice(0,25):[],x=>`<article class="career-item"><div><strong>${escCareer(String(x.event||'career event').replaceAll('_',' '))}</strong></div><p>${escCareer(x.citizen||'')} ${x.to_title?'-> '+escCareer(x.to_title):x.title?'- '+escCareer(x.title):''}</p><small>${escCareer(x.organization||x.education||x.business||'')}</small></article>`);
    const sectors=Object.entries(c.sector_distribution||{}).sort((a,b)=>Number(b[1])-Number(a[1]));
    list(document.getElementById('careerSectors'),sectors,x=>`<article class="career-item compact"><div><strong>${escCareer(x[0])}</strong><span>${Number(x[1])}</span></div></article>`);
    list(document.getElementById('careerBusinesses'),Array.isArray(c.businesses)?c.businesses:[],x=>`<article class="career-item"><div><strong>${escCareer(x.name)}</strong><span class="career-badge">${Number(x.employees||0)} emp</span></div><p>${escCareer(x.owner)} - ${escCareer(x.sector)}</p><small>Est. value ${money(x.estimated_value||0)}</small></article>`,'No citizen-owned businesses yet.');
    list(document.getElementById('careerVacancies'),Array.isArray(c.vacancies)?c.vacancies.slice(0,30):[],x=>`<article class="career-item"><div><strong>${escCareer(x.title)}</strong><span class="career-badge">T${Number(x.tier||0)}</span></div><p>${escCareer(x.organization)} - ${escCareer(x.sector)}</p><small>${money(x.weekly_income)}/week</small></article>`);
    list(document.getElementById('careerCatalog'),Array.isArray(c.catalog)?c.catalog:[],x=>`<article class="career-catalog-row"><b>#${Number(x.rank||0)} ${escCareer(x.title)}</b><span>${escCareer(x.sector)}</span><em>T${Number(x.tier||0)} - ${money(x.weekly_income_min)}-${money(x.weekly_income_max)}/wk - ${escCareer(x.minimum_education||'')}</em></article>`);
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
    const v=document.getElementById('careerView');if(v)v.classList.toggle('active',btn.dataset.view==='career');
  }));
  console.info('[Agentopia] Career Economy v1.6.1.4 dashboard active');
})();
/* AGENTOPIA_CAREER_V1614_JS_END */

/* AGENTOPIA_HUMAN_ECONOMY_V170_JS_START */
(()=>{
  const escE=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const money=v=>'$'+Number(v||0).toLocaleString();
  const list=(el,arr,fn,empty='No data yet.')=>{if(!el)return;el.innerHTML=arr.length?arr.map(fn).join(''):`<div class="economy-empty">${empty}</div>`};
  window.AgentopiaV170Economy=function(s){
    const e=s&&s.human_economy;if(!e||!Object.keys(e).length)return;
    const updated=document.getElementById('economyUpdated');if(updated)updated.textContent=`${escE(e.world_week||'seeded')} · ${escE(e.updated_at||'')}`;
    const stats=document.getElementById('economyStats');if(stats)stats.innerHTML=[
      ['Households',e.households],['Homeownership',(Number(e.homeownership_rate||0).toFixed(1)+'%')],['Median HH income',money(e.median_weekly_household_income)+'/wk'],['Median housing',money(e.median_weekly_housing_cost)+'/wk'],
      ['Tax revenue',money(e.tax_revenue_week)],['Consumer spend',money(e.consumer_spending_week)],['Hardship',(Number(e.hardship_rate||0).toFixed(1)+'%')],['CPI',Number(e.cpi||100).toFixed(2)],['Income Gini',Number(e.income_gini||0).toFixed(3)],['City treasury',money(e.municipal_treasury)]
    ].map(x=>`<div class="economy-stat"><span>${x[0]}</span><strong>${x[1]}</strong></div>`).join('');
    const classes=Object.entries(e.economic_classes||{}).sort((a,b)=>Number(b[1])-Number(a[1]));
    list(document.getElementById('economyClasses'),classes,x=>`<article class="economy-item compact"><div><strong>${escE(String(x[0]).replaceAll('_',' '))}</strong><span>${Number(x[1])}</span></div></article>`);
    list(document.getElementById('economyNeighborhoods'),Array.isArray(e.neighborhoods)?e.neighborhoods:[],x=>`<article class="economy-item"><div><strong>${escE(x.neighborhood)}</strong><span>${Number(x.households||0)} HH</span></div><p>Housing ${money(x.median_weekly_housing_cost)}/wk · HH income ${money(x.median_weekly_household_income)}/wk</p><small>${Number(x.owners||0)} owner/mortgage · ${Number(x.renters||0)} renter</small></article>`);
    const spending=Object.entries(e.spending_categories||{}).filter(x=>Number(x[1])!==0).sort((a,b)=>Number(b[1])-Number(a[1]));
    list(document.getElementById('economySpending'),spending,x=>`<article class="economy-item compact"><div><strong>${escE(String(x[0]).replaceAll('_',' '))}</strong><span>${money(x[1])}</span></div></article>`,'No weekly settlement yet.');
    list(document.getElementById('economyHardship'),Array.isArray(e.hardship_households_detail)?e.hardship_households_detail:[],x=>`<article class="economy-item"><div><strong>${escE((x.members||[]).join(', ')||x.household_id)}</strong><span class="economy-badge">${Number(x.hardship_score||0)}/100</span></div><p>${escE(x.economic_class||'')} · arrears ${money(x.arrears)}</p><small>Ending household cash ${money(x.ending_cash)}</small></article>`,'No households currently flagged for material hardship.');
    list(document.getElementById('economyEvents'),Array.isArray(e.recent_events)?[...e.recent_events].reverse().slice(0,25):[],x=>`<article class="economy-item"><div><strong>${escE(String(x.event||'economic event').replaceAll('_',' '))}</strong></div><p>${escE(x.citizen||x.household_id||'Detroit')}</p><small>${x.amount?money(x.amount):escE(x.world_week||'')}</small></article>`,'No Human Economy events yet.');
    const prices=Object.entries(e.price_indices||{}).sort((a,b)=>String(a[0]).localeCompare(String(b[0])));
    list(document.getElementById('economyPrices'),prices,x=>`<article class="economy-item compact"><div><strong>${escE(x[0])}</strong><span>${Number(x[1]||1).toFixed(4)}</span></div></article>`);
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{
    const v=document.getElementById('economyView');if(v)v.classList.toggle('active',btn.dataset.view==='economy');
    try{if(btn.dataset.view==='economy'&&typeof state!=='undefined'&&state.snapshot)window.AgentopiaV170Economy(state.snapshot)}catch(_e){}
  }));
  console.info('[Agentopia] Human Economy v1.7.0 dashboard active');
})();
/* AGENTOPIA_HUMAN_ECONOMY_V170_JS_END */

/* AGENTOPIA_BUSINESS_ECONOMY_V171_JS_START */
(() => {
  const escB=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const money=v=>'$'+Number(v||0).toLocaleString();
  const list=(el,arr,fn,empty='No data yet.')=>{if(!el)return;el.innerHTML=arr.length?arr.map(fn).join(''):`<div class="business-empty">${empty}</div>`;};
  window.AgentopiaV171Business=function(s){
    if(!s||!s.ok)return;const b=s.business_economy||{};
    const up=document.getElementById('businessUpdated');if(up)up.textContent=b.updated_at?new Date(b.updated_at).toLocaleString():'Waiting...';
    const st=document.getElementById('businessStats');if(st){const vals=[['Businesses',b.operating_businesses||0],['Profitable',b.profitable_businesses||0],['Distressed',b.distressed_businesses||0],['Bankrupt',b.bankrupt_businesses||0],['Jobs',b.jobs||0],['Revenue',money(b.revenue_week)],['Payroll',money(b.payroll_week)],['Profit',money(b.profit_week)],['Biz tax',money(b.business_tax_week)],['Layoffs',b.layoffs_week||0]];st.innerHTML=vals.map(x=>`<article><span>${x[0]}</span><strong>${x[1]}</strong></article>`).join('');}
    list(document.getElementById('businessLargest'),Array.isArray(b.largest_businesses)?b.largest_businesses:[],x=>`<article class="business-item"><div><strong>${escB(x.name)}</strong><span class="business-badge">${escB(x.entity_type||'firm')}</span></div><p>${escB(x.sector)} · ${Number(x.employees||0)} employees${x.owner?' · owner '+escB(x.owner):''}</p><small>Value ${money(x.estimated_value)} · revenue ${money(x.revenue)} · profit ${money(x.profit)} · cash ${money(x.cash)} · debt ${money(x.debt)}</small></article>`);
    list(document.getElementById('businessSectors'),Array.isArray(b.sector_economy)?b.sector_economy:[],x=>`<article class="business-item"><div><strong>${escB(x.sector)}</strong><span>${Number(x.businesses||0)} firms</span></div><p>${Number(x.employees||0)} jobs · revenue ${money(x.revenue)}</p><small>Profit ${money(x.profit)} · debt ${money(x.debt)}</small></article>`);
    list(document.getElementById('businessOpenings'),Array.isArray(b.openings)?b.openings.slice(0,30):[],x=>`<article class="business-item"><div><strong>${escB(x.title)}</strong><span class="business-badge">T${Number(x.tier||0)}</span></div><p>${escB(x.organization)} · ${escB(x.sector)}</p><small>${money(x.weekly_income)}/week</small></article>`,'No expansion openings yet.');
    list(document.getElementById('businessEvents'),Array.isArray(b.recent_events)?[...b.recent_events].reverse().slice(0,30):[],x=>`<article class="business-item"><div><strong>${escB(String(x.event||'business event').replaceAll('_',' '))}</strong></div><p>${escB(x.business||'Detroit economy')}${x.citizen?' · '+escB(x.citizen):''}</p><small>${x.amount?money(x.amount):x.layoffs?x.layoffs+' layoffs':escB(x.world_week||'')}</small></article>`);
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('businessView');if(v)v.classList.toggle('active',btn.dataset.view==='business');try{if(typeof state!=='undefined'&&state.snapshot)window.AgentopiaV171Business(state.snapshot)}catch(_e){}}));
  console.info('[Agentopia] Business Economy v1.7.1 dashboard active');
})();
/* AGENTOPIA_BUSINESS_ECONOMY_V171_JS_END */

/* AGENTOPIA_EDUCATION_SKILLS_V172_JS_START */
(() => {
  const RELEASE='1.7.2';
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const money=v=>'$'+Number(v||0).toLocaleString();
  const list=(el,arr,fn,empty='No data yet.')=>{if(!el)return;el.innerHTML=arr.length?arr.map(fn).join(''):`<div class="education-empty">${empty}</div>`;};
  window.AgentopiaReleaseVersion=function(s){
    const v=String((s&&s.release_version)||RELEASE);
    const el=document.getElementById('agentopiaReleaseVersion');
    if(el)el.innerHTML=`Agentopia Detroit v${esc(v)} &middot; Education &amp; Skills Economy`;
    document.querySelectorAll('body *').forEach(node=>{
      if(node===el||node.children.length)return;
      const t=(node.textContent||'').trim();
      if(/^Agentopia Detroit v1(?:\.\d+){2,3}$/.test(t))node.textContent=`Agentopia Detroit v${v}`;
      if(/^v?1\.6\.0$/.test(t))node.textContent=`v${v}`;
    });
  };
  window.AgentopiaV172Education=function(s){
    if(!s||!s.ok)return;const e=s.education_skills||{};window.AgentopiaReleaseVersion(s);
    const up=document.getElementById('educationUpdated');if(up)up.textContent=e.updated_at?`${esc(e.world_week||'seeded')} · ${new Date(e.updated_at).toLocaleString()}`:'Waiting...';
    const st=document.getElementById('educationStats');if(st){const vals=[['Tracked',e.citizens_tracked||0],['Enrolled',e.enrolled||0],['K-12',e.k12_students||0],['Adult learners',e.adult_learners||0],['Apprentices',e.apprentices||0],['Programs',e.program_count||0],['Credentials',e.credentials_awarded_total||0],['Student debt',money(e.student_debt_total)],['Borrowers',e.borrowers||0],['Median debt',money(e.median_student_debt)]];st.innerHTML=vals.map(x=>`<article><span>${x[0]}</span><strong>${x[1]}</strong></article>`).join('');}
    list(document.getElementById('educationInstitutions'),Array.isArray(e.institutions)?e.institutions:[],x=>`<article class="education-item"><div><strong>${esc(x.name)}</strong><span class="education-badge">${Number(x.enrolled||0)} enrolled</span></div><p>${esc(x.type||'')} · ${esc(x.focus||'')}</p></article>`);
    const paths=Object.entries(e.pathways||{}).sort((a,b)=>Number(b[1])-Number(a[1]));list(document.getElementById('educationPathways'),paths,x=>`<article class="education-item compact"><div><strong>${esc(x[0])}</strong><span>${Number(x[1])}</span></div></article>`,'No active enrollment yet.');
    list(document.getElementById('educationSkills'),Array.isArray(e.top_skills)?e.top_skills:[],x=>`<article class="education-item"><div><strong>${esc(x.skill)}</strong><span>${Number(x.average||0).toFixed(1)}/300</span></div><small>${Number(x.citizens||0)} citizens with recorded skill</small></article>`);
    list(document.getElementById('educationDebt'),Array.isArray(e.highest_student_debt)?e.highest_student_debt:[],x=>`<article class="education-item"><div><strong>${esc(x.name)}</strong><span class="education-badge">${money(x.student_debt)}</span></div><p>${esc(x.education||'')}${x.program?' · '+esc(x.program):''}</p></article>`,'No student debt yet.');
    list(document.getElementById('educationEvents'),Array.isArray(e.recent_events)?[...e.recent_events].reverse().slice(0,35):[],x=>`<article class="education-item"><div><strong>${esc(String(x.event||'education event').replaceAll('_',' '))}</strong></div><p>${esc(x.citizen||'Detroit education system')}${x.program?' · '+esc(x.program):''}</p><small>${x.amount?money(x.amount):esc(x.credential||x.education||x.world_week||'')}</small></article>`);
    list(document.getElementById('educationPrograms'),Array.isArray(e.programs)?e.programs:[],x=>`<article class="education-item"><div><strong>${esc(x.title)}</strong><span class="education-badge">${esc(x.pathway)}</span></div><p>${esc(x.sector||'General')} · ${Number(x.duration_weeks||0)} weeks</p><small>${Number(x.tuition_week||0)?money(x.tuition_week)+'/week':'public/employer funded'} · ${esc(x.credential||'')}</small></article>`);
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('educationView');if(v)v.classList.toggle('active',btn.dataset.view==='education');try{if(btn.dataset.view==='education'&&typeof state!=='undefined'&&state.snapshot)window.AgentopiaV172Education(state.snapshot)}catch(_e){}}));
  try{window.AgentopiaReleaseVersion(typeof state!=='undefined'?state.snapshot:null)}catch(_e){}
  console.info('[Agentopia] Education & Skills Economy v1.7.2 dashboard active');
})();
/* AGENTOPIA_EDUCATION_SKILLS_V172_JS_END */

/* AGENTOPIA_HEALTHCARE_V173_JS_START */
(() => {
  const RELEASE='1.7.3';
  const RELEASE_NAME='Health & Healthcare Economy';
  const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const money=v=>'$'+Number(v||0).toLocaleString();
  const list=(el,arr,fn,empty='No data yet.')=>{if(!el)return;el.innerHTML=arr.length?arr.map(fn).join(''):`<div class="health-empty">${empty}</div>`;};
  window.AgentopiaReleaseVersion=function(s){
    const v=String((s&&s.release_version)||RELEASE),name=String((s&&s.release_name)||RELEASE_NAME);
    const el=document.getElementById('agentopiaReleaseVersion');
    if(el)el.innerHTML=`Agentopia Detroit v${esc(v)} &middot; ${esc(name)}`;
    document.querySelectorAll('body *').forEach(node=>{
      if(node===el||node.children.length)return;
      const t=(node.textContent||'').trim();
      if(/^Agentopia Detroit v1(?:\.\d+){2,3}$/.test(t))node.textContent=`Agentopia Detroit v${v}`;
      if(/^v?1\.6\.0$/.test(t))node.textContent=`v${v}`;
    });
  };
  window.AgentopiaV173Health=function(s){
    if(!s||!s.ok)return;const h=s.healthcare||{};window.AgentopiaReleaseVersion(s);
    const up=document.getElementById('healthUpdated');if(up)up.textContent=h.updated_at?`${esc(h.world_week||'seeded')} · ${new Date(h.updated_at).toLocaleString()}`:'Waiting...';
    const st=document.getElementById('healthStats');if(st){const vals=[
      ['Tracked',h.citizens_tracked||0],['Insured',`${Number(h.insured_pct||0).toFixed(1)}%`],['Physical',`${Number(h.average_physical_health||0).toFixed(1)}/100`],['Mental',`${Number(h.average_mental_wellbeing||0).toFixed(1)}/100`],['Stress',`${Number(h.average_stress||0).toFixed(1)}/100`],['Work capacity',`${Number(h.average_work_capacity||0).toFixed(1)}/100`],['Active issues',h.active_conditions||0],['Care visits',h.care_visits_week||0],['Claims',money(h.insurance_claims_week)],['Medical debt',money(h.medical_debt_total)],['ER/acute',h.emergency_visits_week||0],['Sick days',Number(h.sick_days_week||0).toFixed(1)]
    ];st.innerHTML=vals.map(x=>`<article><span>${x[0]}</span><strong>${x[1]}</strong></article>`).join('');}
    list(document.getElementById('healthProviders'),Array.isArray(h.providers)?h.providers:[],x=>`<article class="health-item"><div><strong>${esc(x.name)}</strong><span class="health-badge">${Number(x.utilization_pct||0).toFixed(0)}%</span></div><p>${esc(x.type||'')} · ${Number(x.visits_week||0)}/${Number(x.weekly_capacity||0)} visits</p><small>${money(x.revenue_week)} care revenue this week</small></article>`);
    list(document.getElementById('healthClasses'),Array.isArray(h.health_by_economic_class)?h.health_by_economic_class:[],x=>`<article class="health-item"><div><strong>${esc(x.economic_class||'unknown')}</strong><span>${Number(x.citizens||0)} citizens</span></div><p>Physical ${Number(x.avg_physical||0).toFixed(1)} · Mental ${Number(x.avg_mental||0).toFixed(1)} · Stress ${Number(x.avg_stress||0).toFixed(1)}</p><small>Medical debt ${money(x.medical_debt)}</small></article>`);
    list(document.getElementById('healthBurden'),Array.isArray(h.highest_health_burden)?h.highest_health_burden:[],x=>`<article class="health-item"><div><strong>${esc(x.name)}</strong><span class="health-badge">capacity ${Number(x.work_capacity||0)}%</span></div><p>Physical ${Number(x.physical_health||0)} · Mental ${Number(x.mental_wellbeing||0)} · Stress ${Number(x.stress||0)} · Active ${Number(x.active_conditions||0)}</p><small>${x.chronic_conditions&&x.chronic_conditions.length?'Chronic: '+esc(x.chronic_conditions.join(', ')):'No chronic condition recorded'} · debt ${money(x.medical_debt)}</small></article>`);
    list(document.getElementById('healthEvents'),Array.isArray(h.recent_events)?[...h.recent_events].reverse().slice(0,40):[],x=>`<article class="health-item"><div><strong>${esc(String(x.event||'health event').replaceAll('_',' '))}</strong></div><p>${esc(x.citizen||'Detroit healthcare system')}${x.provider?' · '+esc(x.provider):''}${x.event_type?' · '+esc(String(x.event_type).replaceAll('_',' ')):''}</p><small>${x.gross_cost!=null?money(x.gross_cost)+' gross · patient '+money(x.patient_paid||0)+' · insurer '+money(x.insurance_paid||0):esc(x.condition||x.reason||x.world_week||'')}</small></article>`);
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('healthcareView');if(v)v.classList.toggle('active',btn.dataset.view==='healthcare');try{if(btn.dataset.view==='healthcare'&&typeof state!=='undefined'&&state.snapshot)window.AgentopiaV173Health(state.snapshot)}catch(_e){}}));
  try{window.AgentopiaReleaseVersion(typeof state!=='undefined'?state.snapshot:null)}catch(_e){}
  console.info('[Agentopia] Health & Healthcare Economy v1.7.3 dashboard active');
})();
/* AGENTOPIA_HEALTHCARE_V173_JS_END */

/* AGENTOPIA_MOBILITY_V174_JS_START */
(() => {
  const RELEASE='1.7.4',RELEASE_NAME='Mobility & Time';
  const escM=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=v=>'$'+Number(v||0).toLocaleString();
  function list(el,arr,fn,empty='No mobility data yet.'){if(!el)return;el.innerHTML=(arr||[]).length?(arr||[]).map(fn).join(''):`<div class="mobility-empty">${escM(empty)}</div>`;}
  function phaseClock(raw){
    const s=String(raw||'').toLowerCase();let day='Sun',time='8:00 PM';
    if(s.includes('before_contact')){day='Mon';time='6:30 AM'}
    else if(s.includes('after_contact')){day='Fri';time='9:00 PM'}
    else if(s.includes('contact')){const m=s.match(/-s(\d+)/);const n=Math.max(1,Math.min(5,Number(m?.[1]||1)));day=['Mon','Tue','Wed','Thu','Fri'][n-1];time='5:30 PM'}
    else if(s.includes('activity')){day='Sat';time='2:00 PM'}
    else if(s.includes('review')){day='Sun';time='5:00 PM'}
    return `${day} ${time}`;
  }
  window.AgentopiaV174Mobility=function(s){
    const m=s?.mobility_time||{};if(!m||!Object.keys(m).length)return;
    const u=document.getElementById('mobilityUpdated');if(u)u.textContent=m.updated_at?new Date(m.updated_at).toLocaleString():'Updated';
    const clock=document.getElementById('mobilityClock');if(clock)clock.textContent=phaseClock(s?.current_time||m.engine_time||'');
    const ph=document.getElementById('mobilityPhase');if(ph)ph.textContent=`${String(m.phase||'').replaceAll('_',' ')}${m.slot?' · slot '+m.slot:''} · ${escM((m.weather||{}).condition||'normal conditions')}`;
    const st=document.getElementById('mobilityStats');if(st){const vals=[['Citizens',m.citizens_tracked||0],['Trips / week',m.trips_week||0],['Avg commute',Number(m.avg_commute_minutes||0).toFixed(1)+' min'],['Long commutes',m.long_commutes||0],['Congestion',Number(m.congestion_index||1).toFixed(2)+'x'],['Transit',Number(m.transit_share_pct||0).toFixed(1)+'%'],['Active travel',Number(m.active_transport_share_pct||0).toFixed(1)+'%'],['Vehicles',m.vehicle_count||0],['EV share',Number(m.ev_share_pct||0).toFixed(1)+'%'],['AV share',Number(m.autonomous_share_pct||0).toFixed(1)+'%'],['Transport spend',money(m.transport_spend_week)],['Incidents',m.incidents_week||0]];st.innerHTML=vals.map(x=>`<article><span>${x[0]}</span><strong>${x[1]}</strong></article>`).join('');}
    const modes=Object.entries(m.mode_share||{}).sort((a,b)=>Number(b[1])-Number(a[1]));
    list(document.getElementById('mobilityModes'),modes,x=>`<article class="mobility-item compact"><div><strong>${escM(String(x[0]).replaceAll('_',' '))}</strong><span>${Number(x[1])} trips</span></div></article>`);
    list(document.getElementById('mobilityCorridors'),m.busiest_corridors||[],x=>`<article class="mobility-item compact"><div><strong>${escM(x.corridor)}</strong><span>${Number(x.trips||0)} trips</span></div></article>`);
    list(document.getElementById('mobilityCitizens'),m.citizen_mobility||[],x=>`<article class="mobility-item"><div><strong>${escM(x.name)}</strong><span class="mobility-badge">${escM(String(x.mode||'').replaceAll('_',' '))}</span></div><p>${escM(x.home)} -> ${escM(x.destination)} · ${Number(x.avg_commute_minutes||0).toFixed(0)} min</p><small>${Number(x.weekly_miles||0).toFixed(1)} mi/week · ${escM(String(x.vehicle||'none').replaceAll('_',' '))} · transport budget ${money(x.transport_budget)}</small></article>`);
    list(document.getElementById('mobilityEvents'),Array.isArray(m.recent_events)?[...m.recent_events].reverse().slice(0,25):[],x=>`<article class="mobility-item"><div><strong>${escM(String(x.event||'mobility event').replaceAll('_',' '))}</strong><span>${escM(x.day||'')}</span></div><p>${escM(x.citizen||'Detroit')} ${x.corridor?'· '+escM(x.corridor):''}</p><small>${escM(x.severity||x.weather||x.world_week||'')}</small></article>`,'No significant mobility incidents this week.');
    const badge=document.getElementById('agentopiaReleaseVersion');if(badge)badge.innerHTML=`Agentopia Detroit v${escM(String(s?.release_version||RELEASE))} &middot; ${escM(String(s?.release_name||RELEASE_NAME))}`;
  };
  document.querySelectorAll('.tab').forEach(btn=>btn.addEventListener('click',()=>{const v=document.getElementById('mobilityView');if(v)v.classList.toggle('active',btn.dataset.view==='mobility');try{if(typeof state!=='undefined'&&state.snapshot)window.AgentopiaV174Mobility(state.snapshot)}catch(_e){}}));
  try{if(typeof state!=='undefined'&&state.snapshot)window.AgentopiaV174Mobility(state.snapshot)}catch(_e){}
  console.info('[Agentopia] Mobility & Time v1.7.4 dashboard active');
})();
/* AGENTOPIA_MOBILITY_V174_JS_END */

/* AGENTOPIA_MOBILITY_TAB_HOTFIX_V1741_START */
(() => {
  // v1.7.4.1: Mobility was added after the legacy tab controller had already
  // registered its handlers. Own this one tab in capture phase so older
  // listeners cannot immediately undo the selected panel.
  document.addEventListener('click', (event) => {
    const raw = event.target;
    const btn = raw && raw.closest ? raw.closest('.tab[data-view="mobility"]') : null;
    if (!btn) return;
    const panel = document.getElementById('mobilityView');
    if (!panel) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    document.querySelectorAll('.tab').forEach((tab) => {
      const selected = tab === btn;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    document.querySelectorAll('.view-panel').forEach((view) => {
      view.classList.toggle('active', view === panel);
    });

    try {
      if (typeof state !== 'undefined' && state.snapshot && window.AgentopiaV174Mobility) {
        window.AgentopiaV174Mobility(state.snapshot);
      }
    } catch (_error) {}
  }, true);

  console.info('[Agentopia] v1.7.4.1 Mobility tab navigation hotfix active');
})();
/* AGENTOPIA_MOBILITY_TAB_HOTFIX_V1741_END */

/* AGENTOPIA_MOBILITY_HITBOX_V1742_JS_START */
(() => {
  const MAX_Z = '2147482000';

  function protectTabHitboxes() {
    const mobility = document.querySelector('.tab[data-view="mobility"]');
    if (!mobility) return;

    const bar = mobility.closest('[role="tablist"], .tabs, .tab-bar, .tabs-bar') || mobility.parentElement;
    if (bar) {
      bar.style.setProperty('position', 'relative', 'important');
      bar.style.setProperty('z-index', MAX_Z, 'important');
      bar.style.setProperty('pointer-events', 'auto', 'important');
      bar.style.setProperty('overflow', 'visible', 'important');
      bar.style.setProperty('height', 'auto', 'important');
      bar.style.setProperty('min-height', '36px', 'important');
      bar.style.setProperty('flex-wrap', 'wrap', 'important');
      bar.style.setProperty('row-gap', '6px', 'important');

      const shell = bar.closest('header, .topbar, .toolbar, .header, .nav-shell');
      if (shell) {
        shell.style.setProperty('position', 'relative', 'important');
        shell.style.setProperty('z-index', '2147481900', 'important');
        shell.style.setProperty('overflow', 'visible', 'important');
        shell.style.setProperty('height', 'auto', 'important');
      }
    }

    document.querySelectorAll('.tab, [role="tab"]').forEach((tab) => {
      tab.style.setProperty('position', 'relative', 'important');
      tab.style.setProperty('z-index', '2147482001', 'important');
      tab.style.setProperty('pointer-events', 'auto', 'important');
      tab.style.setProperty('cursor', 'pointer', 'important');
      tab.style.setProperty('flex', '0 0 auto', 'important');
    });
    mobility.style.setProperty('z-index', '2147482002', 'important');

    // Record what is physically above the Mobility button. This is diagnostic
    // evidence in DevTools without changing the underlying simulation.
    requestAnimationFrame(() => {
      const r = mobility.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const x = r.left + r.width / 2;
      const y = r.top + r.height / 2;
      const stack = document.elementsFromPoint(x, y);
      const top = stack && stack.length ? stack[0] : null;
      mobility.dataset.hitboxTop = top ? `${top.tagName.toLowerCase()}#${top.id || ''}.${String(top.className || '').replace(/\s+/g,'.')}` : 'none';
      if (top && top !== mobility && !mobility.contains(top)) {
        console.warn('[Agentopia v1.7.4.2] Mobility hitbox was covered by:', top);
      }
    });
  }

  function selectMobility(event) {
    const target = event.target && event.target.closest ? event.target.closest('.tab[data-view="mobility"]') : null;
    if (!target) return;
    const panel = document.getElementById('mobilityView');
    if (!panel) return;

    event.preventDefault();
    event.stopImmediatePropagation();

    document.querySelectorAll('.tab, [role="tab"]').forEach((tab) => {
      const selected = tab === target;
      tab.classList.toggle('active', selected);
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    document.querySelectorAll('.view-panel').forEach((view) => {
      view.classList.toggle('active', view === panel);
    });

    try {
      if (typeof state !== 'undefined' && state.snapshot && window.AgentopiaV174Mobility) {
        window.AgentopiaV174Mobility(state.snapshot);
      }
    } catch (_error) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', protectTabHitboxes, {once:true});
  } else {
    protectTabHitboxes();
  }
  window.addEventListener('resize', protectTabHitboxes, {passive:true});
  document.addEventListener('click', selectMobility, true);

  console.info('[Agentopia] v1.7.4.2 Mobility physical hitbox/overlay hotfix active');
})();
/* AGENTOPIA_MOBILITY_HITBOX_V1742_JS_END */


/* AGENTOPIA_CITY_PULSE_TRUTH_V17451_START */
(() => {
  const q = id => document.getElementById(id);
  const txt = el => String(el?.textContent || '').trim();

  function canonicalStage() {
    const phase = txt(q('phaseName')).toLowerCase();
    const sim = txt(q('simTime'));
    const d = sim.match(/\bD(\d+)\b/i);
    const s = sim.match(/\bS(\d+)\b/i);
    if (phase === 'activity') return d ? `ACTIVITY D${d[1]}` : 'ACTIVITY';
    if (phase === 'contact') return s ? `CONTACT S${s[1]}` : 'CONTACT';
    if (phase) return phase.replaceAll('_',' ').toUpperCase();
    const m = sim.match(/\b(plan|before contact|contact|after contact|activity|review|settle)\b/i);
    return m ? m[1].toUpperCase() : 'LIVE';
  }

  function phaseElapsed() {
    const t=txt(q('phaseElapsed'));
    return t ? t.replace(/^⏱\s*/, '') : '—';
  }

  function bodyRelease() {
    const m=String(document.body?.innerText || '').match(/Agentopia Detroit v(\d+(?:\.\d+){2,4})/i);
    return m ? m[1] : '';
  }

  async function updateVersion() {
    let v='';
    try {
      const r=await fetch(`/api/health?t=${Date.now()}`,{cache:'no-store'});
      if(r.ok){
        const h=await r.json();
        v=String(h.release_version || h.app_version || h.version || h.engine_version || '').trim();
      }
    } catch (_) {}
    if(!v) v=bodyRelease();
    if(v && q('cityPulseVersion')) q('cityPulseVersion').textContent=`v${v}`;
  }

  function repairPulse() {
    const stage=canonicalStage();
    const hb=q('cpHeartbeat');
    if(hb){
      const current=txt(hb);
      const age=(current.match(/heartbeat\s+([^•]+)/i)||[])[1]?.trim() || '—';
      hb.textContent=`heartbeat ${age} • ${stage} ${phaseElapsed()}`;
    }

    const progress=q('cpProgress');
    if(progress){
      const current=txt(progress);
      const total=(current.match(/\/(\d+)\s+citizens/i)||[])[1];
      const bad=/unknown|collecting|0\/\d+\s+citizens have reported activity in unknown/i.test(current);
      if(bad){
        progress.textContent = total ? `${stage} in progress • ${total} active citizens` : `${stage} in progress`;
        const bar=q('cpProgressBar');
        if(bar && Number(bar.style.width.replace('%','') || 0) === 0) bar.style.width='8%';
      }
    }

    const stream=q('cpStream');
    if(stream && stream.querySelector('.cp-empty')){
      const raw=txt(q('engineLog'));
      const lines=raw.split(/\n+/).map(x=>x.trim()).filter(Boolean)
        .filter(x=>/ACTIVITY|SOLO_ACTIVITY|CONTACT|MISSION|FACTION|weekly_income|completed|failed|WARNING|ERROR/i.test(x))
        .slice(-8);
      if(lines.length){
        stream.replaceChildren();
        for(const line of lines){
          const row=document.createElement('div'); row.className='cp-pulse-row cp-pulse-fallback';
          const t=document.createElement('time'); t.textContent='RAW';
          const msg=document.createElement('span'); msg.textContent=line;
          row.append(t,msg); stream.appendChild(row);
        }
      } else {
        const empty=stream.querySelector('.cp-empty');
        if(empty) empty.textContent=`${stage} is active; waiting for the next persisted world event…`;
      }
    }

    document.querySelectorAll('.cp-model').forEach(row=>{
      const s=txt(row);
      row.classList.remove('cp-saturated','cp-busy');
      const m=s.match(/(\d+)\/(\d+)\s+busy/i);
      if(m){
        const b=Number(m[1]), n=Number(m[2]);
        if(n>0 && b>=n) row.classList.add('cp-saturated');
        else if(n>0 && b/n>=0.75) row.classList.add('cp-busy');
      }
    });
  }

  setInterval(repairPulse,1000);
  setInterval(updateVersion,15000);
  setTimeout(()=>{ repairPulse(); updateVersion(); },250);
})();
/* AGENTOPIA_CITY_PULSE_TRUTH_V17451_END */
