/* Agentopia Detroit 2.0.11: GPU-instanced urban architectural finishes.
 * Source building footprints/heights are unchanged; ALL added trims/windows/
 * rooftops are visual approximation, NOT a measured historic facade. Works
 * only for modern mapped years 2024/2026 and future 2045. Earlier eras stay
 * source-gated and unrendered pending dated reconstruction assets.
 */
import * as T from 'three/webgpu';
import {xy,seeded} from './geography.js';

const UP=new T.Vector3(0,1,0), EYE=new T.Vector3(), TURN=new T.Quaternion(), SIZE=new T.Vector3(), TEMP=new T.Matrix4();
const DOWNTOWN=xy(42.3296,-83.0474);
function height(row){const feet=Number(row.m),stories=Number(row.s);const metres=Number.isFinite(feet)&&feet>0?feet*.3048:Number.isFinite(stories)&&stories>0?stories*3.3:8.5;return Math.max(.14,Math.min(metres/32,12));}
function areaAndCenter(points){let a=0,cx=0,cz=0;const n=points.length;
 for(let k=0;k<n;k++){const p=points[k],q=points[(k+1)%n],cross=p[0]*q[1]-q[0]*p[1];a+=cross;cx+=(p[0]+q[0])*cross;cz+=(p[1]+q[1])*cross;}
 if(Math.abs(a)<1e-8)return {area:0,center:points[0]||[0,0],ccw:true};
 return {area:Math.abs(a)*.5,center:[cx/(3*a),cz/(3*a)],ccw:a>0};}
function compose(x,y,z,sx,sy,sz,angle=0){EYE.set(x,y,z);TURN.setFromAxisAngle(UP,angle);SIZE.set(sx,sy,sz);TEMP.compose(EYE,TURN,SIZE);return TEMP.clone();}
function instance(parent,geometry,material,matrices,name){if(!matrices.length)return 0;const obj=new T.InstancedMesh(geometry,material,matrices.length);matrices.forEach((m,i)=>obj.setMatrixAt(i,m));obj.instanceMatrix.needsUpdate=true;obj.frustumCulled=false;obj.name=name;obj.castShadow=false;obj.receiveShadow=false;parent.add(obj);return matrices.length;}
function ringPoints(row){if(!Array.isArray(row.p)||row.p.length<4)return null;const output=[];for(const p of row.p){if(!Array.isArray(p)||p.length<2)continue;const lon=Number(p[0]),lat=Number(p[1]);if(!Number.isFinite(lon)||!Number.isFinite(lat))continue;output.push(xy(lat,lon));}
 if(output.length<4)return null;const first=output[0],last=output[output.length-1];if(Math.hypot(first[0]-last[0],first[1]-last[1])<.0001)output.pop();return output.length>=3?output:null;}
export function addFacadeDetails(group,regions,materials,year,quality='medium'){
 const stats={windows:0,roofs:0,trims:0,pilasters:0,buildingsDetailed:0,architecturalAccuracy:'Visual facade approximations; GIS footprints remain source geometry'};
 if(year<2024)return stats;
 const high=quality==='high',low=quality==='low';
 const limits={buildings:high?1500:low?300:850,windows:high?56000:low?9000:26000,trims:high?7400:low?1400:3900,pilasters:high?3800:low?450:1800,roofs:high?600:low?100:300};
 const candidates=[],seen=new Set();
 for(const region of regions){for(const row of (region.buildings||[])){
   const pts=ringPoints(row);if(!pts)continue;const h=height(row);if(h<.38)continue;
   const {area,center,ccw}=areaAndCenter(pts);if(area<.05||area>140)continue;
   // Geographically prioritize the core but do not pretend we have surveyed facades.
   const dist=Math.hypot(center[0]-DOWNTOWN[0],center[1]-DOWNTOWN[1]);if(dist>100)continue;
   const key=String(row.id??'')+':'+center.map(x=>x.toFixed(3)).join(',');if(seen.has(key))continue;seen.add(key);
   candidates.push({row,pts,h,area,center,ccw,dist,priority:dist-.35*Math.min(h,9)});
 }}
 candidates.sort((a,b)=>a.priority-b.priority);const chosen=candidates.slice(0,limits.buildings);
 const panes=[],lit=[],parapets=[],cornices=[],pilasters=[],vents=[];const rnd=seeded(0x210211);
 let windowBudget=limits.windows,trimBudget=limits.trims,pilasterBudget=limits.pilasters;
 for(const c of chosen){const {pts,h,center,ccw,area,row}=c;const id=(Number(row.id)||0)>>>0;
   let count=0;const floors=Math.min(90,Math.max(2,Math.round(h/.125)));
   const mood=id%7;const floorSkip=low?3:1;const edgeList=[];
   for(let i=0;i<pts.length;i++){
     const a=pts[i],b=pts[(i+1)%pts.length],dx=b[0]-a[0],dz=b[1]-a[1],length=Math.hypot(dx,dz);
     if(length<.3||length>36)continue;
     const nx=(ccw?1:-1)*dz/length,nz=(ccw?-1:1)*dx/length;
     const rotation=Math.atan2(nx,nz),edgeAngle=-Math.atan2(dz,dx),mx=(a[0]+b[0])/2,mz=(a[1]+b[1])/2;
     edgeList.push({a,dx,dz,length,nx,nz,rotation,edgeAngle,mx,mz});
     // Roofline parapets and stone cornices follow actual mapped footprint edges.
     if(trimBudget>1&&h>.65){const raised=h-.015;
       cornices.push(compose(mx+nx*.014,raised,mz+nz*.014,length,.055,.058,edgeAngle));trimBudget--;
       if(mood%3!==0&&trimBudget){parapets.push(compose(mx+nx*.016,h+.067,mz+nz*.016,length,.13,.04,edgeAngle));trimBudget--;}
     }
     const cols=Math.max(1,Math.min(35,Math.floor(length/(h>2?.20:.28))));
     const sampledRows=Math.max(1,Math.ceil(floors/floorSkip));
     // Do not exhaust instance budget on one enormous footprint.
     const skip=Math.max(1,Math.ceil(cols*sampledRows/500));
     for(let f=1;f<floors&&windowBudget>0;f+=floorSkip*skip){
       const y=h*(f+.38)/floors; if(y>=h-.07)continue;
       for(let j=0;j<cols&&windowBudget>0;j+=skip){
         const along=(j+.5)/cols;
         const x=a[0]+along*dx+nx*.035,z=a[1]+along*dz+nz*.035;
         const mat=compose(x,y,z,1,1,1,rotation);
         ((rnd()<.10)?lit:panes).push(mat);windowBudget--;count++;
       }
     }
     if(pilasterBudget>0&&h>1.0&&length>.72&&mood<4){
       const slots=Math.min(8,Math.floor(length/.66));
       for(let j=1;j<slots&&pilasterBudget>0;j++){
         const frac=j/slots;
         pilasters.push(compose(a[0]+frac*dx+nx*.026,h*.5,a[1]+frac*dz+nz*.026,.045,h*.87,.04,rotation));
         pilasterBudget--;
       }
     }
   }
   if(h>1&&vents.length<limits.roofs){
     const scale=Math.min(.36,Math.max(.11,Math.sqrt(area)*.11));
     vents.push(compose(center[0],h+.08,center[1],scale,.15,scale,id%7*.23));
   }
   if(count||edgeList.length)stats.buildingsDetailed++;
 }
 const windowGeo=new T.PlaneGeometry(.12,.082);
 stats.windows+=instance(group,windowGeo,materials.windows,panes,'GIS-aligned glass windows — illustrative');
 stats.windows+=instance(group,windowGeo,materials.nightwindow,lit,'GIS-aligned illuminated windows — illustrative');
 const cube=new T.BoxGeometry(1,1,1);
 stats.trims+=instance(group,cube,materials.stone,cornices,'Rooftop cornices — decorative, not archival');
 stats.trims+=instance(group,cube,materials.concrete,parapets,'Rooftop parapet profiles — decorative, not archival');
 stats.pilasters+=instance(group,cube,materials.stone,pilasters,'Wall pilasters — decorative, not archival');
 stats.roofs+=instance(group,cube,materials.steelDark,vents,'Rooftop mechanical boxes — schematic');
 return stats;
}
