/* Adapter for the REAL /api/snapshot observer contract from live_world/server.py.
 * No mock/fabricated citizens. Locations are semantic unless actual GPS supplied.
 */
export function hashName(text) {
  let h = 2166136261;
  for (const char of String(text || '')) { h ^= char.charCodeAt(0); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
export const PLACE_HINTS = Object.freeze({
  park: [42.3365, -83.0302],
  cafe: [42.3329, -83.0470],
  restaurant: [42.3329, -83.0470],
  market: [42.3307, -83.0476],
  store: [42.3307, -83.0476],
  school: [42.3376, -83.0595],
  university: [42.3376, -83.0595],
  transit: [42.3316, -83.0501],
  work: [42.3286, -83.0412],
  office: [42.3286, -83.0412],
  community: [42.3280, -83.0449],
  hall: [42.3280, -83.0449],
  'faction/thai_guardians_hq': [42.3314, -83.0502],
  'faction/obsidian_network_hq': [42.3337, -83.0557],
  home: [42.3365, -83.0574],
});
export function semanticAnchor(agent) {
  const location = String(agent?.location || 'home');
  const explicit = agent?.coordinates || agent?.position;
  if (explicit && typeof explicit === 'object') {
    const lat = Number(explicit.lat ?? explicit.latitude), lon = Number(explicit.lon ?? explicit.lng ?? explicit.longitude);
    if (Number.isFinite(lat) && Number.isFinite(lon) && lat > 42.2 && lat < 42.5 && lon > -83.25 && lon < -82.8) {
      return {lat, lon, accuracy:'reported GPS', className:'coordinates'};
    }
  }
  const key = location.toLowerCase();
  const hint = Object.keys(PLACE_HINTS).find(k => key.includes(k));
  const [lat, lon] = PLACE_HINTS[hint || 'home'];
  const salt = hashName(key + ':' + String(agent.name||''));
  // Homes have no addresses in the snapshot. Spread representative home markers
  // along mapped Detroit neighborhoods rather than stacking everyone at one dot.
  // This is an EXPLICITLY inferred city visualization, never a GPS claim.
  if (key.startsWith('home/')) {
    return {lat:42.329 + ((salt&65535)/65535)*.015,
            lon:-83.079 + (((salt>>>16)&65535)/65535)*.070,
            accuracy:'illustrative neighborhood placement; home address not supplied', className:'home'};
  }
  const small = hint ? .0024 : .0040;
  return {lat:lat+(((salt&1023)/1023)-.5)*small,lon:lon+((((salt>>>10)&1023)/1023)-.5)*small,
          accuracy:'illustrative map placement from observer location',className:hint||'home'};
}
export function normalizeSnapshot(s) {
  if (!s || s.ok !== true || !Array.isArray(s.agents)) throw new Error('Snapshot is missing Agentopia agents[]');
  const mobility = new Map((Array.isArray(s.mobility_time?.citizen_mobility) ? s.mobility_time.citizen_mobility : [])
    .filter(row => typeof row?.name === 'string').map(row => [row.name,row]));
  const agents = s.agents.filter(a => a && typeof a.name === 'string' && a.name.trim()).slice(0,512).map(a => {
    const travel = mobility.get(a.name) || {};
    const pos = semanticAnchor(a);
    const state = String(a.activity_type || '').toLowerCase();
    const movement = /walk|run|transit|commut|travel|bike|shop|park|public|joint/.test(
      `${a.activity || ''} ${state} ${travel.mode || ''} ${a.location || ''}`.toLowerCase());
    return {name:a.name, location:String(a.location||'Unspecified'), activity:String(a.activity||''),
      activityTime:String(a.activity_time||s.current_time||''), job:String(a.job||'Resident'),
      faction:String(a.faction?.name||a.faction?.id||'Independent'), mode:String(travel.mode||'Unknown'),
      destination:String(travel.destination||''), movement, ...pos};
  });
  return {agents,clock:String(s.current_time||''),run:String(s.run||''),engine:String(s.engine?.state||'unknown'),
    total:Number(s.population_total??s.agent_count??agents.length),active:Number(s.runtime_active_count??agents.length),
    updated:Number(s.updated_at||0),mobilityCount:mobility.size};
}
export function nearestMappedRoad(pos, points) {
  if (!points.length) return pos;
  let best = points[0],distance=Infinity;
  for (const item of points) {
    const dx=pos[0]-item[0], dz=pos[1]-item[1], d=dx*dx+dz*dz;
    if(d<distance){distance=d;best=item;}
  }
  // Limit snapping so a recorded GPS coordinate is not moved to a distant road.
  return distance<2.25?best:pos;
}
export function roadCandidatePoints(regions, project) {
  const points=[];
  for(const area of regions||[]) for(const road of area.roads||[]) {
    if(road.bridge||road.tunnel||!Array.isArray(road.p)||road.p.length<2)continue;
    if(!['residential','tertiary','secondary','primary','trunk','pedestrian','footway','service'].includes(String(road.t)))continue;
    for(let i=0;i<road.p.length;i+=Math.max(1,Math.floor(road.p.length/8))){
      const p=road.p[i];if(!Array.isArray(p)||p.length<2)continue;
      const [x,z]=project(Number(p[1]),Number(p[0]));
      if(Number.isFinite(x)&&Number.isFinite(z))points.push([x,z]);
    }
  }
  return points;
}
