/* Agentopia browser-local City Builder overlay. No API writes, no world-engine changes.
 * User edits are NOT certified GIS data. Import applies only within one browser profile.
 */
export const KEY='agentopia.detroit.citybuilder.v1';
export const SCHEMA='agentopia.detroit.citybuilder.v1';
export const EDIT_TYPES=new Set(['landmark','park','shore_dry','shore_wet']);
const finite=n=>Number.isFinite(+n);
export function cleanFeature(a){
 if(!a||typeof a!=='object')return null;
 const lat=Number(a.lat),lon=Number(a.lon),radiusM=Number(a.radiusM??30),start=Number(a.start??2024),end=Number(a.end??2045);
 if(!EDIT_TYPES.has(a.type)||!Number.isFinite(lat)||!Number.isFinite(lon)||lat<42.23||lat>42.43||lon< -83.2||lon> -82.85)return null;
 if(!Number.isFinite(radiusM)||radiusM<2||radiusM>120||!Number.isInteger(start)||!Number.isInteger(end)||start<1701||end>2045||end<start)return null;
 const name=String(a.name||'').trim().slice(0,90);if(name.length<2)return null;
 const source=String(a.source||'').trim().slice(0,600);if(source&& !/^https:\/\/[^\s<>]+$/.test(source))return null;
 if(a.confirmed===true&&['shore_dry','shore_wet'].includes(a.type)&&!source)return null;
 return {id:String(a.id||('local-'+name.toLowerCase().replace(/[^a-z0-9]+/g,'-'))).slice(0,100),type:a.type,name,lat,lon,radiusM,start,end,source,notes:String(a.notes||'').slice(0,500),confirmed:a.confirmed===true};
}
export function validatePack(pack){
 if(!pack||pack.schema!==SCHEMA||!Array.isArray(pack.features)||pack.features.length>60)throw Error('Expected Agentopia City Builder v1 JSON with at most 60 edits');
 const result=[],ids=new Set();for(const a of pack.features){const f=cleanFeature(a);if(!f||ids.has(f.id))throw Error('Invalid/duplicate feature in city pack');ids.add(f.id);result.push(f);}return {schema:SCHEMA,features:result};
}
export function loadLocalEdits(){try{const raw=localStorage.getItem(KEY);if(!raw)return [];return validatePack(JSON.parse(raw)).features;}catch(e){console.warn('City Builder changes ignored:',e);return [];}}
export function saveLocalEdits(features){const pack=validatePack({schema:SCHEMA,features});localStorage.setItem(KEY,JSON.stringify(pack));return pack;}
function inRing(point,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const a=ring[i],b=ring[j];if(!Array.isArray(a)||!Array.isArray(b))continue;const [x,y]=a,[bx,by]=b;if((y>point[1])!==(by>point[1])&&point[0]<(bx-x)*(point[1]-y)/(by-y)+x)inside=!inside;}return inside;}
export function applyLocalMaskEdits(ctx,features,year,rect,width,height,islandData){
 // Only locally confirmed edits, only in the modern mapped eras, and within bounded radii.
 if(year<2024||!Array.isArray(features))return 0;
 const meter=111194.9266,lonScale=meter*Math.cos(42.329*Math.PI/180),originLat=42.329,originLon=-83.052;
 // +Z is SOUTH everywhere: match geography.js.xy and water canvasXY.
 const point=(lat,lon)=>{const x=(lon-originLon)*lonScale/32,z=(originLat-lat)*meter/32;return [(x-rect.xmin)*width/(rect.xmax-rect.xmin),(z-rect.zmin)*height/(rect.zmax-rect.zmin)];};
 const protectedDry=[[42.32915,-83.0397],[42.32743,-83.04441],[42.32198,-83.06225],[42.33203,-83.02703]];
 let applied=0;
 for(const row of features){const f=cleanFeature(row);if(!f||!f.confirmed||year<f.start||year>f.end||!['shore_dry','shore_wet'].includes(f.type))continue;
   if(f.type==='shore_wet'&&protectedDry.some(([lat,lon])=>Math.hypot((f.lat-lat)*111195,(f.lon-lon)*111195*Math.cos(lat*Math.PI/180))<f.radiusM+75))continue;
   if(f.type==='shore_wet'&&Array.isArray(islandData?.rings)&&islandData.rings.some(r=>inRing([f.lon,f.lat],r)))continue;
   const [x,y]=point(f.lat,f.lon),rx=f.radiusM/32*width/(rect.xmax-rect.xmin),ry=f.radiusM/32*height/(rect.zmax-rect.zmin);
   if(x<-rx||y<-ry||x>width+rx||y>height+ry)continue;
   ctx.save();ctx.globalCompositeOperation=f.type==='shore_dry'?'destination-out':'source-over';ctx.fillStyle=f.type==='shore_dry'?'#000':'#2e7896';ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,2*Math.PI);ctx.fill();ctx.restore();applied++;
 }
 return applied;
}
