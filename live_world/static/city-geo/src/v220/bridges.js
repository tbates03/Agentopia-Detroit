/* Integrated 3D Detroit bridges — structural types & placed alignments.
 * Data: bridge-data.js. All geometric detail is source-informed massing,
 * NOT scanned CAD/BIM or measured survey. The world engine remains untouched.
 */
import * as T from 'three/webgpu';
import {xy,METERS_PER_UNIT} from '../v219/geography.js';
import {BRIDGE_REGISTRY,bridgeState,bridgesInYear} from './bridge-data.js';
const U=m=>m/METERS_PER_UNIT;
const V=(x,y,z)=>new T.Vector3(x,y,z);

function createMats(){return {
 road:new T.MeshStandardMaterial({color:0x30383e,roughness:.93,metalness:.04,side:T.DoubleSide}),
 cement:new T.MeshStandardMaterial({color:0xb0b6b3,roughness:.91,metalness:.06,side:T.DoubleSide}),
 warmConcrete:new T.MeshStandardMaterial({color:0xaaa99a,roughness:.93,side:T.DoubleSide}),
 steel:new T.MeshStandardMaterial({color:0x7b98a5,metalness:.48,roughness:.48,side:T.DoubleSide}),
 dark:new T.MeshStandardMaterial({color:0x425a65,metalness:.55,roughness:.48,side:T.DoubleSide}),
 silver:new T.MeshStandardMaterial({color:0xd9e7e9,metalness:.48,roughness:.35,side:T.DoubleSide}),
 line:new T.LineBasicMaterial({color:0xdde5e2,transparent:true,opacity:.85,depthWrite:false}),
 suspension:new T.LineBasicMaterial({color:0xf0d8a5,transparent:true,opacity:.92,depthWrite:false}),
 stripe:new T.MeshBasicMaterial({color:0xe9e4cf,side:T.DoubleSide}),
 sidewalk:new T.MeshStandardMaterial({color:0x7b9a8c,roughness:1,side:T.DoubleSide}),
 hazard:new T.MeshBasicMaterial({color:0xe0a04c,side:T.DoubleSide}),
 lamp:new T.MeshBasicMaterial({color:0xffdb87}),
 };}
function box(g,name,w,h,d,x,y,z,material,shadow=false){const a=new T.Mesh(new T.BoxGeometry(w,h,d),material);a.name=name;a.position.set(x,y,z);if(shadow)a.castShadow=true;a.receiveShadow=true;g.add(a);return a;}
function beam(g,name,a,b,r,mat,sides=7){const v1=Array.isArray(a)?V(...a):a,v2=Array.isArray(b)?V(...b):b;const dir=new T.Vector3().subVectors(v2,v1);const len=dir.length();if(len<.002)return null;const ob=new T.Mesh(new T.CylinderGeometry(r,r,len,sides,1),mat);ob.name=name;ob.position.copy(v1).add(v2).multiplyScalar(.5);ob.quaternion.setFromUnitVectors(V(0,1,0),dir.normalize());g.add(ob);return ob;}
function lineGroup(g,name,coords,material){if(!coords.length)return;const geom=new T.BufferGeometry();geom.setAttribute('position',new T.Float32BufferAttribute(coords,3));const lines=new T.LineSegments(geom,material);lines.name=name;g.add(lines);return lines;}
function pointsToLine(array,a,b){array.push(a.x,a.y,a.z,b.x,b.y,b.z);}
function frameFor(b){
 const A=xy(...b.endpoints[0]),B=xy(...b.endpoints[1]);
 const dx=B[0]-A[0],dz=B[1]-A[1],length=Math.hypot(dx,dz);
 const center=V((A[0]+B[0])/2,0,(A[1]+B[1])/2);
 // Rotating local +Z gives the direction from Detroit toward Canada / Belle Isle.
 const angle=Math.atan2(dx,dz);
 return {center,angle,length};
}
function mainDeckHeight(b,s){
 const half=b.reportedLengthM/METERS_PER_UNIT/2;
 const a=Math.min(1,Math.abs(s)/half);
 const maxY=U(b.deckClearanceM)+.04;
 const bankY=b.kind==='open-spandrel-arch'? .185 : .21;
 if(b.kind==='open-spandrel-arch'||b.kind==='historic-truss')return bankY+(maxY-bankY)*(1-Math.pow(a,5));
 const central=Math.min(.88,(b.mainSpanM||b.reportedLengthM)/b.reportedLengthM*.92);
 if(a<=central)return maxY+U(1.2)*(1-a*a);
 const t=Math.min(1,(a-central)/(1-central));return bankY+(maxY-bankY)*(1-t*t*(3-2*t));
}
function deckSurface(g,b,frame,m,state,quality){
 const length=frame.length,half=length/2,spacing=quality==='high'?0.45:quality==='low'?1.2:0.72;
 const n=Math.max(20,Math.ceil(length/spacing)),width=U(b.deckWidthM);
 const verts=[],normals=[],uv=[];
 function triangle(a,c,d){verts.push(...a,...c,...d);}
 for(let i=0;i<n;i++){
  const z0=-half+length*i/n,z1=-half+length*(i+1)/n;
  const y0=mainDeckHeight(b,z0),y1=mainDeckHeight(b,z1);
  // +Y-facing top triangles (same orientation as v219 fixed asphalt).
  triangle([-width/2,y0,z0],[-width/2,y1,z1],[width/2,y0,z0]);
  triangle([width/2,y0,z0],[-width/2,y1,z1],[width/2,y1,z1]);
  const base0=y0-.10,base1=y1-.10;
  triangle([-width/2,base0,z0],[-width/2,y0,z0],[-width/2,base1,z1]);
  triangle([-width/2,y0,z0],[-width/2,y1,z1],[-width/2,base1,z1]);
  triangle([width/2,y0,z0],[width/2,base0,z0],[width/2,base1,z1]);
  triangle([width/2,y0,z0],[width/2,base1,z1],[width/2,y1,z1]);
 }
 const gg=new T.BufferGeometry();gg.setAttribute('position',new T.Float32BufferAttribute(verts,3));gg.computeVertexNormals();
 const mesh=new T.Mesh(gg,m.road);mesh.name='Continuous elevated roadway · georeferenced approximate alignment';mesh.receiveShadow=true;g.add(mesh);
 for(const sign of [-1,1]){
  const x=sign*(width/2+.025);
  const rail=[];
  for(let k=0;k<=n;k++){const z=-half+length*k/n;rail.push(V(x,mainDeckHeight(b,z)+.105,z));}
  const curve=new T.CatmullRomCurve3(rail);const ob=new T.Mesh(new T.TubeGeometry(curve,n,.018,5,false),m.steel);ob.name='Bridge guardrail';g.add(ob);
 }
 // One instanced-mesh for hundreds of lane markings; no per-mark draw calls.
 const lanes=b.lanes||2,dividerCount=Math.max(0,lanes-1),skip=quality==='low'?2:1;
 const count=Math.ceil(n/(skip*2))*dividerCount;
 if(count){const geom=new T.BoxGeometry(.012,.004,.20),ins=new T.InstancedMesh(geom,m.stripe,count);const matrix=new T.Matrix4();let k=0;
 for(let j=0;j<n;j+=skip*2){const z=-half+length*(j+.5)/n,y=mainDeckHeight(b,z)+.007;
  for(let line=1;line<lanes;line++){
   const x=-width/2+(line/lanes)*width;matrix.makeTranslation(x,y,z);ins.setMatrixAt(k++,matrix);
  }
 }ins.count=k;ins.instanceMatrix.needsUpdate=true;ins.name='Bridge road lane markings (instanced)';g.add(ins);}
 if(b.kind==='cable-stayed'){
  // Sidewalk/bike path on one side — physical public multi-use path.
  const walk=new T.Mesh(new T.BoxGeometry(.11,.006,length*.92),m.sidewalk);walk.position.set(width/2-.075,mainDeckHeight(b,0)+.006,0);walk.name='Gordie Howe multi-use path · approximated';
  // A straight unit-length strip cannot follow sloped approach, so only the nearly-level main crossing.
  walk.scale.z=Math.min(1,b.mainSpanM/b.reportedLengthM);g.add(walk);
 }
 return {length,width};
}
function drawSuspension(g,b,frame,m,quality){
 const side=U(b.deckWidthM)/2+.24,mainHalf=U(b.mainSpanM)/2,towerTop=U(b.towerHeightM),deck=mainDeckHeight(b,0),count=quality==='low'?12:quality==='medium'?23:37;
 let cableCount=0;
 function yCable(z){const az=Math.abs(z);if(az<=mainHalf)return towerTop-(towerTop-(deck+.73))*(1-(az/mainHalf)**2);
  const t=(az-mainHalf)/(mainHalf*2.05);return towerTop-Math.min(1,t)*(towerTop-(deck+.10));}
 for(const s of [-1,1]){
  const zz=s*mainHalf;
  for(const x of [-side,side]){
   // Twin steel towers, with open roadway portal through them.
   box(g,'Ambassador trussed steel tower leg',.21,towerTop,.24,x,towerTop/2,zz,m.dark,true);
   box(g,'Ambassador upper tower cap',.31,.14,.31,x,towerTop+.02,zz,m.steel);
  }
  for(const h of [.36*towerTop,.73*towerTop,towerTop*.93]){
   box(g,'Ambassador portal steel crossbeam',2*side+.28,.095,.20,0,h,zz,m.steel);
  }
  // Simple diagonal structural braces between tower legs.
  beam(g,'Ambassador tower lattice bracing',[-side,.42*towerTop,zz],[side,.68*towerTop,zz],.040,m.dark);
 }
 const hangers=[];
 for(const x of [-side,side]){
  const curvePts=[];for(let k=0;k<=64;k++){
   const z=(-mainHalf*2.25)+(mainHalf*4.5)*k/64;curvePts.push(V(x,yCable(z),z));}
  const cable=new T.Mesh(new T.TubeGeometry(new T.CatmullRomCurve3(curvePts),64,.035,7,false),m.silver);cable.name='Ambassador 1929 main suspension cable';g.add(cable);cableCount++;
  for(let i=0;i<=count;i++){const z=-mainHalf+2*mainHalf*i/count;pointsToLine(hangers,V(x,yCable(z),z),V(x,mainDeckHeight(b,z)+.13,z));cableCount++;}
 }
 lineGroup(g,'Ambassador vertical suspension hangers',hangers,m.suspension);
 const truss=[];const half=frame.length/2;for(const x of [-side*.88,side*.88]){
  const n=quality==='low'?20:55;
  for(let i=0;i<n;i++){const z=-half+frame.length*i/n,z2=-half+frame.length*(i+1)/n;
   const y1=mainDeckHeight(b,z)-.095,y2=mainDeckHeight(b,z2)-.095;
   pointsToLine(truss,V(x,y1,z),V(x,y1-.25,z));
   pointsToLine(truss,V(x,y1-.25,z),V(x,y2,z2));
   pointsToLine(truss,V(x,y1,z),V(x,y2-.25,z2));
  }
 }lineGroup(g,'Ambassador steel stiffening trusses',truss,m.line);
 return {cables:cableCount,towers:2,arches:0};
}
function drawCableStayed(g,b,frame,m,state,quality){
 const side=U(b.deckWidthM)/2+.18,spanHalf=U(b.mainSpanM)/2,top=U(b.towerHeightM),anchorGap=spanHalf*.96;
 const cables=[];const stays=b.stayCount||216;const halfCount=stays/8;
 for(const sign of [-1,1]){
  const z0=sign*spanHalf;
  for(const footX of [-side-.17,side+.17]){
   // A-shaped concrete towers, legs part to either side of the roadway.
   beam(g,'Gordie Howe 220m A-pylon leg',[footX,.36,z0],[0,top,z0],.103,m.cement,9);
   box(g,'Gordie Howe pylon base',.25,.46,.36,footX,.24,z0,m.cement);
  }
  box(g,'Gordie Howe A-pylon crossbar',side*1.4,.12,.24,0,top*.61,z0,m.cement);
  // Each tower has fan stay planes on both edges, with inner and outer runs.
  for(const edge of [-1,1]){
   for(let k=1;k<=halfCount;k++){
    const t=k/(halfCount+1);const inward=z0-sign*anchorGap*t;
    const outward=z0+sign*anchorGap*t;
    const mastY=top*(.64+.32*(1-t*.5));
    const head=V(edge*.10,mastY,z0);
    pointsToLine(cables,head,V(edge*side,mainDeckHeight(b,inward)+.1,inward));
    pointsToLine(cables,head,V(edge*side,mainDeckHeight(b,outward)+.1,outward));
   }
  }
 }
 lineGroup(g,'Gordie Howe 216 white cable stays (source count)',cables,m.line);
 // Stronger tubes on widely spaced stays make cables visible at a distance.
 if(quality!=='low'){
  for(let sign of [-1,1])for(const edge of [-1,1])for(let k=2;k<=halfCount;k+=quality==='high'?8:13){
   const t=k/(halfCount+1),z0=sign*spanHalf,far=z0-sign*anchorGap*t;
   beam(g,'Gordie Howe primary stay cable highlight',[edge*.1,top*(.64+.32*(1-t*.5)),z0],[edge*side,mainDeckHeight(b,far)+.1,far],.012,m.silver,5);
  }
 }
 if(state==='construction'){
  // Deck was connected in June 2024, but was NOT open to traffic until 2026.
  for(const at of [-frame.length*.45,-spanHalf*.2,spanHalf*.2,frame.length*.45]){
   box(g,'2024 CONSTRUCTION — NOT OPEN',U(10),.035,.19,0,mainDeckHeight(b,at)+.07,at,m.hazard);
  }
 }
 return {cables:stays,towers:2,arches:0};
}
function drawConcreteArches(g,b,frame,m,quality){
 const span=frame.length/b.spanCount,half=frame.length/2,side=U(b.deckWidthM)/2+.02;
 const n=b.spanCount,curveRes=quality==='low'?5:quality==='high'?16:9;
 for(const x of [-side,side]){
  for(let i=0;i<n;i++){
   const z0=-half+i*span;
   const pts=[];
   for(let p=0;p<=curveRes;p++){
    const t=p/curveRes,z=z0+t*span,deck=mainDeckHeight(b,z);
    // Shallow open-spandrel segmental arches: springline above water, key below deck.
    const y=Math.max(.075,deck-.24)+Math.sin(Math.PI*t)*.14;
    pts.push(V(x,y,z));
   }
   const ar=new T.Mesh(new T.TubeGeometry(new T.CatmullRomCurve3(pts),curveRes,.032,6,false),m.warmConcrete);
   ar.name='MacArthur 1923 concrete open-spandrel arch';g.add(ar);
   const py=mainDeckHeight(b,z0)-.09;
   box(g,'MacArthur arch pier',.12,Math.max(.13,py),.11,x,Math.max(.13,py)/2,z0,m.warmConcrete);
  }
 }
 const posts=Math.max(24,Math.round(frame.length/.35));
 const bar=[];for(const x of [-side,side])for(let i=0;i<=posts;i++){
  const z=-half+frame.length*i/posts,y=mainDeckHeight(b,z);
  pointsToLine(bar,V(x,y,z),V(x,y+.22,z));
  if(i>0){const lastZ=-half+frame.length*(i-1)/posts;
   pointsToLine(bar,V(x,y+.22,z),V(x,mainDeckHeight(b,lastZ)+.22,lastZ));}
 }lineGroup(g,'MacArthur side railings / pedestrian protection',bar,m.line);
 return {cables:0,towers:0,arches:b.spanCount};
}
function drawOriginalBelle(g,b,frame,m){
 const trusses=[],half=frame.length/2,side=U(b.deckWidthM)/2+.10,n=b.spanCount;
 for(const x of [-side,side])for(let i=0;i<n;i++){
  const a=-half+i*frame.length/n,c=-half+(i+1)*frame.length/n,y=mainDeckHeight(b,(a+c)/2);
  pointsToLine(trusses,V(x,y+.03,a),V(x,y+.53,a));
  pointsToLine(trusses,V(x,y+.53,a),V(x,y+.53,c));
  pointsToLine(trusses,V(x,y+.53,a),V(x,y+.03,c));
  pointsToLine(trusses,V(x,y+.03,a),V(x,y+.53,c));
 }
 lineGroup(g,'Original 1889 Belle Isle steel-and-wood bridge (schematic)',trusses,m.suspension);
 return {cables:0,towers:0,arches:0};
}
function makeBridgeGroup(b,year,quality,m){
 const frame=frameFor(b),state=bridgeState(b.id,year),g=new T.Group();
 g.position.copy(frame.center);g.rotation.y=frame.angle;
 g.name='DETROIT BRIDGE · '+b.name+' · '+state;
 g.userData.feature={name:b.name,start:b.started,end:b.ended,source:b.source,
  location_certainty:`${state==='construction'?'Under construction in 2024; not yet open to public. ':'Operational in displayed era. '}${b.note} Geographic alignment and structural massing approximate, not engineering survey.`};
 const deck=deckSurface(g,b,frame,m,state,quality);
 const spec=b.kind==='suspension'?drawSuspension(g,b,frame,m,quality):b.kind==='cable-stayed'?drawCableStayed(g,b,frame,m,state,quality):b.kind==='open-spandrel-arch'?drawConcreteArches(g,b,frame,m,quality):drawOriginalBelle(g,b,frame,m);
 return {group:g,metrics:{id:b.id,name:b.name,state,kind:b.kind,lengthM:Math.round(frame.length*METERS_PER_UNIT),cables:spec.cables,arches:spec.arches,towers:spec.towers,source:b.source}};
}
export function addDetroitBridgeNetwork(cityGroup,year,quality='high'){
 const layer=new T.Group();layer.name='Real Detroit bridge locations — historical era-specific render';
 const mats=createMats(),metrics=[];
 for(const bridge of bridgesInYear(year)){
  const model=makeBridgeGroup(bridge,year,quality,mats);layer.add(model.group);metrics.push(model.metrics);
 }
 cityGroup.add(layer);
 return {group:layer,metrics,count:metrics.length,materials:mats};
}
export function removeDetroitBridgeNetwork(owner,network){if(!network)return;
 owner.remove(network.group);
 network.group.traverse(obj=>{obj.geometry?.dispose?.();});
 for(const mat of Object.values(network.materials))mat.dispose();
}
