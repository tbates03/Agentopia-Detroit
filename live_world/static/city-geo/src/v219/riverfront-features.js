/* Detroit Riverfront Conservancy and Michigan DNR documented modern locations.
 * Real GPS centers, SCALED SYMBOLIC landscaping (not a surveyed footprint).
 * No fabricated architectural or historical replicas; active for documented years.
 */
import * as T from 'three/webgpu';
import {xy,seeded} from './geography.js';
import {DETROIT_SHORE_GUIDE} from './waterfront-land.js';
import {buildUpwardQuad} from './road-logic.js';
export const MODERN_RIVERFRONT=[
 {id:'cullen',name:'Cullen Plaza / carousel node',lat:42.33330,lon:-83.02460,start:2021,source:'https://www.detroitriverfront.org/map',features:'Riverwalk node with carousel plaza and adjacent promenade'},
 {id:'wilson',name:'Ralph C. Wilson Jr. Centennial Park',lat:42.32198,lon:-83.06225,start:2025,source:'https://www.detroitriverfront.org/plan-your-visit/parks-greenways/ralph-c-wilson-jr-centennial-park',features:'22-acre park; Water Garden, DTE Foundation Summit, play garden, Sport House'},
 {id:'milliken',name:'William G. Milliken State Park & Harbor',lat:42.33203,lon:-83.02703,start:2007,source:'https://www.michigan.gov/recsearch/parks/williammilliken',features:'Harbor, berm, picnic landscape, lighthouse'},
 {id:'valade',name:'Robert C. Valade Park',lat:42.33503,lon:-83.01880,start:2019,source:'https://www.detroitriverfront.org/plan-your-visit/parks-greenways/robert-c-valade-park',features:'Beach-inspired park, gathering area and play amenities'},
 {id:'gm',name:'GM Plaza and Riverwalk promenade',lat:42.32805,lon:-83.03891,start:2003,source:'https://www.detroitriverfront.org/map',features:'Promenade near Renaissance Center; GM-donated Riverwalk section'},
 {id:'southwest',name:'Southwest Greenway riverfront connection',lat:42.3230,lon:-83.0610,start:2023,source:'https://www.detroitriverfront.org/plan-your-visit/parks-greenways/southwest-greenway',features:'Greenway between Bagley and Jefferson, connects to Ralph Wilson Park'},
];
const Y=.216;
const discGeometry=(radius=.5,segments=36)=>new T.CircleGeometry(radius,segments);
function disc(group,name,mat,x,z,sx,sz,y=Y){const mesh=new T.Mesh(discGeometry(1,40),mat);mesh.rotation.x=-Math.PI/2;mesh.position.set(x,y,z);mesh.scale.set(sx,sz,1);mesh.receiveShadow=true;mesh.name=name;group.add(mesh);return mesh;}
function path(group,m,pts,width=.09){if(pts.length<2)return;const vertices=[];for(let i=1;i<pts.length;i++){
 const [ax,az]=pts[i-1],[bx,bz]=pts[i],dx=bx-ax,dz=bz-az,len=Math.hypot(dx,dz)||1,ox=dz*width/len/2,oz=-dx*width/len/2;
 vertices.push(ax-ox,Y+.02,az-oz, ax+ox,Y+.02,az+oz,bx+ox,Y+.02,bz+oz,
 ax-ox,Y+.02,az-oz,bx+ox,Y+.02,bz+oz,bx-ox,Y+.02,bz-oz);
 }const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(vertices,3));g.computeVertexNormals();const mesh=new T.Mesh(g,m);mesh.name='Approximate path symbol';group.add(mesh);
}
function trees(group,x,z,n,m,seed){const r=seeded(seed),canopy=new T.InstancedMesh(new T.IcosahedronGeometry(.12,1),m.tree,n),trunk=new T.InstancedMesh(new T.CylinderGeometry(.018,.025,.23,5),m.trunk,n),p=new T.Vector3(),q=new T.Quaternion(),s=new T.Vector3(),mt=new T.Matrix4();for(let i=0;i<n;i++){
 const a=2*Math.PI*i/n+(.13*r()),radius=.37+(.20*r());const xx=x+Math.cos(a)*radius,zz=z+Math.sin(a)*radius;
 mt.compose(p.set(xx,Y+.25,zz),q,s.set(.7+r()*.35,.8+r()*.45,.7+r()*.35));canopy.setMatrixAt(i,mt);
 mt.compose(p.set(xx,Y+.11,zz),q,s.set(1,1,1));trunk.setMatrixAt(i,mt);
 }canopy.instanceMatrix.needsUpdate=true;trunk.instanceMatrix.needsUpdate=true;group.add(canopy,trunk);}
function landmarkPin(group,feature,x,z,materials){const obj=new T.Mesh(new T.CylinderGeometry(.075,.075,.05,12),materials.gold);obj.position.set(x,Y+.10,z);obj.name='Source-backed park point; landscaping is schematic';obj.userData.feature={name:feature.name,start:feature.start,end:2045,source:feature.source,location_certainty:'Sourced location and opening date. Small landscape details are symbolic, not surveyed. '+feature.features};group.add(obj);}
/* The Detroit-side modern Riverwalk is drawn as ONE connected 3D promenade
 * along the SAME visual control points used by the repaired river mask.
 * Control points are documentary place-constrained approximations, not a
 * surveyed seawall. This eliminates detached circles around riverfront towers.
 */
function addContinuousPromenade(group,materials,year,quality){
 if(year<2024)return {segments:0,trees:0};
 const bank=DETROIT_SHORE_GUIDE.filter(p=>p[0]>=-83.0665 && p[0]<=-83.0085);
 const pave=[],quay=[];const trees=[];const rnd=seeded(307216);
 for(let i=1;i<bank.length;i++){
  const left=bank[i-1],right=bank[i];
  const span=Math.hypot(...xy(right[1],right[0]).map((v,j)=>v-xy(left[1],left[0])[j]));
  const steps=Math.max(1,Math.ceil(span/.60));
  for(let j=0;j<steps;j++){
   const t=j/steps,t2=(j+1)/steps;
   const a=[left[0]+(right[0]-left[0])*t,left[1]+(right[1]-left[1])*t];
   const b=[left[0]+(right[0]-left[0])*t2,left[1]+(right[1]-left[1])*t2];
   const A=xy(a[1],a[0]),B=xy(b[1],b[0]);
   // Detroit inland is NORTH (+Z). Paved walk sits on the dry side.
   const qa=buildUpwardQuad([A[0],A[1]+.105],[B[0],B[1]+.105],.20,.222);
   const qb=buildUpwardQuad([A[0],A[1]+.015],[B[0],B[1]+.015],.048,.221);
   if(qa)pave.push(...qa);if(qb)quay.push(...qb);
   const lon=(a[0]+b[0])/2;
   const park=(lon>-83.066&&lon<-83.057)||(lon>-83.029&&lon<-83.024)||(lon>-83.021&&lon<-83.016);
   if(park&&rnd()<.29 && trees.length<350)trees.push([A[0]+(B[0]-A[0])*.5,A[1]+.32+rnd()*.45]);
  }
 }
 const add=(positions,name,material)=>{
  if(!positions.length)return;
  const geo=new T.BufferGeometry();geo.setAttribute('position',new T.Float32BufferAttribute(positions,3));geo.computeVertexNormals();
  const mesh=new T.Mesh(geo,material);mesh.name=name;mesh.receiveShadow=true;mesh.renderOrder=10;group.add(mesh);
 };
 add(pave,'Connected Detroit Riverwalk promenade — inferred alignment',materials.sidewalk);
 add(quay,'Detroit riverside retaining edge / promenade reference',materials.concrete);
 if(trees.length){
  const canopy=new T.InstancedMesh(new T.IcosahedronGeometry(.12,1),materials.tree,trees.length);
  const trunk=new T.InstancedMesh(new T.CylinderGeometry(.014,.025,.22,5),materials.trunk,trees.length);
  const matrix=new T.Matrix4(),v=new T.Vector3(),q=new T.Quaternion(),sc=new T.Vector3();
  trees.forEach(([x,z],i)=>{
   matrix.compose(v.set(x,.41,z),q,sc.set(1.0,.9+rnd()*.4,1.0));canopy.setMatrixAt(i,matrix);
   matrix.compose(v.set(x,.29,z),q,sc.set(1,1,1));trunk.setMatrixAt(i,matrix);
  });
  canopy.instanceMatrix.needsUpdate=true;trunk.instanceMatrix.needsUpdate=true;
  canopy.name='Riverfront park trees inferred from documented park locations';group.add(canopy,trunk);
 }
 return {segments:pave.length/18,trees:trees.length};
}
export function addModernRiverfront(group,materials,year,quality){const stats={anchors:0,amenities:0,promenadeSegments:0,promenadeTrees:0,accuracy:'Geographic center markers verified by Detroit Riverfront Conservancy / Michigan DNR published maps; small landscape symbols approximate, NOT surveyed'};
 if(year<2024)return stats;
 const walk=addContinuousPromenade(group,materials,year,quality);stats.promenadeSegments=walk.segments;stats.promenadeTrees=walk.trees;
 const active=MODERN_RIVERFRONT.filter(f=>year>=f.start),high=quality==='high';
 const parkMat=materials.parks,lightPath=materials.sidewalk,sand=new T.MeshStandardMaterial({color:0xe2c69a,roughness:1}),blue=new T.MeshStandardMaterial({color:0x3c879c,metalness:.12,roughness:.38});
 group.userData.riverfrontPrivateMaterials=[sand,blue];
 for(const f of active){const [x,z]=xy(f.lat,f.lon);landmarkPin(group,f,x,z,materials);stats.anchors++;
  // Preview symbology is intentionally smaller than actual park extents: no
  // 2026 official polygon is claimed when the local cache lacks one.
  if(f.id==='wilson'){
   disc(group,'Wilson Park point-centered green example (non-surveyed)',parkMat,x,z,.7,.54);trees(group,x,z,high?35:16,materials,403);stats.amenities+=3;
   disc(group,'Huron-Clinton Water Garden example — not official shape',blue,x-.22,z+.12,.16,.18,Y+.035);
   disc(group,'DTE Foundation Summit grass symbol',materials.parks,x+.26,z-.06,.20,.15,Y+.045);
   path(group,lightPath,Array.from({length:17},(_,i)=>{let t=i/16;return [x-.65+t*1.3,z-.10+Math.sin(t*Math.PI*2)*.16]}));
   const sport=new T.Mesh(new T.BoxGeometry(.23,.10,.15),materials.steel);sport.position.set(x+.37,Y+.06,z+.24);sport.name='Sport House location symbol — illustrative';group.add(sport);
  }else if(f.id==='cullen'){
   disc(group,'Cullen Plaza riverwalk node marker',materials.concrete,x,z,.20,.16);stats.amenities++;
  }else if(f.id==='milliken'){
   disc(group,'Milliken Park schematic planted berm',parkMat,x,z,.53,.32);trees(group,x,z,high?20:10,materials,404);stats.amenities++;
   const quay=new T.Mesh(new T.BoxGeometry(.45,.06,.13),materials.concrete);quay.position.set(x,Y+.055,z+.32);quay.name='Milliken harbor edge symbol, not measured marina';group.add(quay);
  }else if(f.id==='valade'){
   disc(group,'Valade sandy recreation symbol — not surveyed',sand,x,z,.38,.27);trees(group,x,z,high?13:7,materials,405);stats.amenities++;
  }else if(f.id==='gm'){
   disc(group,'GM Plaza safe-land promenade marker',materials.concrete,x,z,.25,.17);stats.amenities++;
  }else if(f.id==='southwest'){
   disc(group,'Southwest Greenway connection point',parkMat,x,z,.20,.19);stats.amenities++;
  }
 }
 return stats;
}
