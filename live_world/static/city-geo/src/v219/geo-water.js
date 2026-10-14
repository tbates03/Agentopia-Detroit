/* Agentopia Detroit v2.0.9: georeferenced GIS water mask.
 * Rasterize the verified source rings directly. Previously nested polygons were
 * separately triangulated/clipped, diverging from the installer wet/dry test.
 * This raster uses Canvas evenodd fill per *original* GIS feature, preserving
 * land holes. No fabricated shoreline, no network dependency at runtime.
 */
import * as T from 'three/webgpu';
import {xy,seeded} from './geography.js';
import {nestedPolygons,clipRing,ringArea,inRing,isBelleIsleHole,VIEW_RECT} from './geo-topology.js';
import {applyWaterfrontCorrections} from './waterfront-land.js';
import {applyLocalMaskEdits} from './city-edits.js';
const WIDTH=2560,HEIGHT=1920;
const RECT=VIEW_RECT;
const PROBES=[
  ['downtown Hart Plaza channel',-83.043,42.322,true],
  ['RenCen channel',-83.039,42.325,true],
  ['Ambassador channel',-83.077,42.308,true],
  ['Belle Isle interior',-82.9783,42.3426,false],
  ['Hart Plaza land',-83.04441,42.32743,false],
  ['Detroit inland land',-83.049,42.336,false]
];
function canvasXY(lon,lat){const [x,z]=xy(lat,lon);return [(x-RECT.xmin)*WIDTH/(RECT.xmax-RECT.xmin),(z-RECT.zmin)*HEIGHT/(RECT.zmax-RECT.zmin)];}
function parkTrees(group,island,mat){const rng=seeded(0xB311E15),pts=[];let xmin=Infinity,xmax=-Infinity,zmin=Infinity,zmax=-Infinity;
  for(const [x,z] of island){xmin=Math.min(xmin,x);xmax=Math.max(xmax,x);zmin=Math.min(zmin,z);zmax=Math.max(zmax,z);}
  for(let i=0;i<24000&&pts.length<550;i++){const x=xmin+(xmax-xmin)*rng(),z=zmin+(zmax-zmin)*rng();if(inRing([x,z],island))pts.push([x,z]);}
  if(!pts.length)return 0;const trunk=new T.InstancedMesh(new T.CylinderGeometry(.024,.034,.28,6),mat.trunk,pts.length),canopy=new T.InstancedMesh(new T.IcosahedronGeometry(.16,1),mat.tree,pts.length);
  const tr=new T.Matrix4(),p=new T.Vector3(),q=new T.Quaternion(),s=new T.Vector3();
  pts.forEach(([x,z],i)=>{const h=.8+rng()*.7;tr.compose(p.set(x,.27,z),q,s.set(1,h,1));trunk.setMatrixAt(i,tr);tr.compose(p.set(x,.42,z),q,s.set(.8,1.2,.8));canopy.setMatrixAt(i,tr);});
  trunk.instanceMatrix.needsUpdate=true;canopy.instanceMatrix.needsUpdate=true;trunk.name='Illustrative island trees';canopy.name='Illustrative island canopy';group.add(trunk,canopy);return pts.length;
}
function landShape(ring,holes=[]){const shape=new T.Shape();for(let i=0;i<ring.length;i++){const [x,z]=ring[i];i?shape.lineTo(x,-z):shape.moveTo(x,-z);}shape.closePath();for(const h of holes){if(h.length<3)continue;const path=new T.Path();h.forEach(([x,z],i)=>i?path.lineTo(x,-z):path.moveTo(x,-z));path.closePath();shape.holes.push(path);}return shape;}
function landMesh(group,piece,m,y,name){const geom=new T.ShapeGeometry(landShape(piece.outer,piece.holes||[]));geom.rotateX(-Math.PI/2);const obj=new T.Mesh(geom,m);obj.position.y=y;obj.name=name;obj.renderOrder=8;obj.receiveShadow=true;group.add(obj);return obj;}
function lookupAlpha(ctx,lon,lat){const [x,y]=canvasXY(lon,lat);if(x<0||y<0||x>=WIDTH||y>=HEIGHT)return null;return ctx.getImageData(Math.floor(x),Math.floor(y),1,1).data[3]>=128;}
function crossSection(ctx,lon,lowLat,highLat){const samples=250,step=(highLat-lowLat)/samples;let longest=0,run=0,wetTotal=0;
  for(let i=0;i<=samples;i++){const wet=lookupAlpha(ctx,lon,lowLat+step*i);if(wet){run++;wetTotal++;}else{longest=Math.max(longest,run);run=0;}}longest=Math.max(longest,run);
  return {longestWaterWidthMeters:Math.round(longest*step*111195),wetSamples:wetTotal,samples:samples+1};}
export function renderHydrography(group,regions,materials,year,islandData=null,waterData=null,localEdits=[]){
  const result={waterFeatures:0,waterMeshes:0,shorelineSegments:0,islandHoles:0,belleIslandVerified:false,trees:0,triangleArea:0,
    riverSource:waterData?.source_name||'UNAVAILABLE',riverVerified:false,renderMethod:'GIS_RASTER_MASK_V219_COMPASS_ALIGNED_MAINLAND',crossSections:{},probeResults:{},waterMaskSize:`${WIDTH}x${HEIGHT}`};
  if(year<2024)return result;
  if(waterData?.schema!=='agentopia.detroit.river.v209'||waterData.qa?.passed!==true){console.error('No independently verified modern river source.');return result;}
  const can=document.createElement('canvas');can.width=WIDTH;can.height=HEIGHT;const ctx=can.getContext('2d',{willReadFrequently:true});
  if(!ctx){console.error('Cannot initialize browser GIS mask rasterizer');return result;}
  const seen=new Set();ctx.clearRect(0,0,WIDTH,HEIGHT);ctx.fillStyle='#2e7896';
  for(const f of waterData.polygons||[]){const rings=f.rings||[],finger=String(f.id)+'|'+rings.length+'|'+JSON.stringify(rings.map(r=>[r.length,r[0]]));
    if(seen.has(finger))continue;seen.add(finger);result.waterFeatures++;
    let valid=0;ctx.beginPath();
    for(const ring of rings){if(!Array.isArray(ring)||ring.length<4)continue;let first=true;
      for(const pt of ring){if(!Array.isArray(pt)||pt.length<2||!Number.isFinite(+pt[0])||!Number.isFinite(+pt[1]))continue;
        const [x,y]=canvasXY(+pt[0],+pt[1]);if(first){ctx.moveTo(x,y);first=false;}else ctx.lineTo(x,y);}
      if(!first){ctx.closePath();valid++;result.shorelineSegments+=ring.length;}
    }
    if(valid)ctx.fill('evenodd');
  }
  if(!result.waterFeatures){console.error('No usable modern river GIS polygons');return result;}
  // The National Register documents the exact ORIGINAL Hart Plaza extent.
  // It is independent land evidence, and must never be painted as water.
  const hart=waterData.land_override_nps_hart_plaza;
  if(Array.isArray(hart)&&hart.length>=4){
    ctx.save();ctx.globalCompositeOperation='destination-out';ctx.fillStyle='#000';
    ctx.beginPath();hart.forEach(([lon,lat],i)=>{const [x,y]=canvasXY(lon,lat);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fill();ctx.restore();
  }
  // The DNR-mapped Belle Isle park boundary overrides generalized water surfaces.
  // This is geographic land evidence, never a painted/fabricated island.
  if(islandData?.schema==='agentopia.detroit.park.v1'){
    ctx.save();ctx.globalCompositeOperation='destination-out';ctx.fillStyle='#000';
    for(const ring of islandData.rings||[]){if(!Array.isArray(ring)||ring.length<4)continue;
      ctx.beginPath();ring.forEach(([lon,lat],i)=>{const [x,y]=canvasXY(lon,lat);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fill();}
    ctx.restore();
  }

  // Correct verified-river raster where real mapped buildings and named
  // Detroit-side land anchors prove a coarse water polygon cannot be water.
  // No source GIS file is modified.
  const landCorrections=applyWaterfrontCorrections(ctx,regions,islandData,RECT,WIDTH,HEIGHT);
  result.landCorrections=landCorrections;
  result.localMaskCorrections=applyLocalMaskEdits(ctx,localEdits,year,RECT,WIDTH,HEIGHT,islandData);
  const probes={};for(const [label,lon,lat,expected] of PROBES){const wet=lookupAlpha(ctx,lon,lat);probes[label]={wet,expected,match:wet===expected};}
  result.probeResults=probes;
  result.crossSections={downtown:crossSection(ctx,-83.043,42.315,42.331),ambassador:crossSection(ctx,-83.077,42.298,42.324),belle:crossSection(ctx,-82.99,42.329,42.365)};
  const passed=Object.values(probes).every(p=>p.match) && result.crossSections.downtown.longestWaterWidthMeters>=200;
  result.riverVerified=passed;
  // Cache corrected water alpha for road geometry and citizen pavement placement.
  // Importantly, this uses EXACTLY the same south-positive (+Z) projected XY and same raster
  // as the displayed river. Roads cannot become invisible under water again.
  const alpha=ctx.getImageData(0,0,WIDTH,HEIGHT).data;
  result.isWetProjected=(x,z)=>{
    const px=Math.floor((x-RECT.xmin)*WIDTH/(RECT.xmax-RECT.xmin));
    const py=Math.floor((z-RECT.zmin)*HEIGHT/(RECT.zmax-RECT.zmin));
    if(px<0||py<0||px>=WIDTH||py>=HEIGHT)return false;
    return alpha[(py*WIDTH+px)*4+3]>=128;
  };
  const tex=new T.CanvasTexture(can);tex.colorSpace=T.SRGBColorSpace;tex.anisotropy=4;tex.generateMipmaps=true;
  // alphaTest discards dry pixels: this is an actual water mask and cannot
  // draw the giant grass plane over pixels classified as water by this data.
  const waterMaterial=new T.MeshPhysicalMaterial({map:tex,color:0xd2efff,transparent:true,alphaTest:.35,opacity:1,roughness:.31,metalness:0,
    clearcoat:.7,clearcoatRoughness:.15,side:T.DoubleSide,depthWrite:false});
  const width=RECT.xmax-RECT.xmin,depth=RECT.zmax-RECT.zmin;
  const plane=new T.Mesh(new T.PlaneGeometry(width,depth),waterMaterial);plane.rotation.x=-Math.PI/2;plane.position.set((RECT.xmin+RECT.xmax)/2,.135,(RECT.zmin+RECT.zmax)/2);
  plane.name='Detroit River corrected mainland shoreline + Belle Isle GIS mask (v2.0.19)';plane.renderOrder=5;group.add(plane);result.waterMeshes=1;
  // Place the independently surveyed MANAGEMENT boundary above the river.
  // This is labeled a park boundary, never claimed to be a perfect shoreline.
  let piece=null;
  if(islandData?.schema==='agentopia.detroit.park.v1'){
    const center=xy(42.3426,-82.9783);
    for(const part of nestedPolygons(islandData.rings||[])){
      if(!inRing(center,part.outer))continue;const outer=clipRing(part.outer);if(outer.length<3)continue;
      const holes=part.holes.map(clipRing).filter(h=>h.length>=3&&inRing(h[0],outer));
      if(!piece||Math.abs(ringArea(outer))>Math.abs(ringArea(piece.outer)))piece={outer,holes};
    }
  }
  if(!piece){ // Real island hole supplied by state river dataset is acceptable.
    for(const f of waterData.polygons||[])for(const part of nestedPolygons(f.rings||[]))for(const h of part.holes||[]){const ring=clipRing(h);
      if(ring.length<3||!isBelleIsleHole(ring))continue;if(!piece||Math.abs(ringArea(ring))>Math.abs(ringArea(piece.outer)))piece={outer:ring,holes:[]};
    }
  }
  // Present the mapped Hart Plaza as land, but NOT as a fictional building.
  if(Array.isArray(hart)&&hart.length>=4){const ring=hart.map(([lon,lat])=>xy(lat,lon));
    landMesh(group,{outer:ring,holes:[]},materials.concrete,.195,'Hart Plaza recorded historic site outline · NPS Section 10');}
  if(piece){landMesh(group,piece,materials.parks,.19,'Belle Isle mapped land boundary (not surveyed shoreline)');result.belleIslandVerified=true;
    result.trees=parkTrees(group,piece.outer,materials);}
  console.info('DETROIT RIVER MASK v209',JSON.stringify({source:result.riverSource,probes:result.probeResults,crossSections:result.crossSections,valid:passed,waterFeatures:result.waterFeatures}));
  if(!passed)console.error('DETROIT RIVER MASK: Wet/dry coverage still incorrect. Examine cached GIS data; do not certify Detroit River from polygon count.');
  return result;
}
