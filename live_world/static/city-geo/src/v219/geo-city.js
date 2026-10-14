/* Agentopia Detroit geography viewer: real mapped footprints and roads, not schematic city blocks.
 * 2024 source GIS and time-of-installation OSM are NOT archival reconstructions.
 * No engine or world-state writes. 2045 is the only speculative visual era.
 */
import * as T from 'three/webgpu';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';
import {xy, seeded} from './geography.js';
import {createMaterials} from './materials.js';
import {renderHydrography} from './geo-water.js';
import {addFacadeDetails} from './city-details.js';
import {addModernRiverfront} from './riverfront-features.js';
import {addEraMassing,landmarkExclusion,addLocalAnnotations} from './era-massing.js';
import {addMappedStreetDetail} from './street-life.js';
import {drawVisibleMappedRoads} from './road-surfaces.js';
import {addGISGroundFinish} from './ground-finish.js';
const GEO_YEAR=2024, BUILDING_BATCH=72, MAX_RENDER_BUILDINGS=20000;
const isYear=n=>Number.isInteger(n)&&n>=1600&&n<=2200;
const arr=p=>Array.isArray(p)&&p.length>2;
const coord=p=>xy(p[1],p[0]); // GeoJSON [longitude, latitude]
function groupMesh(parent,geometry,material,name,y=0){const mesh=new T.Mesh(geometry,material);mesh.name=name;mesh.position.y=y;mesh.receiveShadow=true;parent.add(mesh);return mesh;}
function flatPolygon(group,ring,material,name,height=.015,holes=[]){if(!arr(ring))return;const shape=new T.Shape();let first=true;for(const pt of ring){if(!Array.isArray(pt)||pt.length<2)continue;const [x,z]=coord(pt);if(first){shape.moveTo(x,-z);first=false;}else shape.lineTo(x,-z);}if(first)return;shape.closePath();for(const ringHole of holes){if(!arr(ringHole))continue;const path=new T.Path();let firstHole=true;for(const pt of ringHole){if(!Array.isArray(pt)||pt.length<2)continue;const [hx,hz]=coord(pt);if(firstHole){path.moveTo(hx,-hz);firstHole=false;}else path.lineTo(hx,-hz);}if(!firstHole){path.closePath();shape.holes.push(path);}}const obj=new T.Mesh(new T.ShapeGeometry(shape),material);obj.rotation.x=-Math.PI/2;obj.position.y=height;obj.name=name;obj.receiveShadow=true;group.add(obj);return obj;}
function heightUnits(row){let med=Number(row.m);let stories=Number(row.s);let meters=Number.isFinite(med)&&med>0?med*.3048:Number.isFinite(stories)&&stories>0?stories*3.3:8.5;return Math.max(.14,Math.min(meters/32,12));}
function centroid(points){let sx=0,sz=0,count=0;for(const p of points){if(!p)continue;const [x,z]=coord(p);sx+=x;sz+=z;count++}return count?[sx/count,sz/count]:[0,0];}
function addBuildings(group,rows,m,year){if(year<GEO_YEAR)return 0;const mat=[m.stone,m.brick,m.redbrick,m.glass,m.concrete];let made=0,buckets=Array.from({length:5},()=>[]);
 const flush=(k)=>{let list=buckets[k];if(!list.length)return;try{const merged=mergeGeometries(list,false);if(merged){const mesh=groupMesh(group,merged,mat[k],'2024 GIS building footprints');mesh.receiveShadow=true;mesh.castShadow=false;} }finally{for(const g of list)g.dispose();buckets[k]=[];}};
 for(const row of rows){if(made>=MAX_RENDER_BUILDINGS)break;if(!arr(row.p))continue;const built=Number(row.y);if(isYear(built)&&built>year)continue;const pts=row.p;if(landmarkExclusion(pts,year))continue;const shape=new T.Shape();let started=false;for(const pt of pts){if(!Array.isArray(pt)||pt.length<2)continue;const [x,z]=coord(pt);if(!Number.isFinite(x)||!Number.isFinite(z))continue; if(!started){shape.moveTo(x,-z);started=true;}else shape.lineTo(x,-z);}if(!started)continue;shape.closePath();const h=heightUnits(row);
 const geometry=new T.ExtrudeGeometry(shape,{depth:h,steps:1,bevelEnabled:false,curveSegments:1});geometry.rotateX(-Math.PI/2);
 const id=Number(row.id)||made;const k=((id*7)>>>0)%5;buckets[k].push(geometry);if(buckets[k].length>=BUILDING_BATCH)flush(k);made++;
 }
 for(let k=0;k<buckets.length;k++)flush(k);return made;}
function labelSprite(text){const can=document.createElement('canvas');can.width=512;can.height=128;const ctx=can.getContext('2d');ctx.fillStyle='rgba(12,30,42,.83)';ctx.fillRect(0,0,512,128);ctx.strokeStyle='rgba(237,194,130,.9)';ctx.lineWidth=4;ctx.strokeRect(2,2,508,124);ctx.font='bold 27px system-ui, sans-serif';ctx.fillStyle='#faf6eb';let label=String(text);while(ctx.measureText(label).width>470&&label.length>7)label=label.slice(0,-5)+'…';ctx.fillText(label,18,75);const map=new T.CanvasTexture(can);map.colorSpace=T.SRGBColorSpace;const mat=new T.SpriteMaterial({map,transparent:true,depthWrite:false});const o=new T.Sprite(mat);o.scale.set(5.8,1.45,1);return o;}
const ANCHORS=[
{name:'Belle Isle Park',lat:42.3426,lon:-82.9783,start:2024,end:2045,source:'https://www.michigan.gov/dnr/places/v-centers/belle-isle',status:'Located on Belle Isle; the island shape is only shown if a verified source can supply it.'},
{name:'Woodward Avenue at Jefferson Avenue',lat:42.3293,lon:-83.0458,start:2024,end:2045,source:'https://detroitmi.gov/',status:'Street geometry is from an older mapped centerline inventory, not a verified 2026 traffic/closure record.'},
{name:'Hart Plaza',lat:42.32743,lon:-83.04441,start:1975,end:2045,source:'https://en.wikipedia.org/wiki/Philip_A._Hart_Plaza',status:'Historic civic riverfront plaza; geometry and assets pending.'},
{name:'Guardian Building',lat:42.3296,lon:-83.0464,start:1929,end:2045,source:'https://historicdetroit.org/buildings/guardian-building',status:'Mapped place marker. Requires licensed high-detail GLB architecture.'},
{name:'Penobscot Building',lat:42.3305,lon:-83.0472,start:1928,end:2045,source:'https://historicdetroit.org/buildings/penobscot-building',status:'Mapped place marker. Full architectural mesh pending.'},
{name:'Renaissance Center',lat:42.32915,lon:-83.0397,start:1977,end:2045,source:'https://historicdetroit.org/buildings/renaissance-center',status:'Mapped place marker; no fabricated cylinders.'},
{name:'Coleman A. Young Municipal Center',lat:42.3277,lon:-83.0450,start:1955,end:2045,source:'https://www.detroithistorical.org/learn/online-research/encyclopedia-of-detroit/coleman-young-municipal-center',status:'City-County Building completed 1955, renamed 1997. Anchor approximate; 3D asset pending.'},
{name:'Joe Louis Fist / Monument to Joe Louis',lat:42.3285,lon:-83.0470,start:1986,end:2045,source:'https://en.wikipedia.org/wiki/Monument_to_Joe_Louis',status:'Sculpture anchor approximate; licensed mesh/scan needed.'},
{name:'Veterans Memorial Building',lat:42.3260,lon:-83.0496,start:1950,end:2045,source:'https://www.historicdetroit.org/buildings/veterans-memorial-building',status:'Veterans Memorial Building on riverfront. Anchor approximate; GLB needed.'},
{name:'Ford Auditorium (demolished)',lat:42.3260,lon:-83.0420,start:1956,end:2011,source:'https://www.historicdetroit.org/buildings/ford-auditorium',status:'Demolished in 2011. Historic geometry requires archived drawings; not visible in modern era.'},
{name:'Ambassador Bridge',lat:42.311944,lon:-83.074111,start:1929,end:2045,source:'https://en.wikipedia.org/wiki/Ambassador_Bridge',status:'A mapped 2026 bridge geometry is not yet certified: anchor marks site, not a full rendered span.'},
{name:'Gordie Howe International Bridge',lat:42.2880,lon:-83.0975,start:2026,end:2045,source:'https://www.gordiehoweinternationalbridge.com/',status:'Opened in 2026. Detailed verified bridge deck geometry not yet imported; marker shows site only.'},
{name:'Detroit-Windsor Tunnel (subsurface)',lat:42.3245,lon:-83.040056,start:1930,end:2045,source:'https://en.wikipedia.org/wiki/Detroit%E2%80%93Windsor_Tunnel',status:'Tunnel below river; entrance marker only. No surface bridge fabricated.'},
{name:'MacArthur Bridge — Belle Isle',lat:42.341694,lon:-82.997861,start:1923,end:2045,source:'https://en.wikipedia.org/wiki/MacArthur_Bridge_(Detroit)',status:'Mapped centerlines do not verify the historic or current bridge deck geometry.'},
{name:'DTE Energy / Detroit Edison downtown campus',lat:42.3346,lon:-83.0605,start:1900,end:2045,source:'https://en.wikipedia.org/wiki/DTE_Energy',status:'Approximate downtown campus marker; exact historical building identification still pending.'},
];
function addAnchors(group,year){let count=0;for(const a of ANCHORS){if(year<a.start||year>a.end)continue;const [x,z]=xy(a.lat,a.lon);const pin=labelSprite(a.name);pin.position.set(x,Math.max(2.0,year>=2024?2.5:1.2),z);pin.userData.feature={name:a.name,start:a.start,end:a.end,source:a.source,location_certainty:a.status};group.add(pin);count++;}return count;}
function future(group,m){const rnd=seeded(2045);for(let i=0;i<5;i++){let [bx,bz]=xy(42.342,-83.028);let x=bx+(rnd()-.5)*8,z=bz+(rnd()-.5)*12;const h=7+rnd()*2.5;const ob=new T.Mesh(new T.CylinderGeometry(.45,.78,h,12),m.blueglass);ob.position.set(x,h/2,z);ob.name='2045: future-inspired construction';group.add(ob);}}
export function createGeoCity(scene,year,pack,settings,regions,islandData=null,riverData=null,historicPack=null,localEdits=[]){if(!isYear(year))throw Error('Invalid geography year');const group=new T.Group();group.name='Detroit actual geographic observer '+year;scene.add(group);const m=createMaterials();const finish=addGISGroundFinish(m.grass,regions,year,settings?.quality);const ground=new T.Mesh(new T.PlaneGeometry(710,650),m.grass);ground.rotation.x=-Math.PI/2;ground.position.y=-.12;ground.receiveShadow=true;group.add(ground);
 // Water is rendered from the cached NHD polygons before the city:
 // topology is repaired, clipped and rendered double-sided, with an explicit
 // verified Belle Isle land-hole instead of a synthetic oval.
 const hydro=renderHydrography(group,regions,m,year,islandData,riverData,localEdits);
 const mappedRoads=year>=2024?drawVisibleMappedRoads(group,regions,m,hydro.isWetProjected):{features:0,segments:0,bridges:0,skippedWater:0,sidewalks:0};
 let roads=mappedRoads.features,buildings=0;
 for(const area of regions)buildings+=addBuildings(group,area.buildings||[],m,year);
 const detailRegions=regions.map(r=>({...r,buildings:(r.buildings||[]).filter(b=>!landmarkExclusion(b.p,year))}));
 const details=addFacadeDetails(group,detailRegions,m,year,settings?.quality);
 const urban=addMappedStreetDetail(group,regions,year,settings?.quality,hydro.isWetProjected);
 const riverfront=addModernRiverfront(group,m,year,settings?.quality);
 const historicMassingCount=addEraMassing(group,historicPack,year,settings?.quality);
 const localEditCount=addLocalAnnotations(group,localEdits,year);

 if(year===2045)future(group,m);
 const landmarkCount=addAnchors(group,year);
 return {group,materials:m,landmarkCount,buildingCount:buildings,roadCount:roads,roadSurfaceCount:mappedRoads.segments,roadBridgeCount:mappedRoads.bridges,roadWaterSkipped:mappedRoads.skippedWater,streetDetailCount:urban.stripes,streetlights:urban.lights,waterCount:hydro.waterMeshes,waterDataCount:hydro.waterFeatures,riverVerified:hydro.riverVerified,riverSource:hydro.riverSource,shorelineGuideColumns:hydro.landCorrections?.mainlandGuideColumns??0,waterArea:hydro.triangleArea,waterMaskSize:hydro.waterMaskSize,waterCrossSections:hydro.crossSections,belleIslandVerified:hydro.belleIslandVerified,treeCount:hydro.trees,historicMassingCount,localEditCount,waterfrontAnchors:riverfront.anchors,waterfrontAmenities:riverfront.amenities,promenadeSegments:riverfront.promenadeSegments,promenadeTrees:riverfront.promenadeTrees,landCorrections:hydro.landCorrections||null,windowCount:details.windows,roofCount:details.roofs,trimCount:details.trims,pilasterCount:details.pilasters,buildingsDetailed:details.buildingsDetailed,year,historyIncomplete:year<2024};}
export function destroyGeoCity(scene,city){if(!city)return;scene.remove(city.group);city.group.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.isSprite){o.material?.map?.dispose();o.material?.dispose();}});for(const mat of Object.values(city.materials)){mat.map?.dispose?.();mat.dispose?.();}for(const mat of city.group.userData.riverfrontPrivateMaterials||[])mat.dispose?.();for(const mat of city.group.userData.urbanMaterials||[])mat.dispose?.();}
