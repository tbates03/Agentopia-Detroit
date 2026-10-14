/* Unified local City Builder UI. Edits stay in the existing 3D viewport;
 * NEVER sends edit requests to the Agentopia world/server.
 */
import {KEY,SCHEMA,loadLocalEdits,saveLocalEdits,validatePack,cleanFeature} from './city-edits.js';
import {ORIGIN, METERS_PER_UNIT} from './geography.js';
const $=id=>document.getElementById(id);
export function initInlineEditor({onCommit=()=>{}}={}){
  const drawer=$('city-editor-drawer'),open=$('unified-edit'),close=$('editor-close'),list=$('editor-list'),form=$('editor-form'),status=$('editor-status');
  let edits=loadLocalEdits(),selection=null,placement=false;
  const fields=['name','type','lat','lon','radiusM','start','end','source','notes','confirmed'];
  const fEl=(name)=>form.elements.namedItem(name);
  function msg(text){status.textContent=text;}
  function redraw(){
    list.replaceChildren();
    for(const e of edits){const option=document.createElement('option');option.value=e.id;option.textContent=e.name+(e.confirmed?' ✓':'');list.append(option);}
    if(!selection && edits.length)selection=edits[0].id;
    if(selection&&!edits.some(e=>e.id===selection))selection=edits[0]?.id||null;
    list.value=selection||'';
    const e=edits.find(x=>x.id===selection);for(const key of fields){const el=fEl(key);if(!el)continue;
      if(el.type==='checkbox')el.checked=!!e?.[key];else el.value=e?.[key]??'';
      el.disabled=!e;
    }
    $('editor-delete').disabled=!e;
  }
  function persist(){try{edits=saveLocalEdits(edits).features;onCommit(edits);msg('Applied '+edits.length+' browser-local edits to this 3D city. Original GIS and simulation unchanged.');redraw();return true;}catch(err){msg('Not saved: '+String(err.message||err));return false;}}
  function create(){
    const id='local-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,7);
    const e={id,name:'Detroit annotation',type:'landmark',lat:42.329,lon:-83.045,radiusM:22,start:2026,end:2045,source:'',notes:'Needs a cited source',confirmed:false};
    edits.push(e);selection=id;redraw();msg('New local annotation. Use Place on map to pick coordinates, add a source, then apply.');
  }
  function updateForm(){const e=edits.find(x=>x.id===selection);if(!e)return;
    for(const key of fields){const el=fEl(key);if(!el)continue;const raw=el.type==='checkbox'?el.checked:el.value;e[key]=['lat','lon','radiusM','start','end'].includes(key)?Number(raw):raw;}
    const cleaned=cleanFeature(e);if(cleaned){Object.assign(e,cleaned);msg('Local edit changed. Press Apply to preview it in this 3D scene.');}
    else msg('Please correct the edit values before applying.');
  }
  open.addEventListener('click',()=>{drawer.hidden=false;drawer.classList.add('visible');redraw();});
  close.addEventListener('click',()=>{drawer.classList.remove('visible');drawer.hidden=true;placement=false;});
  $('editor-new').addEventListener('click',create);
  $('editor-save').addEventListener('click',()=>{updateForm();persist();});
  $('editor-delete').addEventListener('click',()=>{edits=edits.filter(e=>e.id!==selection);selection=null;redraw();persist();});
  list.addEventListener('change',()=>{selection=list.value;redraw();});
  form.addEventListener('change',updateForm);
  $('editor-pick').addEventListener('click',()=>{if(!selection)create();placement=true;msg('Placement armed: click an open land area in the 3D scene to place the selected feature.');});
  $('editor-export').addEventListener('click',()=>{
    try{const json=validatePack({schema:SCHEMA,features:edits});const blob=new Blob([JSON.stringify(json,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
      const a=document.createElement('a');a.href=url;a.download='agentopia-detroit-city-edits.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);msg('Exported local edits JSON.');}
    catch(err){msg('Export failed: '+err.message);}
  });
  $('editor-import').addEventListener('change',async(e)=>{
    const file=e.target.files?.[0];if(!file)return;
    try{const pack=validatePack(JSON.parse(await file.text()));edits=pack.features;selection=edits[0]?.id||null;redraw();persist();}
    catch(err){msg('Import rejected: '+String(err.message||err));}
    finally{e.target.value='';}
  });
  $('editor-clear').addEventListener('click',()=>{if(!confirm('Clear browser-local map annotations? Source GIS and world data will not change.'))return;edits=[];selection=null;persist();});
  function mapPick(point){
    if(!placement)return false;
    placement=false;
    const e=edits.find(x=>x.id===selection);if(!e)return false;
    e.lat=ORIGIN.lat + point.z*METERS_PER_UNIT/111194.9266;
    e.lon=ORIGIN.lon + point.x*METERS_PER_UNIT/(111194.9266*Math.cos(ORIGIN.lat*Math.PI/180));
    e.lat=Math.round(e.lat*1e6)/1e6;e.lon=Math.round(e.lon*1e6)/1e6;
    redraw();msg('Placed at '+e.lat+', '+e.lon+'. Add a source and press Apply.');return true;
  }
  redraw();
  return {mapPick,isPlacing:()=>placement,open:()=>open.click(),getEdits:()=>edits};
}
