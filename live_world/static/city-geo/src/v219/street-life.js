/* Street detail on the SAME real Detroit GIS centerlines used by the city.
 * Road markings/lamps are presentation geometry, not certified survey objects.
 */
import * as T from 'three/webgpu';
import {xy,seeded} from './geography.js';
function isDowntown(p){return p[1]>=42.318&&p[1]<=42.351&&p[0]>=-83.085&&p[0]<=-83.008;}
export function addMappedStreetDetail(group,regions,year,quality,isWetProjected){
 const result={stripes:0,lights:0};if(year<2024)return result;
 const strips=[],positions=[];
 for(const area of regions||[])for(const road of area.roads||[]){
   if(!Array.isArray(road.p)||road.p.length<2||road.bridge||road.tunnel)continue;
   const primary=['primary','secondary','trunk','tertiary'].includes(String(road.t));
   if(!primary)continue;
   let cumulative=0;
   for(let i=1;i<road.p.length;i++){
      const pa=road.p[i-1],pb=road.p[i];if(!isDowntown(pa)||!isDowntown(pb))continue;
      const [ax,az]=xy(pa[1],pa[0]),[bx,bz]=xy(pb[1],pb[0]);
      const dx=bx-ax,dz=bz-az,len=Math.hypot(dx,dz);
      if(len<.035||len>2.7)continue;
      if(typeof isWetProjected==='function'&&isWetProjected((ax+bx)/2,(az+bz)/2))continue;
      const ux=dx/len,uz=dz/len,ox=-uz*.012,oz=ux*.012;
      for(let d=.11;d<len-.015;d+=.31){const from=d,to=Math.min(len-.018,d+.12);
        if(to<=from)continue;const x=ax+ux*from,z=az+uz*from,xe=ax+ux*to,ze=az+uz*to,y=.207;
        strips.push(x-ox,y,z-oz, x+ox,y,z+oz, xe+ox,y,ze+oz,
                    x-ox,y,z-oz, xe+ox,y,ze+oz, xe-ox,y,ze-oz);
        result.stripes++;if(result.stripes>6000)break;
      }
      cumulative+=len;
      if(quality==='high'&&cumulative>1.0&&positions.length<190){positions.push([ax+dx*.5,az+dz*.5]);cumulative=0;}
      if(result.stripes>6000)break;
   }
   if(result.stripes>6000)break;
 }
 if(strips.length){const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(strips,3));g.computeVertexNormals();
   const m=new T.MeshStandardMaterial({color:0xf1dfb6,roughness:1,emissive:0x242219,emissiveIntensity:.08,side:T.DoubleSide});
   const mesh=new T.Mesh(g,m);mesh.name='GIS-aligned street markings (illustrative)';group.add(mesh);
   group.userData.urbanMaterials=(group.userData.urbanMaterials||[]).concat(m);
 }
 if(positions.length){
   const metal=new T.MeshStandardMaterial({color:0x50636e,metalness:.5,roughness:.4}),emission=new T.MeshStandardMaterial({color:0xf9e8ac,emissive:0xf7cd87,emissiveIntensity:1.1});
   const pole=new T.InstancedMesh(new T.CylinderGeometry(.005,.008,.26,5),metal,positions.length);
   const bulb=new T.InstancedMesh(new T.SphereGeometry(.021,6,4),emission,positions.length);
   const mat=new T.Matrix4(),p=new T.Vector3(),rot=new T.Quaternion(),scale=new T.Vector3(1,1,1);
   positions.forEach(([x,z],i)=>{mat.compose(p.set(x,.29,z),rot,scale);pole.setMatrixAt(i,mat);mat.compose(p.set(x,.44,z),rot,scale);bulb.setMatrixAt(i,mat);});
   pole.instanceMatrix.needsUpdate=bulb.instanceMatrix.needsUpdate=true;pole.name='Streetlights aligned to mapped roads (illustrative)';bulb.name='Streetlight globes';group.add(pole,bulb);
   group.userData.urbanMaterials=(group.userData.urbanMaterials||[]).concat(metal,emission);result.lights=positions.length;
 }
 return result;
}
