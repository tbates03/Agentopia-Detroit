/* Live Agentopia population rendered in Detroit GIS coordinates.
 * Read-only /api/snapshot, as exposed by live_world/server.py.
 * The observer provides semantic locations, not physical GPS tracks. Anchors
 * and short walking loops are EXPLICITLY illustrative and never written back.
 */
import * as T from 'three/webgpu';
import {xy} from './geography.js';
import {hashName, normalizeSnapshot, semanticAnchor, roadCandidatePoints, nearestMappedRoad} from './society-logic.js';
const MAX=512;
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
export function createLiveCitizens(scene,regions,{onUpdate=()=>{},onInspect=()=>{}}={}){
  const group=new T.Group(); group.name='Agentopia real observer citizens: geographic placement inferred';scene.add(group);
  const torsoMat=new T.MeshStandardMaterial({color:0xffffff,roughness:.66,metalness:.02});
  const headMat=new T.MeshStandardMaterial({color:0xf3cead,roughness:.85});
  const limbMat=new T.MeshStandardMaterial({color:0x23384a,roughness:.92});
  const ringMat=new T.MeshBasicMaterial({color:0x71f1d1,transparent:true,opacity:.42,depthWrite:false,side:T.DoubleSide});
  const torso=new T.InstancedMesh(new T.CylinderGeometry(.020,.028,.085,7),torsoMat,MAX);
  const head=new T.InstancedMesh(new T.SphereGeometry(.024,7,5),headMat,MAX);
  const limb=new T.InstancedMesh(new T.CylinderGeometry(.010,.012,.068,6),limbMat,MAX);
  const halo=new T.InstancedMesh(new T.RingGeometry(.065,.078,22),ringMat,MAX);
  torso.name='Live resident bodies'; head.name='Live resident heads'; limb.name='Live resident legs'; halo.name='Live resident location circles';
  [torso,head,limb,halo].forEach(mesh=>{mesh.count=0;mesh.frustumCulled=false;group.add(mesh);mesh.userData.agentLayer=true;});
  const m=new T.Matrix4(), p=new T.Vector3(), q=new T.Quaternion(), scale=new T.Vector3(1,1,1);
  const flat=new T.Quaternion().setFromAxisAngle(new T.Vector3(1,0,0),-Math.PI/2);
  let records=[], current=null,lastError='',lastSuccess=0,lastRequest=0,disposed=false,busy=false,selected='', enabled=true, timer=null;
  const points=roadCandidatePoints(regions,xy);
  const locations=new Map();
  const setPose=(mesh,i,x,y,z,rot=q,s=scale)=>{
    m.compose(p.set(x,y,z),rot,s); mesh.setMatrixAt(i,m);
  };
  const clear=()=>{for(const mesh of [torso,head,limb,halo])mesh.count=0;};
  const sortColor=(name,faction)=>{
    const n=hashName(name); if(/guardian/i.test(faction))return new T.Color(0x3b94cd);
    if(/obsidian/i.test(faction))return new T.Color(0x9567b8);
    return new T.Color().setHSL((n%360)/360,.45,.52);
  };
  function updateCitizens(snap){
    const now=performance.now();const prior=new Map(records.map(row=>[row.name,row]));
    records=snap.agents.slice(0,MAX).map((a,i)=>{
      const [px,pz]=xy(a.lat,a.lon);
      const [x,z]=a.accuracy==='reported GPS'?[px,pz]:nearestMappedRoad([px,pz],points);
      const old=prior.get(a.name);
      return {...a,x,z,initialX:old?.x??x,initialZ:old?.z??z,started:now,phase:(hashName(a.name)%1000)/151};
    });
    for(const mesh of [torso,head,limb,halo])mesh.count=records.length;
    records.forEach((a,i)=>{torso.setColorAt(i,sortColor(a.name,a.faction));});
    if(torso.instanceColor)torso.instanceColor.needsUpdate=true;
    current=snap;lastSuccess=Date.now();lastError='';
    onUpdate({ok:true,clock:snap.clock,engine:snap.engine,active:snap.active,total:snap.total,shown:records.length,
      locationMode:'GPS when supplied; otherwise visual placement snapped to mapped Detroit streets',
      mobilityCount:snap.mobilityCount,people:records.slice(0,40),age:0});
    if(selected){const chosen=records.find(r=>r.name===selected);if(chosen)onInspect(chosen);}
  }
  async function refresh(){
    if(disposed||busy||!enabled)return;
    busy=true;lastRequest=Date.now();
    try{
      const response=await fetch('/api/snapshot',{cache:'no-store',signal:AbortSignal.timeout(22000)});
      if(!response.ok)throw new Error('Observer HTTP '+response.status);
      const raw=await response.json(),snap=normalizeSnapshot(raw);
      updateCitizens(snap);
    }catch(err){
      lastError=String(err?.message||err);
      onUpdate({ok:false,lastError,clock:current?.clock||'',engine:current?.engine||'offline',
        shown:records.length,total:current?.total||0,active:current?.active||0,age:lastSuccess?Math.round((Date.now()-lastSuccess)/1000):null,
        people:records.slice(0,40)});
    }finally{busy=false;}
  }
  function tick(time,camera){
    if(disposed)return;
    group.visible=enabled;
    if(!enabled||!records.length)return;
    const elapsed=time/1000;
    const dist=camera?camera.position.distanceTo(new T.Vector3(0,0,0)):30;
    const ringScale=clamp(dist/65,.6,2);
    records.forEach((a,i)=>{
      const duration=clamp((time-a.started)/2400,0,1);
      const eased=duration*duration*(3-2*duration);
      const baseX=a.initialX+(a.x-a.initialX)*eased;
      const baseZ=a.initialZ+(a.z-a.initialZ)*eased;
      // Short illustrative walk loops ONLY when activity reports motion.
      const stride=a.movement?Math.sin(elapsed*.64+a.phase)*.035:0;
      const breathing=a.movement?Math.abs(Math.sin(elapsed*3.2+a.phase))*.006:0;
      const x=baseX+stride,z=baseZ+stride*.43;
      setPose(torso,i,x,.245+breathing,z);
      setPose(head,i,x,.313+breathing,z);
      setPose(limb,i,x,.171+breathing,z);
      setPose(halo,i,x,.146,z,flat,new T.Vector3(ringScale,ringScale,ringScale));
    });
    for(const mesh of [torso,head,limb,halo])mesh.instanceMatrix.needsUpdate=true;
  }
  function inspectHit(hit){
    if(hit?.object?.userData?.agentLayer && Number.isInteger(hit.instanceId)){
      const record=records[hit.instanceId];if(!record)return null;
      selected=record.name;onInspect(record);return record;
    }return null;
  }
  function choose(name){
    const a=records.find(row=>row.name===name);if(!a)return null;
    selected=a.name;onInspect(a);return a;
  }
  function status(){return {ok:!!current&&!lastError,recordCount:records.length,clock:current?.clock||'',lastError,selected,lastSuccess,enabled};}
  function start(){refresh();timer=setInterval(refresh,9000);}
  function dispose(){disposed=true;if(timer)clearInterval(timer);scene.remove(group);for(const mesh of [torso,head,limb,halo])mesh.geometry.dispose();for(const mat of [torsoMat,headMat,limbMat,ringMat])mat.dispose();}
  function setEnabled(yes){enabled=!!yes;group.visible=enabled;if(enabled&&!current)refresh();}
  return {group,start,refresh,tick,dispose,status,choose,inspectHit,setEnabled,getRecords:()=>records};
}
