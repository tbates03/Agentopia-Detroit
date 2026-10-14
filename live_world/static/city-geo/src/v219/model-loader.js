/* Agentopia Detroit 2.0.11 — local-only GLB landmark ingestion.
 * No external asset fetches; explicit provenance and rights required.
 * Never suggest that decorative city finishes are authoritative landmark models.
 */
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {xy} from './geography.js';
const FILE=/^[a-zA-Z0-9_-]+\.glb$/;
const KNOWN_LICENSES=new Set(['CC0-1.0','CC-BY-4.0','CC-BY-SA-4.0','CC-BY-3.0','USER-OWNED-LOCAL-ONLY']);
const loader=new GLTFLoader();
export function acceptsLocalAsset(a,year){
 if(!a||typeof a!=='object'||!FILE.test(a.file||''))return false;
 if(!Number.isFinite(a.lat)||!Number.isFinite(a.lon)||!Number.isInteger(a.start)||!Number.isInteger(a.end)||a.start>a.end||year<a.start||year>a.end)return false;
 if(!KNOWN_LICENSES.has(a.license)||!Number.isFinite(Number(a.scale??1))||Number(a.scale??1)<=0)return false;
 if(a.kind==='illustrative_concept')return year===2045;
 if(a.kind!=='real_landmark')return false;
 return a.coordinates_verified===true&&a.era_verified===true&&typeof a.source==='string'&&/^https:\/\//.test(a.source)&&typeof a.author==='string'&&a.author.length>2;
}
export async function loadLocalModels(group,year){
 try{
  const response=await fetch('./assets/models/manifest.json',{method:'GET',cache:'no-store',credentials:'same-origin'});
  if(!response.ok)return 0;
  const manifest=await response.json();
  if(manifest.schema!=='agentopia.local_glb.v1'||!Array.isArray(manifest.assets))return 0;
  const selected=manifest.assets.filter(a=>acceptsLocalAsset(a,year));let count=0;
  for(const a of selected.slice(0,40)){
   try{
    const gltf=await loader.loadAsync('./assets/models/'+encodeURIComponent(a.file));
    if(!group.parent){gltf.scene.traverse(o=>o.geometry?.dispose?.());continue;}
    const [x,z]=xy(a.lat,a.lon);
    const scale=Math.min(10,Math.max(.00001,Number(a.scale??1)));
    gltf.scene.position.set(x,Number(a.y)||0,z);
    gltf.scene.rotation.y=Number(a.heading)||0;gltf.scene.scale.setScalar(scale);
    gltf.scene.userData.feature={name:a.name||a.file,start:a.start,end:a.end,source:a.source||'',location_certainty:a.kind==='real_landmark'?`Imported local 3D landmark · model by ${a.author} · ${a.license}. Verify geometry and date against source.`:'Future artistic concept; not a historical landmark.'};
    gltf.scene.name=`Imported: ${a.name||a.file}`;
    gltf.scene.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;}});
    group.add(gltf.scene);count++;
   }catch(e){console.warn('Local landmark model skipped:',a.file,e)}
  }
  return count;
 }catch(e){console.warn('Optional local landmark manifest unavailable:',e);return 0;}
}
