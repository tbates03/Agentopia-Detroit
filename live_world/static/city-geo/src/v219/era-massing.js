/* Source-informed historic massing, NOT surveyed footprints or licensed replicas.
 * Documentary status: anchored dated features; geometry is explicitly approximate.
 * 2045 is the only imaginative future construction era.
 */
import * as T from 'three/webgpu';
import {xy} from './geography.js';
import {activeLandmarks} from './historic-logic.js';
const M=1/32;
const SITES=[
 {id:'penobscot',lat:42.3305,lon:-83.0472,radius:20,from:1905,through:2045},
 {id:'guardian',lat:42.3296,lon:-83.0464,radius:23,from:1929,through:2045},
 {id:'veterans',lat:42.3260,lon:-83.0496,radius:19,from:1950,through:2045},
 {id:'municipal',lat:42.3277,lon:-83.0450,radius:32,from:1955,through:2045},
 {id:'ford',lat:42.3260,lon:-83.0420,radius:26,from:1956,through:2010},
 {id:'rencen',lat:42.32915,lon:-83.0397,radius:74,from:1976,through:2045}
];
function metersBetween(lat1,lon1,lat2,lon2){return Math.hypot((lat2-lat1)*111195,(lon2-lon1)*111195*Math.cos(lat1*Math.PI/180));}
export function landmarkExclusion(points,year){if(year<2024||!Array.isArray(points)||points.length<3)return false;let lon=0,lat=0,n=0;
 for(const p of points){if(!Array.isArray(p)||!Number.isFinite(+p[0])||!Number.isFinite(+p[1]))continue;lon+=+p[0];lat+=+p[1];n++;}
 if(!n)return false;lat/=n;lon/=n;return SITES.some(s=>year>=s.from&&year<=s.through&&metersBetween(lat,lon,s.lat,s.lon)<s.radius);
}
const materials={
  guardian:new T.MeshStandardMaterial({color:0xb86a3c,roughness:.88,metalness:.08}),
  guardianTrim:new T.MeshStandardMaterial({color:0x1c686d,roughness:.65,metalness:.35}),
  limestone:new T.MeshStandardMaterial({color:0xd0c9b4,roughness:.9}),
  white:new T.MeshStandardMaterial({color:0xdfdcd0,roughness:.85}),
  midnight:new T.MeshStandardMaterial({color:0x24333b,metalness:.28,roughness:.4}),
  glass:new T.MeshPhysicalMaterial({color:0x628fa1,metalness:.35,roughness:.21,clearcoat:.72}),
  steel:new T.MeshStandardMaterial({color:0x79939e,roughness:.43,metalness:.68}),
  plaza:new T.MeshStandardMaterial({color:0xbab8ab,roughness:1}),
  window:new T.MeshStandardMaterial({color:0x283a43,roughness:.42,metalness:.18})
};
function box(parent,name,w,h,d,px,py,pz,material){const mesh=new T.Mesh(new T.BoxGeometry(w,h,d),material);mesh.position.set(px,py,pz);mesh.name=name;mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;}
function cyl(parent,name,top,bottom,h,x,y,z,material,segments=24){const mesh=new T.Mesh(new T.CylinderGeometry(top,bottom,h,segments),material);mesh.position.set(x,y,z);mesh.name=name;mesh.castShadow=true;mesh.receiveShadow=true;parent.add(mesh);return mesh;}
function bands(parent,w,d,y1,y2,n,mat){for(let i=0;i<n;i++){const y=y1+(y2-y1)*(i+.5)/n;box(parent,'Documented-style facade band',w+.025,.012,d+.025,0,y,0,mat);}}
function fins(parent,r,h,segments,material,x=0,z=0){const obj=new T.InstancedMesh(new T.BoxGeometry(.014,h,.026),material,segments);const m=new T.Matrix4();for(let k=0;k<segments;k++){const a=2*Math.PI*k/segments;const px=x+Math.cos(a)*r,pz=z+Math.sin(a)*r;m.makeRotationY(-a);m.setPosition(px,h/2,pz);obj.setMatrixAt(k,m);}obj.instanceMatrix.needsUpdate=true;obj.name='Facade vertical mullions - reference-based detail';parent.add(obj);}
function makeGuardian(g,h){const t=materials.guardian,trim=materials.guardianTrim,w=1.25,d=.80;box(g,'Guardian granite podium',1.55,.32,1.02,0,.16,0,materials.limestone);
 box(g,'Guardian orange-tan brick body',w,h-.66,d,0,(h-.66)/2+.31,0,t);
 box(g,'Guardian Art Deco setback',1.05,.27,.68,0,h-.51,0,t);
 box(g,'Guardian stepped crown',.72,.22,.50,0,h-.29,0,t);
 box(g,'Guardian ornate crown band',.78,.065,.55,0,h-.18,0,trim);
 for(let i=0;i<26;i++){const y=.46+i*(h-1)/26;for(const xx of [-.43,-.22,0,.22,.43])box(g,'Guardian window rhythm',.07,.062,.014,xx,y,d/2+.013,materials.window);}
 for(const z of [-.28,.28]){box(g,'Guardian exterior corner pilaster',.055,h-.5,.055,-w/2+.02,(h-.5)/2+.30,z,trim);box(g,'Guardian exterior corner pilaster',.055,h-.5,.055,w/2-.02,(h-.5)/2+.30,z,trim);}
}
function makePenobscot(g,year,h){let floorRatio=year<1916?13/47:year<1928?24/47:1;const H=h*floorRatio;
 box(g,'Penobscot limestone shaft',1.12,H*.84,.90,0,H*.42,0,materials.limestone);
 for(let j=0;j<5;j++){const scale=1-j*.1;box(g,'Penobscot stepped tower crown',1.14*scale,H*.035,.92*scale,0,H*.84+j*H*.035,0,materials.limestone);}
 bands(g,1.12,.9,.17,H*.82,Math.max(8,Math.round(floorRatio*32)),materials.white);
 if(year>=1928){cyl(g,'Penobscot aviation beacon',.04,.075,.11,0,H+.02,0,materials.guardianTrim,12);}
}
function makeMunicipal(g){box(g,'Courts Tower',1.05,96.6*M,.55,-.44,(96.6*M)/2,0,materials.white);
 box(g,'Administration Tower',1.52,60*M,.78,.68,(60*M)/2,-.03,materials.white);
 box(g,'Civic Center glass entrance link',.65,.33,.78,.1,.18,.01,materials.glass);
 for(let i=0;i<17;i++){const y=.24+i*.135;box(g,'City-County courthouse facade grid',.065,.045,.02,-.83,y,.29,materials.midnight);}
}
function makeRencen(g,year){const hotel=221.5*M,offices=159*M,secondary=103*M;
 // Original five-tower core: documented arrangement; spacing approximate.
 cyl(g,'Detroit Marriott 73-story central hotel',.45,.49,hotel,0,hotel/2,0,materials.glass,40);
 const a=[[.90,.64],[-.90,.64],[.90,-.64],[-.90,-.64]];
 for(const [x,z] of a){cyl(g,'Renaissance Center 39-story office tower',.32,.34,offices,x,offices/2,z,materials.glass,28);fins(g,.335,offices,20,materials.steel,x,z);}
 fins(g,.47,hotel,36,materials.steel);
 box(g,'Renaissance Center podium',2.65,.37,2.25,0,.19,0,materials.midnight);
 if(year>=1981){for(const z of [-.43,.43]){cyl(g,'Renaissance Center 1981 eastern office tower',.29,.30,secondary,2.25,secondary/2,z,materials.glass,28);fins(g,.298,secondary,18,materials.steel,2.25,z);}}
}
function makeFord(g){box(g,'Ford Auditorium white marble walls',1.62,.56,1.04,0,.28,0,materials.white);
 box(g,'Ford Auditorium dark granite west facade',1.44,.32,.025,0,.26,.535,materials.midnight);
 box(g,'Ford Auditorium flat roof',1.73,.048,1.14,0,.59,0,materials.white);
}
function makeVeterans(g){box(g,'Veterans Memorial 1950 main civic mass',.85,1.02,.75,0,.51,0,materials.white);
 for(let i=-3;i<=3;i++)box(g,'Veterans Memorial facade vertical relief',.045,.82,.025,i*.102,.53,.39,materials.midnight);
}
function makeHart(g){box(g,'Hart Plaza — open hardscape reference footprint',1.8,.035,1.25,0,.06,0,materials.plaza);
 const ring=new T.Mesh(new T.TorusGeometry(.19,.038,8,36),materials.white);ring.rotation.x=Math.PI/2;ring.position.set(.16,.11,-.06);ring.name='Horace E Dodge fountain - symbolic, date approximate';g.add(ring);
}
export function addEraMassing(group,pack,year,quality='high'){
 if(!pack||pack.schema!=='agentopia.detroit.historic-waterfront.v1')return 0;
 let n=0;
 for(const v of activeLandmarks(pack,year)){
 const [x,z]=xy(v.lat,v.lon);const g=new T.Group();g.position.set(x,.14,z);g.name=`SOURCE-INFORMED approximate massing: ${v.name}`;
 g.userData.feature={name:v.name,start:v.from,end:v.through,source:v.source,location_certainty:'SOURCE-DATED MASSING ONLY. Site center and form simplified; not a certified architectural replica. '+v.notes};
 if(v.model==='guardian')makeGuardian(g,(v.height_m||151)*M);
 else if(v.model==='penobscot')makePenobscot(g,year,(v.height_m||173)*M);
 else if(v.model==='rencen')makeRencen(g,year);
 else if(v.model==='municipal')makeMunicipal(g);
 else if(v.model==='veterans')makeVeterans(g);
 else if(v.model==='ford')makeFord(g);
 else if(v.model==='hart')makeHart(g);
 else continue;
 group.add(g);n++;
 }
 return n;
}
export function addLocalAnnotations(group,features,year){if(!Array.isArray(features))return 0;let count=0;
 const mat=new T.MeshStandardMaterial({color:0xffd16d,roughness:.7});group.userData.cityBuilderMaterial=mat;
 for(const f of features){if(f.start>year||f.end<year)continue;if(!['landmark','park','shore_dry','shore_wet'].includes(f.type))continue;
 const [x,z]=xy(f.lat,f.lon);const pin=cyl(group,'City Builder local annotation',.075,.07,.22,x,.40,z,mat,12);
 pin.userData.feature={name:f.name,start:f.start,end:f.end,source:f.source,location_certainty:'Locally edited (NOT independently validated). '+(f.notes||'')};count++;}
 return count;
}
