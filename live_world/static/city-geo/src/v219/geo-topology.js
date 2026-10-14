/* Pure geographic topology helpers. All sources use GeoJSON [lon,lat] pairs.
 * Converting water features to meshes MUST preserve ring containment and holes;
 * a list of ArcGIS rings is not necessarily one outer and the rest holes.
 */
import {xy} from './geography.js';
export const VIEW_RECT={xmin:-310,xmax:315,zmin:-230,zmax:235};
export function ringArea(p){let s=0;for(let i=0,n=p.length;i<n;i++){const a=p[i],b=p[(i+1)%n];s+=a[0]*b[1]-b[0]*a[1];}return s/2;}
export function inRing(pt,p){let inside=false;for(let i=0,j=p.length-1;i<p.length;j=i++){const a=p[i],b=p[j];if(((a[1]>pt[1])!==(b[1]>pt[1])) && pt[0]<(b[0]-a[0])*(pt[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;}return inside;}
export function pointsFromGPS(gps){const p=[];for(const q of gps||[]){if(!Array.isArray(q)||q.length<2)continue;let v;try{v=xy(q[1],q[0])}catch{continue}if(v.every(Number.isFinite)&&(!p.length||Math.hypot(v[0]-p.at(-1)[0],v[1]-p.at(-1)[1])>.002))p.push(v);}if(p.length>2&&Math.hypot(p[0][0]-p.at(-1)[0],p[0][1]-p.at(-1)[1])<.004)p.pop();return p.length>=3&&Math.abs(ringArea(p))>.0005?p:[];}
export function clipRing(p,rect=VIEW_RECT){let out=p;
 const sides=[['x',rect.xmin,true],['x',rect.xmax,false],['z',rect.zmin,true],['z',rect.zmax,false]];
 for(const [axis,edge,minimum] of sides){const k=axis==='x'?0:1;const result=[];const check=v=>minimum?v[k]>=edge:v[k]<=edge;const intersection=(a,b)=>{const div=b[k]-a[k];const t=Math.abs(div)<1e-12?0:(edge-a[k])/div;return[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]};for(let i=0;i<out.length;i++){const a=out[(i+out.length-1)%out.length],b=out[i];const ia=check(a),ib=check(b);if(ia!==ib)result.push(intersection(a,b));if(ib)result.push(b);}out=result;if(out.length<3)break;}
 const cleaned=[];for(const p of out){if(!cleaned.length||Math.hypot(p[0]-cleaned.at(-1)[0],p[1]-cleaned.at(-1)[1])>.001)cleaned.push(p);}if(cleaned.length>2&&Math.hypot(cleaned[0][0]-cleaned.at(-1)[0],cleaned[0][1]-cleaned.at(-1)[1])<.001)cleaned.pop();return cleaned.length>=3&&Math.abs(ringArea(cleaned))>.002?cleaned:[];
}
/* Returns a list of OUTER rings, each with the holes it immediately owns.
 * Nested rings alternate between water and land according to containment.
 * We only use validated containment, never assume all extra rings are holes.
 */
export function nestedPolygons(lonlatRings){const rings=lonlatRings.map(pointsFromGPS).filter(x=>x.length>=3).sort((a,b)=>Math.abs(ringArea(b))-Math.abs(ringArea(a)));
 const nodes=[];for(const r of rings){let parent=-1;for(let i=0;i<nodes.length;i++){if(Math.abs(ringArea(nodes[i].ring))<=Math.abs(ringArea(r)))continue;if(inRing(r[0],nodes[i].ring)){parent=i;}}nodes.push({ring:r,parent,depth:parent<0?0:nodes[parent].depth+1});}
 return nodes.map((v,i)=>({outer:v.ring,holes:nodes.filter(w=>w.parent===i&&w.depth%2===1).map(w=>w.ring),depth:v.depth})).filter(v=>v.depth%2===0);
}
export const BELLE_ISLE=[...xy(42.3426,-82.9783)];
export function isBelleIsleHole(ring){return inRing(BELLE_ISLE,ring) && Math.abs(ringArea(ring))>2;}
