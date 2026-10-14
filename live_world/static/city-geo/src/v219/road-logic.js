/* Pure road geometry shared by drawing and standalone QA tests. Three.js terrain
 * coordinates: X east, Z south, Y up. Road quads MUST have upward normals. */
export function widthForRoad(type){
 const t=String(type||'').toLowerCase();
 if(t==='motorway'||t==='trunk')return .75;
 if(t==='primary')return .58;
 if(t==='secondary')return .48;
 if(t==='tertiary')return .37;
 if(t==='residential'||t==='living_street')return .31;
 if(['pedestrian','footway','cycleway','path'].includes(t))return .13;
 return .25;
}
export function buildUpwardQuad(a,b,width,y){
 const dx=b[0]-a[0],dz=b[1]-a[1],len=Math.hypot(dx,dz);
 if(!Number.isFinite(len)||len<.001||len>100)return null;
 const nx=-dz/len*width/2,nz=dx/len*width/2;
 // RIGHT, LEFT, NEXT LEFT gives +Y facing triangles for eastbound roads.
 const aR=[a[0]-nx,y,a[1]-nz],aL=[a[0]+nx,y,a[1]+nz];
 const bL=[b[0]+nx,y,b[1]+nz],bR=[b[0]-nx,y,b[1]-nz];
 return [...aR,...aL,...bL,...aR,...bL,...bR];
}
export function normalY(vertices){
 const a=[vertices[0],vertices[1],vertices[2]],b=[vertices[3],vertices[4],vertices[5]],c=[vertices[6],vertices[7],vertices[8]];
 const ux=b[0]-a[0],uz=b[2]-a[2],vx=c[0]-a[0],vz=c[2]-a[2];
 return uz*vx-ux*vz;
}
export function shouldSkipRoad(bridge,tunnel,midpoint,isWet){
 if(tunnel)return true;
 return !bridge&&typeof isWet==='function'&&isWet(midpoint[0],midpoint[1]);
}
