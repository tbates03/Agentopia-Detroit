/* Agentopia Detroit 2.0.18: one coherent coordinate system and riverbank.
 * All sources are WGS84 GeoJSON [lon,lat]. South is +Z (north is -Z), matching geography.js.xy().
 * Inferred waterfront control line is NOT a surveyed shoreline: it clips only
 * false-positive *water* on the Detroit mainland side, never creates water.
 */
export const METER_PER_UNIT=32;
export const ORIGIN_LAT=42.329, ORIGIN_LON=-83.052;
export const LAND_ANCHORS=Object.freeze([
 {name:'Ralph C. Wilson Jr. Centennial Park',lat:42.32198,lon:-83.06225,bufferM:60,source:'https://www.detroitriverfront.org/map'},
 {name:'Huntington Place',lat:42.32676,lon:-83.04911,bufferM:55,source:'https://huntingtonplacedetroit.com/'},
 {name:'Hart Plaza',lat:42.32743,lon:-83.04441,bufferM:48,source:'https://www.detroitriverfront.org/map'},
 {name:'Renaissance Center / GM waterfront',lat:42.32915,lon:-83.0397,bufferM:85,source:'https://historicdetroit.org/buildings/renaissance-center'},
 {name:'GM Plaza',lat:42.32805,lon:-83.03891,bufferM:55,source:'https://www.detroitriverfront.org/map'},
 {name:'Milliken State Park & Harbor',lat:42.33203,lon:-83.02703,bufferM:55,source:'https://www.michigan.gov/recsearch/parks/williammilliken'},
 {name:'Robert C. Valade Park',lat:42.33503,lon:-83.01880,bufferM:45,source:'https://www.detroitriverfront.org/map'},
]);
/* A visual mainland-side correction guide, *not* a claimed surveyed shoreline.
 * Source-backed riverfront POIs constrain the guide. MainLakes polygon still
 * determines where water exists. In 2024+ only; cannot back-project into 1701.
 * Stops short of Belle Isle to preserve the island's northern channel.
 */
export const DETROIT_SHORE_GUIDE=Object.freeze([
 [-83.0980,42.2942],[-83.0890,42.3006],[-83.0790,42.3084],
 [-83.0710,42.3152],[-83.0650,42.3197],[-83.0621,42.3207],
 [-83.0570,42.3230],[-83.0510,42.32465],[-83.0470,42.32565],
 [-83.0438,42.32605],[-83.0400,42.32685],[-83.0371,42.3277],
 [-83.0320,42.32905],[-83.0272,42.3306],[-83.0220,42.33255],
 [-83.0186,42.33385],[-83.0134,42.3359],[-83.0085,42.33785]
]);
export function projectedPoint(lat,lon,originLat=ORIGIN_LAT,originLon=ORIGIN_LON){
 if(!Number.isFinite(lat)||!Number.isFinite(lon))throw Error('invalid coordinate');
 return [(lon-originLon)*111194.9266*Math.cos(originLat*Math.PI/180)/32,
         (originLat-lat)*111194.9266/32]; // +Z is SOUTH, matching geography.js.xy()
}
export function coordsToRaster(lon,lat,rect,width,height){
 const [x,z]=projectedPoint(lat,lon);
 return [(x-rect.xmin)*width/(rect.xmax-rect.xmin),(z-rect.zmin)*height/(rect.zmax-rect.zmin)];
}
export function geoContains(lon,lat,ring){let inside=false;
 if(!Array.isArray(ring)||ring.length<3)return false;
 for(let i=0,j=ring.length-1;i<ring.length;j=i++){
  const a=ring[i],b=ring[j];if(!Array.isArray(a)||!Array.isArray(b))continue;
  if((a[1]>lat)!==(b[1]>lat)&&lon<(b[0]-a[0])*(lat-a[1])/(b[1]-a[1])+a[0])inside=!inside;
 }return inside;
}
export function shorelineLatAt(lon){
 const a=DETROIT_SHORE_GUIDE;
 if(!Number.isFinite(lon)||lon<a[0][0]||lon>a[a.length-1][0])return null;
 for(let i=1;i<a.length;i++)if(lon<=a[i][0]){
  const t=(lon-a[i-1][0])/(a[i][0]-a[i-1][0]);
  return a[i-1][1]+(a[i][1]-a[i-1][1])*t;
 }
 return a[a.length-1][1];
}
export function buildingFootprints(regions,islandRings=[]){
 const out=[],ids=new Set();
 for(const area of regions||[])for(const row of area.buildings||[]){
  if(!Array.isArray(row.p)||row.p.length<4)continue;
  const pts=row.p.filter(p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(+p[0])&&Number.isFinite(+p[1]));
  if(pts.length<4)continue;
  const center=pts.reduce((a,p)=>[a[0]+(+p[0]),a[1]+(+p[1])],[0,0]).map(n=>n/pts.length);
  if(islandRings.some(r=>geoContains(center[0],center[1],r)))continue;
  const key=`${row.id||''}:${center[0].toFixed(6)}:${center[1].toFixed(6)}`;
  if(ids.has(key))continue;ids.add(key);out.push({p:pts,center});
 }return out;
}
export function rasterWet(pixels,px,py,width,height){
 const x=Math.floor(px),y=Math.floor(py);if(x<0||y<0||x>=width||y>=height)return false;
 return pixels[(y*width+x)*4+3]>=128;
}
/* Data-derived corrections: building footprints correct land where the coarse
 * river overlaps actual buildings. Column bands connect waterfront to mainland
 * only where a guide or adjacent real mapped buildings supports doing so.
 */
export function inferLandfront(regions,islandRings,ctx,rect,width,height){
 const buildings=buildingFootprints(regions,islandRings);
 const pixels=ctx.getImageData(0,0,width,height).data;
 const shoreline=Array(width).fill(null),nearby=Array(width).fill(null);
 const colToLon=x=>ORIGIN_LON+(rect.xmin+x/width*(rect.xmax-rect.xmin))*32/(111194.9266*Math.cos(ORIGIN_LAT*Math.PI/180));
 let guided=0;
 for(let x=0;x<width;x++){
  const lat=shorelineLatAt(colToLon(x));if(lat===null)continue;
  shoreline[x]=coordsToRaster(colToLon(x),lat,rect,width,height)[1];guided++;
 }
 const floodedFootprints=[];let submerged=0;
 for(const b of buildings){
  const pts=b.p.map(p=>coordsToRaster(+p[0],+p[1],rect,width,height));
  const [cx,cy]=coordsToRaster(...b.center,rect,width,height);
  if(!rasterWet(pixels,cx,cy,width,height)&&!pts.some(([x,y])=>rasterWet(pixels,x,y,width,height)))continue;
  submerged++;floodedFootprints.push(b);
  let minx=Infinity,maxx=-Infinity,miny=Infinity;
  for(const [x,y] of pts){minx=Math.min(minx,x);maxx=Math.max(maxx,x);miny=Math.min(miny,y);}
  if(maxx-minx>width*.05)continue;
  const from=Math.max(0,Math.floor(minx)-2),to=Math.min(width-1,Math.ceil(maxx)+2);
  for(let x=from;x<=to;x++){
   // Only link true Detroit-side waterfront building data to the mainland.
   const coast=shoreline[x];const band=135/32*(height/(rect.zmax-rect.zmin));
   if(coast===null||miny<coast-band)continue;
   nearby[x]=Math.min(nearby[x]??Infinity,miny);
  }
 }
 const paddingPx=13/32*height/(rect.zmax-rect.zmin);
 return {shoreline,nearby,submerged,floodedFootprints,footprintsChecked:buildings.length,guided,paddingPx};
}
export function applyWaterfrontCorrections(ctx,regions,islandData,rect,width,height){
 const islandRings=islandData?.schema==='agentopia.detroit.park.v1'?(islandData.rings||[]):[];
 const result=inferLandfront(regions,islandRings,ctx,rect,width,height);
 ctx.save();ctx.globalCompositeOperation='destination-out';ctx.fillStyle='#000';ctx.strokeStyle='#000';
 const buildingClearPx=12/32*width/(rect.xmax-rect.xmin);
 for(const b of result.floodedFootprints){
  const pts=b.p.map(p=>coordsToRaster(+p[0],+p[1],rect,width,height));
  ctx.beginPath();pts.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.closePath();
  ctx.fill();ctx.lineWidth=buildingClearPx*2;ctx.stroke();
 }
 let columnsApplied=0;
 for(let x=0;x<width;x++){
  const bank=result.shoreline[x];if(bank===null)continue;
  const near=result.nearby[x];const cutoff=Math.max(bank,near===null?bank:near+result.paddingPx);
  if(cutoff<=0)continue;
  // -Z is north/Detroit. Clear from pixel Y=0 toward the mapped shoreline.
  ctx.fillRect(x,0,1,Math.min(height,Math.max(0,Math.ceil(cutoff))));columnsApplied++;
 }
 // Keep bounded land features dry, but do not alter opposite (Windsor) bank.
 for(const a of LAND_ANCHORS){const [x,y]=coordsToRaster(a.lon,a.lat,rect,width,height);
  const rx=a.bufferM/32*width/(rect.xmax-rect.xmin),ry=a.bufferM/32*height/(rect.zmax-rect.zmin);
  ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,Math.PI*2);ctx.fill();
 }
 ctx.restore();
 return {submergedBuildingsBeforeCorrection:result.submerged,footprintsChecked:result.footprintsChecked,
  guardedAnchors:LAND_ANCHORS.length,mainlandGuideColumns:columnsApplied,
  coordinateConvention:'South +Z (matched to geography.js / river raster)',
  caution:'Shore guide inferred from mapped waterfront landmarks; not a surveyed shoreline'};
}
