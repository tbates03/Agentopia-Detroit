/* Ground shading derived from REAL mapped Detroit GIS building density and
 * street centerlines. Color / landcover is artistic, not a land-use survey.
 */
import * as T from 'three/webgpu';
import {xy,seeded} from './geography.js';
export function addGISGroundFinish(material,regions,year,quality){
 if(year<2024)return null;
 const size=quality==='high'?2048:1024,can=document.createElement('canvas');
 can.width=can.height=size;
 const ctx=can.getContext('2d');if(!ctx)return null;
 ctx.fillStyle='#6b8665';ctx.fillRect(0,0,size,size);
 // Aerial urban density treatment; artistic landcover based on known downtown
 // center, not a replacement for real municipal zoning or aerial imagery.
 const W=710,H=650;
 const px=(lon,lat)=>{const [x,z]=xy(lat,lon);return [(x+W/2)/W*size,(z+H/2)/H*size];};
 const [cx,cy]=px(-83.043,42.331),rad=size*86/W;
 const urban=ctx.createRadialGradient(cx,cy,rad*.11,cx,cy,rad);
 urban.addColorStop(0,'rgba(184,172,154,.84)');
 urban.addColorStop(.56,'rgba(160,165,147,.66)');
 urban.addColorStop(1,'rgba(116,146,112,0)');
 ctx.fillStyle=urban;ctx.fillRect(0,0,size,size);

 const r=seeded(3174);
 // Non-semantic organic texture breaks up the unrealistic flat plane.
 for(let i=0;i<22000;i++){
   const green=84+Math.floor(r()*65);ctx.fillStyle=`rgba(${green-30},${green},${green-35},${.04+r()*.055})`;
   ctx.fillRect(r()*size,r()*size,1+r()*8,1+r()*8);
 }
 const project=pt=>{const [x,z]=xy(pt[1],pt[0]);return [(x+W/2)/W*size,(z+H/2)/H*size];};
 // Buffers follow mapped buildings; no invented grid or declared zoning.
 ctx.fillStyle='rgba(174,164,151,.37)';ctx.strokeStyle='rgba(169,167,158,.30)';
 for(const area of regions||[])for(const b of area.buildings||[]){
   if(!Array.isArray(b.p)||b.p.length<3)continue;
   const pts=b.p,step=Math.max(1,Math.floor(pts.length/24));ctx.beginPath();let started=false;
   for(let i=0;i<pts.length;i+=step){const [x,y]=project(pts[i]);if(!Number.isFinite(x)||!Number.isFinite(y))continue;
     started?ctx.lineTo(x,y):ctx.moveTo(x,y);started=true;
   }
   if(started){ctx.closePath();ctx.lineWidth=10;ctx.stroke();ctx.fill();}
 }
 // Mapped street corridors align with the actual road meshes above ground.
 ctx.strokeStyle='rgba(38,49,50,.52)';ctx.lineCap='round';
 for(const area of regions||[])for(const row of area.roads||[]){
   if(!Array.isArray(row.p)||row.p.length<2||row.tunnel)continue;
   ctx.lineWidth=['motorway','trunk','primary'].includes(row.t)?4.2:['secondary','tertiary'].includes(row.t)?3.0:1.7;
   ctx.beginPath();for(let i=0;i<row.p.length;i++){const [x,y]=project(row.p[i]);i?ctx.lineTo(x,y):ctx.moveTo(x,y);}ctx.stroke();
 }
 const texture=new T.CanvasTexture(can);texture.colorSpace=T.SRGBColorSpace;
 texture.anisotropy=8;material.map=texture;material.color.setHex(0xffffff);material.needsUpdate=true;
 return texture;
}
