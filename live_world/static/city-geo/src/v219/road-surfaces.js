/* v2.0.18: make real Detroit GIS streets VISIBLE. The v217 strip triangles faced
 * DOWN and were back-face culled. This road renderer uses +Y-facing quads,
 * sidewalks and visible asphalt. Water-covered streets are omitted except
 * explicitly mapped bridges. Existing GIS centerlines remain authoritative.
 */
import * as T from 'three/webgpu';
import {xy} from './geography.js';
import {widthForRoad,buildUpwardQuad,shouldSkipRoad} from './road-logic.js';
const toScene=p=>xy(p[1],p[0]);
const isWalk=t=>['pedestrian','footway','path','cycleway'].includes(String(t));
function addLayer(group,name,vertices,material,renderOrder){
 if(vertices.length===0)return;
 const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(vertices,3));
 // Materials reuse existing asphalt/stone texture maps. Without UVs a mapped
 // road can sample a single dark texel or fail on some WebGPU backends.
 const uvs=[];for(let k=0;k<vertices.length;k+=3)uvs.push(vertices[k]*.34,vertices[k+2]*.34);
 g.setAttribute('uv',new T.Float32BufferAttribute(uvs,2));g.computeVertexNormals();
 const o=new T.Mesh(g,material);o.name=name;o.receiveShadow=true;o.renderOrder=renderOrder;
 group.add(o);
}
export function drawVisibleMappedRoads(group,regions,materials,isWet){
 const asphalt=[],sidewalks=[],bridgeDecks=[],pedestrian=[];
 const stats={features:0,segments:0,bridges:0,skippedWater:0,sidewalks:0};
 for(const region of regions||[])for(const road of region.roads||[]){
  if(!Array.isArray(road.p)||road.p.length<2)continue;
  const t=String(road.t||''),width=widthForRoad(t),walk=isWalk(t),bridge=Boolean(road.bridge),tunnel=Boolean(road.tunnel);
  if(tunnel)continue;
  stats.features++;
  for(let i=1;i<road.p.length;i++){
   const a=road.p[i-1],b=road.p[i];
   if(!Array.isArray(a)||!Array.isArray(b)||!Number.isFinite(+a[0])||!Number.isFinite(+a[1])||!Number.isFinite(+b[0])||!Number.isFinite(+b[1]))continue;
   const A=toScene(a),B=toScene(b),mid=[(A[0]+B[0])/2,(A[1]+B[1])/2];
   if(shouldSkipRoad(bridge,tunnel,mid,isWet)){stats.skippedWater++;continue;}
   const y=bridge?.37:.187;
   const inner=buildUpwardQuad(A,B,width,y);
   if(!inner)continue;
   const shoulder=buildUpwardQuad(A,B,width+(walk?.05:.14),y-.012);
   if(shoulder){sidewalks.push(...shoulder);stats.sidewalks++;}
   if(bridge){bridgeDecks.push(...inner);stats.bridges++;}
   else if(walk)pedestrian.push(...inner);
   else asphalt.push(...inner);
   stats.segments++;
  }
 }
 // Materials include local texture maps and are reused from the main city.
 materials.asphalt.side=T.DoubleSide;materials.sidewalk.side=T.DoubleSide;
 addLayer(group,'REAL GIS STREET SIDEWALKS + CURBS',sidewalks,materials.sidewalk,7);
 addLayer(group,'REAL GIS STREET ASPHALT — upward-facing visible surfaces',asphalt,materials.asphalt,8);
 addLayer(group,'Mapped bridges, above Detroit River',bridgeDecks,materials.steelDark,8);
 addLayer(group,'GIS pedestrian ways / Riverwalk approaches',pedestrian,materials.concrete,8);
 return stats;
}
