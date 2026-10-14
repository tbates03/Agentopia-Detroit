// Geometry is illustrative except approximate landmark anchors from the archived Detroit era pack.
export const ORIGIN = {lat:42.329, lon:-83.052};
export const METERS_PER_UNIT = 32;
export function xy(lat,lon) {
  const latitude = Number(lat), longitude = Number(lon);
  if(!Number.isFinite(latitude)||!Number.isFinite(longitude)) throw Error('Invalid GPS anchor');
  // Three.js has +X east, +Z SOUTH (not north): preserves compass handedness.
  return [(longitude-ORIGIN.lon)*111194.9266*Math.cos(ORIGIN.lat*Math.PI/180)/METERS_PER_UNIT,
    (ORIGIN.lat-latitude)*111194.9266/METERS_PER_UNIT];
}
export function shore(x) {
  // Hand-sculpted, approximate waterfront curve; not an official Detroit shoreline polygon.
  const points=[[-170,-99],[-94,-72],[-65,-49],[-45,-35],[-28,-21],[-8,-12],[15,-12],[42,-14],[82,-20],[170,-24]];
  for(let i=1;i<points.length;i++) if(x<=points[i][0]){let a=points[i-1],b=points[i],t=(x-a[0])/(b[0]-a[0]);t=Math.max(0,Math.min(1,t));return a[1]+(b[1]-a[1])*t;}
  return -24;
}
export function pointOnLand(x,z,padding=0){return z>=shore(x)+padding;}
export function seeded(n){let x=(n|0)^0x9e3779b9;return ()=>{x^=x<<13;x^=x>>>17;x^=x<<5;return (x>>>0)/4294967296;};}
