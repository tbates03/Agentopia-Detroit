import * as T from 'three/webgpu';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {createGeoCity,destroyGeoCity} from '../v219/geo-city.js';
import {monitorHealth} from '../v219/observer.js';
import {xy} from '../v219/geography.js';
import {createSky} from '../v219/sky.js';
import {loadLocalModels} from '../v219/model-loader.js';
const get=id=>document.getElementById(id),canvas=get('scene');
import {loadLocalEdits} from '../v219/city-edits.js';
import {createLiveCitizens} from '../v219/citizens-live.js';
import {initInlineEditor} from '../v219/city-editor-inline.js';
import {addDetroitBridgeNetwork,removeDetroitBridgeNetwork} from './bridges.js';
import {BRIDGE_REGISTRY,bridgeState} from './bridge-data.js';
const query=new URL(location.href).searchParams;
const settings={light:'day',season:'summer',quality:'high',year:Number(query.get('era'))||2026};
const showError=(error)=>{document.dispatchEvent(new CustomEvent('agentopia:fatal',{detail:{error:String(error?.stack||error)}}));console.error('[Agentopia 2.0.20 startup]',error);get('loading').classList.remove('hidden');get('loading').querySelector('h2').textContent='3D viewer failed to initialize';get('loading-sub').textContent=String(error?.stack||error)+'\nThe original observer and simulation are unaffected.\nSee README-FIRST.md for setup and troubleshooting.';get('renderer-chip').textContent='RENDER ERROR';};
let renderer,controls,scene,camera,pack,city,light,hemi,skyTexture,selected=null,regions=[],mapMeta=null,islandData=null,riverData=null,historicPack=null,localEdits=[],citizens=null,cityEditor=null,bridgeLayer=null;
const bootStart=performance.now();
function bootStage(stage){console.info('[Agentopia 2.0.20]',stage,Math.round(performance.now()-bootStart)+'ms');
 const el=get('loading-sub');if(el)el.textContent=stage;document.dispatchEvent(new CustomEvent('agentopia:stage',{detail:{stage}}));
}
async function geoFetch(uri){
 const response=await fetch(uri,{cache:'no-store',signal:AbortSignal.timeout(45000)});
 if(!response.ok)throw Error('HTTP '+response.status+' reading '+uri);
 return response;
}
const yieldToBrowser=()=>new Promise(resolve=>setTimeout(resolve,0));
const sunSettings={golden:{position:[-34,36,-44],color:0xffddb0,intensity:2.55,background:0xa5b6bf,hemi:1.05},day:{position:[-30,62,18],color:0xfff8ea,intensity:2.45,background:0x98b8c8,hemi:1.03},night:{position:[-18,25,30],color:0x8badd5,intensity:.68,background:0x131e39,hemi:.46}};
function lightScene(){const x=sunSettings[settings.light];light.position.set(...x.position);light.color.setHex(x.color);light.intensity=x.intensity;hemi.intensity=x.hemi;if(skyTexture)skyTexture.dispose();skyTexture=createSky(settings.light);scene.background=skyTexture;scene.environment=skyTexture;scene.environmentIntensity=settings.light==='night'?.38:.72;scene.fog.color.setHex(x.background);renderer.toneMappingExposure=settings.light==='night'?1.48:1.02;}
// Camera is north/Detroit side looking toward Canada (+Z); east (+X) is screen-left.
function setPreset(which,first=false){
const at=(lat,lon,y)=>{const [x,z]=xy(lat,lon);return [x,y,z]};
const presets={
 waterfront:{pos:at(42.3319,-83.0505,6.5),target:at(42.32835,-83.0407,1.52)},
 aerial:{pos:at(42.3378,-83.0540,20),target:at(42.3289,-83.0415,1.2)},
 street:{pos:at(42.3311,-83.0493,.14),target:at(42.3296,-83.0478,.18)},
 landmark:{pos:at(42.3312,-83.0435,4.8),target:at(42.32915,-83.0397,2.2)},
 guardian:{pos:at(42.3328,-83.0510,6.8),target:at(42.3296,-83.0464,2.0)},
 wilson:{pos:at(42.3266,-83.0656,7),target:at(42.32198,-83.06225,.24)},
 milliken:{pos:at(42.3368,-83.0292,6),target:at(42.33203,-83.02703,.22)},
 valade:{pos:at(42.3393,-83.0208,5.5),target:at(42.33503,-83.01880,.22)},
 bridges:{pos:at(42.324,-83.115,25),target:at(42.302,-83.087,1.25)},
 ambassador:{pos:at(42.322,-83.083,10),target:at(42.31210,-83.07405,1.6)},
 gordie:{pos:at(42.3025,-83.113,14),target:at(42.28850,-83.09780,2.25)},
 macarthur:{pos:at(42.351,-83.010,10),target:at(42.34254,-82.998585,.65)},
 belle:{pos:at(42.350,-82.991,19),target:at(42.342,-82.978,1)}
};const p=presets[which]||presets.waterfront;controls.target.set(...p.target);camera.position.set(...p.pos);controls.maxPolarAngle=which==='street'?1.59:1.53;controls.update();if(['gordie','ambassador','macarthur'].includes(which)){const b=BRIDGE_REGISTRY.find(item=>item.id===which);if(b){const state=bridgeState(which,settings.year);get('feature-name').textContent=b.name;get('feature-desc').textContent=state==='absent'?`Not constructed in ${settings.year}. Opened ${b.openYear}. ${b.note}`:state==='construction'?`2024: bridge deck connected, but NOT yet open to public. ${b.note}`:`${b.note} Approximate georeferenced engineering-style massing; not a certified BIM survey.`;}}for(const b of document.querySelectorAll('[data-camera]'))b.classList.toggle('active',b.dataset.camera===which);
}
function releaseCity(){if(city){removeDetroitBridgeNetwork(city.group,bridgeLayer);destroyGeoCity(scene,city);}bridgeLayer=null;city=null;}
function changeYear(y){const era=pack.eras.find(e=>e.year===Number(y));if(!era)return;settings.year=era.year;get('era').value=String(era.year);releaseCity();city=createGeoCity(scene,era.year,pack,settings,regions,islandData,riverData,historicPack,localEdits);bridgeLayer=addDetroitBridgeNetwork(city.group,era.year,settings.quality);city.bridgeCount=bridgeLayer.count;city.bridgeMetrics=bridgeLayer.metrics;city.group.traverse(o=>{if(o.isSprite&&/^(Ambassador Bridge|Gordie Howe International Bridge|MacArthur Bridge — Belle Isle)$/.test(o.userData?.feature?.name||''))o.visible=false;});loadLocalModels(city.group,era.year).catch(console.warn);get('era-summary').textContent=era.description;get('hero-title').innerHTML=era.year===2045?'Detroit, beyond<br>tomorrow.':era.year<=1805?'Detroit at the<br>beginning of an era.':'Detroit, through<br>the generations.';get('feature-name').textContent=era.headline||era.label;get('feature-desc').textContent=(era.year===2045?'2045 IS THE ONLY FUTURE-INSPIRED ERA. ':era.year<2024?'HISTORICAL COASTLINE AND CITYWIDE FABRIC INCOMPLETE. Source-dated landmark massing is approximate. ':'Mapped 2024 Detroit footprints + mapped older Detroit street centerlines. Not a certified 2026 survey. ')+(era.description||'');
get('geo-flag').textContent=era.year<2024?`HISTORICAL GEOMETRY INCOMPLETE · ${city.landmarkCount} dated anchors`:`${city.buildingCount} GIS buildings · ${city.roadCount} mapped roads · MAPPED DETROIT RIVER (${city.waterDataCount} sources) · ${city.windowCount} facade windows · Belle Isle ${city.belleIslandVerified?'mapped land boundary':'outline UNVERIFIED'}`;
if(era.year>=2024&&mapMeta?.missing_layers?.length)get('geo-flag').textContent+=' · LEGACY DATA GAPS: '+mapMeta.missing_layers.join(', ');
get('scene-disclosure').textContent=era.year<2024?'DATED HISTORICAL LANDMARK MASSING ONLY · archive shoreline and citywide footprints not yet georeferenced':(!city.riverVerified||city.waterCount===0)?'WATER NOT VERIFIED — check river source and geometry':city.belleIslandVerified?`Mapped river source: ${city.riverSource} · Belle Isle park land · GIS buildings`:'RIVER COVERAGE WARNING / BELLE ISLE OUTLINE NOT VERIFIED';
if(era.year>=2024 && (!city.riverVerified || city.waterCount===0)){get('geo-flag').textContent+=' · WATER RENDER WARNING';console.error('Geo v2.0.20: river raster coverage sample did not pass; inspect source wet/dry classification');}
if(city.landCorrections)get('geo-flag').textContent+=` · GIS LAND GUARD ${city.landCorrections.submergedBuildingsBeforeCorrection} flooded buildings flagged · ${city.landCorrections.guardedAnchors} dry anchors`;
get('bridge-state').textContent=bridgeLayer.metrics.length?bridgeLayer.metrics.map(b=>`${b.name.replace(' — Belle Isle','')}: ${b.state==='construction'?'2024 CONSTRUCTION':b.state==='open'?'OPEN':'NOT BUILT'}`).join(' · '):'No present-day crossings constructed in selected era';
get('geo-flag').textContent+=` · BRIDGES ${bridgeLayer.count}`;
get('geo-flag').textContent+=` · DOCUMENTED MASSING ${city?.historicMassingCount??0} · LOCAL EDITS ${city?.localEditCount??0} · GIS STREET DETAIL ${city?.streetDetailCount??0}`;get('geo-flag').textContent+=` · GEO WATER MASK ${city.waterMaskSize||'?'}`;if(city.waterCrossSections?.downtown)get('geo-flag').textContent+=` · Downtown wet width ${city.waterCrossSections.downtown.longestWaterWidthMeters}m`;
const here=new URL(location.href);here.searchParams.set('era',String(era.year));history.replaceState(null,'',here.pathname+here.search);
selected=null;if(citizens)citizens.setEnabled(settings.year>=2024);}
function selectObject(obj){while(obj&&!obj.userData?.feature)obj=obj.parent;if(!obj?.userData?.feature)return;const f=obj.userData.feature;get('feature-name').textContent=f.name;get('feature-desc').textContent=(f.location_certainty||'Mapped marker')+' · Active '+f.start+'–'+f.end+'.';if(f.source){const link=document.createElement('a');link.textContent='Explore historical reference ↗';link.href=f.source;link.target='_blank';link.rel='noopener noreferrer';link.style.cssText='display:block;color:#e4b779;margin-top:15px';get('feature-desc').appendChild(link);}selected=f;}
async function start(){bootStage('Loading historical era records...');const response=await geoFetch('./packs/detroit/eras.json');if(!response.ok)throw Error('Cannot read historical era pack: '+response.status);pack=await response.json();if(!Array.isArray(pack.eras)||pack.eras.length!==14||!Array.isArray(pack.features))throw Error('Unexpected era pack format');
bootStage('Loading source-backed historical landmark registry...');const historyResult=await geoFetch('./packs/detroit/historic-waterfront.json?v=216');historicPack=await historyResult.json();if(historicPack.schema!=='agentopia.detroit.historic-waterfront.v1'||!Array.isArray(historicPack.landmarks))throw Error('Historical registry invalid');localEdits=loadLocalEdits();
bootStage('Loading Detroit GIS building footprints and roads (three regions)...');const areas=['west_bridges','downtown','belle_isle'];regions=await Promise.all(areas.map(async area=>{const r=await geoFetch('./data/'+area+'.json');if(!r.ok)throw Error('Missing real Detroit map dataset '+area+'. Run the geography installer: HTTP '+r.status);const d=await r.json();bootStage('Loaded GIS region '+area+' ('+(d.buildings?.length||0)+' buildings)');if(d.schema!=='agentopia.detroit.geo.v1'||!Array.isArray(d.buildings)||!Array.isArray(d.roads))throw Error('Corrupt Detroit GIS region '+area);return d;}));try{const pr=await fetch('./data/provenance.json',{cache:'no-store'});if(pr.ok)mapMeta=await pr.json();}
catch(e){console.warn('No geographic provenance',e)}
bootStage('Loading Belle Isle park geometry...');try{const ir=await geoFetch('./data/belle_isle_park.json');if(ir.ok){const d=await ir.json();if(d?.schema==='agentopia.detroit.park.v1'&&Array.isArray(d.rings))islandData=d;}}catch(e){console.warn('Independent Belle Isle boundary unavailable',e)}

bootStage('Loading validated Detroit River polygons...');const rr=await geoFetch('./data/river_verified_v209.json');
if(rr.ok){const data=await rr.json();if(data.schema==='agentopia.detroit.river.v209'&&data.qa?.passed===true&&Array.isArray(data.polygons)){riverData=data;console.info('Verified Detroit River source',data.source_name,data.qa);}else throw Error('River v209 data corrupted or missing QA pass');}
else throw Error('Verified Detroit River file missing. Run the v2.0.9 standalone river installer. HTTP '+rr.status);

const missing=Array.isArray(mapMeta?.missing_layers)?mapMeta.missing_layers:[];
if(missing.length){console.warn('Mapped data unavailable:',missing.join(', '));}
const gpuParam=query.get('gpu');const forceWebGL=gpuParam!=='webgpu'; // Mac safety: proven functional WebGL2 unless explicitly opt-in to WebGPU
bootStage('Initializing '+(forceWebGL?'WebGL 2':'WebGPU')+' graphics backend...');renderer=new T.WebGPURenderer({canvas,antialias:true,alpha:false,forceWebGL,powerPreference:'high-performance'});
renderer.outputColorSpace=T.SRGBColorSpace;renderer.toneMapping=T.ACESFilmicToneMapping;renderer.shadowMap.enabled=true;renderer.shadowMap.type=T.PCFSoftShadowMap;
await renderer.init();bootStage('GPU ready. Building mapped Detroit city and corrected shoreline...');const backend=renderer.backend?.isWebGPUBackend?'WebGPU opt-in':renderer.backend?.isWebGLBackend?'WebGL 2 · safe default':'Renderer backend unknown';get('backend').textContent=backend;get('renderer-chip').textContent='◉ '+backend.toUpperCase();
scene=new T.Scene();scene.background=new T.Color(0x9eb9c7);scene.fog=new T.FogExp2(0x9db9c5,.00042);
camera=new T.PerspectiveCamera(42,1,.06,1600);camera.position.set(0,72,-132);
controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.08;controls.minDistance=.4;controls.maxDistance=520;controls.maxPolarAngle=1.53;controls.target.set(0,1.55,14);controls.update();
hemi=new T.HemisphereLight(0xfff5e4,0x2c4856,.9);scene.add(hemi);
light=new T.DirectionalLight(0xffe8bb,2.8);light.castShadow=true;light.shadow.mapSize.set(2048,2048);light.shadow.camera.left=-220;light.shadow.camera.right=220;light.shadow.camera.top=220;light.shadow.camera.bottom=-220;light.shadow.camera.near=1;light.shadow.camera.far=240;light.shadow.bias=-.00015;light.shadow.normalBias=.025;scene.add(light);
const extra=new T.DirectionalLight(0x7fa3b8,.36);extra.position.set(32,34,50);scene.add(extra);
lightScene();await yieldToBrowser();let wanted=pack.eras.some(e=>e.year===settings.year)?settings.year:2026;get('era').replaceChildren(...pack.eras.map(era=>{const e=document.createElement('option');e.value=era.year;e.textContent=`${era.year} · ${era.label}`;return e;}));
changeYear(wanted);bootStage('Mapped city ready. Starting controls and render loop...');await yieldToBrowser();setPreset(['bridges','gordie','ambassador','macarthur','waterfront','aerial','guardian','street','belle','wilson','milliken','valade','landmark'].includes(query.get('view'))?query.get('view'):'waterfront',true);
// One city, one screen. Editor changes directly rebuild the GIS-based 3D viewer.
cityEditor=initInlineEditor({onCommit:edits=>{localEdits=edits;changeYear(settings.year);}});
if(query.get('edit')==='1')cityEditor.open();
function inspectCitizen(a){
  get('feature-name').textContent=a.name;
  get('feature-desc').textContent=`${a.job} | ${a.activity || 'No recorded activity'} | ${a.location} | ${a.activityTime} | ${a.accuracy}. Movement visualization is illustrative, not a GPS trace.`;
  get('resident-focus').textContent='Follow '+a.name;
  get('resident-focus').disabled=false;
  get('resident-focus').onclick=()=>focusCitizen(a.name);
}
function focusCitizen(name){
  const a=citizens?.choose(name);if(!a)return;
  controls.target.set(a.x,.26,a.z);camera.position.set(a.x+.7,.98,a.z+1.1);controls.update();
}
function renderLiveStatus(data){
  const chip=get('society-state'),details=get('society-detail'),list=get('resident-list');
  const sourceAge=data.age!=null?` | Last snapshot ${data.age}s ago`:'';
  chip.textContent=data.ok?`LIVE ${data.shown} RESIDENTS`:(data.lastError?'OBSERVER UNAVAILABLE':'CONNECTING...');
  chip.dataset.live=data.ok?'yes':'no';
  details.textContent=(data.ok?`${data.clock} | ${data.engine} | ${data.shown} displayed / ${data.total} recorded`:`${data.lastError||'Connecting to /api/snapshot'}${sourceAge}`)
    +` | Visual era ${settings.year}; resident simulation clock above. Positions inferred unless GPS supplied.`;
  list.replaceChildren();
  for(const a of data.people||[]){
    const b=document.createElement('button');b.type='button';b.className='resident-row';
    const n=document.createElement('strong');n.textContent=a.name;
    const sub=document.createElement('small');sub.textContent=(a.activity||a.location).slice(0,88);
    b.append(n,sub);b.addEventListener('click',()=>focusCitizen(a.name));list.append(b);
  }
}
citizens=createLiveCitizens(scene,regions,{onUpdate:renderLiveStatus,onInspect:inspectCitizen});
citizens.setEnabled(settings.year>=2024);citizens.start();
get('live-population').addEventListener('click',()=>{if(settings.year<2024)changeYear(2045);citizens.setEnabled(true);get('resident-list').scrollIntoView({block:'nearest',behavior:'smooth'});});
get('follow-life').addEventListener('click',()=>{if(settings.year<2024)changeYear(2045);const moving=citizens?.getRecords().find(p=>p.movement)||citizens?.getRecords()[0];if(moving)focusCitizen(moving.name);});
function resize(){const width=canvas.clientWidth,height=canvas.clientHeight;if(!width||!height)return;renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();}
new ResizeObserver(resize).observe(canvas);
function quality(){const pixel=window.devicePixelRatio||1;renderer.setPixelRatio(Math.min(pixel,settings.quality==='high'?2:settings.quality==='medium'?1.4:1));light.shadow.mapSize.set(settings.quality==='high'?2048:settings.quality==='medium'?1024:512,settings.quality==='high'?2048:settings.quality==='medium'?1024:512);light.shadow.map?.dispose?.();resize();}
quality();get('loading').classList.add('hidden');document.dispatchEvent(new Event('agentopia:ready'));bootStage('Render loop active. Total startup '+Math.round(performance.now()-bootStart)+'ms');get('quality').value=settings.quality;
get('era').onchange=e=>changeYear(Number(e.target.value));get('season').onchange=e=>{settings.season=e.target.value;changeYear(settings.year)};
get('light').onchange=e=>{settings.light=e.target.value;lightScene();changeYear(settings.year)};
get('quality').onchange=e=>{settings.quality=e.target.value;quality();changeYear(settings.year);};
for(const b of document.querySelectorAll('[data-camera]'))b.addEventListener('click',()=>setPreset(b.dataset.camera));
const ray=new T.Raycaster(),mouse=new T.Vector2();let startXY=null;
canvas.addEventListener('pointerdown',e=>{startXY=[e.clientX,e.clientY]});canvas.addEventListener('pointerup',e=>{if(!startXY||Math.hypot(e.clientX-startXY[0],e.clientY-startXY[1])>5||e.button!==0)return;const rect=canvas.getBoundingClientRect();mouse.x=(e.clientX-rect.left)/rect.width*2-1;mouse.y=-(e.clientY-rect.top)/rect.height*2+1;ray.setFromCamera(mouse,camera);if(cityEditor?.isPlacing()){
   const world=new T.Vector3();const terrain=new T.Plane(new T.Vector3(0,1,0),-.19);
   if(ray.ray.intersectPlane(terrain,world)){cityEditor.mapPick(world);return;}
 }
 const hits=ray.intersectObjects([...city.group.children,...(citizens?.group.children||[])],true);
 for(const hit of hits){if(citizens?.inspectHit(hit))return;}
 const pick=hits.find(hit=>{let o=hit.object;while(o){if(o.userData?.feature)return true;o=o.parent}return false;});if(pick)selectObject(pick.object)});
monitorHealth(({ok,latency,body,error})=>{get('link-led').classList.toggle('connected',ok);get('observer-status').textContent=ok?'Observer healthy':'Observer unavailable';get('health').textContent=ok?`HTTP GET /api/health · ${latency} ms`:'Offline: '+error; if(ok){const c=body?.world_time||body?.time||body?.checkpoint;if(typeof c==='string')get('checkpoint').textContent=c;}});
let t0=performance.now(),frames=0,samples=[];renderer.setAnimationLoop(()=>{try{controls.update();citizens?.tick(performance.now(),camera);renderer.render(scene,camera);frames++;const t=performance.now();if(t-t0>1150){const fps=Math.round(frames*1000/(t-t0));get('fps').textContent=fps+' FPS';const info=renderer.info;get('metrics').textContent=`Frames/s: ${fps}\nDraw calls: ${info?.render?.calls??'—'}\nTriangles: ${info?.render?.triangles??'—'}\nMemory: GPU telemetry not exposed by browser\nScene era: ${settings.year}\nMapped buildings: ${city?.buildingCount??0}\nMapped road features: ${city?.roadCount??0}\nVisible asphalt segments: ${city?.roadSurfaceCount??0}\nRoad segments excluded beneath water: ${city?.roadWaterSkipped??0}\nRiverwalk promenade segments: ${city?.promenadeSegments??0}\nWater surfaces: ${city?.waterCount??0}/${city?.waterDataCount??0}\nSubmerged buildings (before land guard): ${city?.landCorrections?.submergedBuildingsBeforeCorrection??'—'}\nRiverfront site anchors: ${city?.waterfrontAnchors??0}\nLive citizen figures: ${citizens?.status().recordCount??0}\nBridge structures: ${city?.bridgeCount??0}\nCable-stay / hanger count: ${city?.bridgeMetrics?.reduce((n,b)=>n+(b.cables||0),0)??0}\nConcrete bridge arches: ${city?.bridgeMetrics?.reduce((n,b)=>n+(b.arches||0),0)??0}\nHistoric massing models: ${city?.historicMassingCount??0}\nLocal City Builder edits: ${city?.localEditCount??0}\nRiver source: ${city?.riverSource??'UNAVAILABLE'}\nBelle Isle outline verified: ${city?.belleIslandVerified??false}\nWindow instances: ${city?.windowCount??0}\nRoof accents: ${city?.roofCount??0}\nFacade trim: ${city?.trimCount??0}\nLandmark anchors: ${city?.landmarkCount??0}`;frames=0;t0=t}}catch(e){renderer.setAnimationLoop(null);showError(e)}});
}
start().catch(showError);
