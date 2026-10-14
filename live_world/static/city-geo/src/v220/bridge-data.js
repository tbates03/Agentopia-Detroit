/* Agentopia Detroit 2.0.20 — georeferenced bridge registry (no runtime writes).
 * Endpoints are alignment approximations derived from independently referenced
 * bridge midpoints, physical lengths and their banks; NOT engineering surveys.
 * Coordinate order for endpoints: [latitude, longitude].
 * Date-stamped behavior is grounded in sources listed below.
 */
export const BRIDGE_REGISTRY = Object.freeze([
 {
  id:'belle_1889',name:'Original Belle Isle Bridge (1889–1915)',kind:'historic-truss',
  started:1889,ended:1915,openYear:1889,constructionYear:null,
  endpoints:[[42.34480,-83.00126],[42.34028,-82.99591]],
  midpoint:[42.34254,-82.998585],reportedLengthM:668,
  deckWidthM:13.4,deckClearanceM:8,lanes:2,
  spanCount:17,approximate:true,
  source:'https://historicdetroit.org/buildings/douglas-macarthur-bridge',
  note:'Illustrative iron-and-wood swing/truss crossing. Opened 1889; destroyed by fire April 1915. Not a measured 1889 replica.'
 },
 {
  id:'macarthur',name:'Douglas MacArthur Bridge — Belle Isle',kind:'open-spandrel-arch',
  started:1923,ended:2045,openYear:1923,constructionYear:null,
  endpoints:[[42.34480,-83.00126],[42.34028,-82.99591]],
  midpoint:[42.34254,-82.998585],reportedLengthM:668,
  deckWidthM:25.9,deckClearanceM:9.1,lanes:5,spanCount:19,
  approximate:true,
  source:'https://www.michigan.gov/dnr/-/media/Project/Websites/dnr/Documents/PRD/BI-archive/Belle-multimodal/BelleIsleMobilityStudy2024-Ch2-Existing-Conditions.pdf',
  note:'1923 concrete open-spandrel arch crossing; 19 arches, 2,193 ft long, five traffic lanes. Anchor and deck alignment approximate.'
 },
 {
  id:'ambassador',name:'Ambassador Bridge',kind:'suspension',
  started:1929,ended:2045,openYear:1929,constructionYear:null,
  endpoints:[[42.32100,-83.08030],[42.30320,-83.06780]],
  midpoint:[42.31210,-83.07405],reportedLengthM:2286,mainSpanM:563.9,
  deckWidthM:16.76,deckClearanceM:46,lanes:4,towerHeightM:118,
  approximate:true,
  source:'https://historicdetroit.org/buildings/ambassador-bridge',
  note:'1929 suspension bridge, 1,850-ft central span and 7,490-ft total length. Steel towers, twin cables, hangers and stiffening truss. Approaches approximate.'
 },
 {
  id:'gordie',name:'Gordie Howe International Bridge',kind:'cable-stayed',
  started:2024,ended:2045,openYear:2026,constructionYear:2024,
  endpoints:[[42.29940,-83.10340],[42.27760,-83.09220]],
  midpoint:[42.28850,-83.09780],reportedLengthM:2500,mainSpanM:853,
  deckWidthM:31,deckClearanceM:46,lanes:6,towerHeightM:220,stayCount:216,
  approximate:true,
  source:'https://gordiehoweinternationalbridge.com/gordie-howe-international-bridge-deck-connection-complete/',
  openingSource:'https://gordiehoweinternationalbridge.com/celebrating-the-gordie-howe-international-bridge/',
  note:'2024 deck connected but NOT open to public. Traffic opened July 27, 2026. 853-m main span, 220-m A-shaped pylons, 216 stay cables. Alignment approximate.'
 }
]);
const RAD=Math.PI/180;
export function gpsDistanceM(a,b){
 const lat=(a[0]+b[0])/2*RAD;
 return Math.hypot((b[0]-a[0])*111194.9266,(b[1]-a[1])*111194.9266*Math.cos(lat));
}
export function bridgeState(id,year){
 const b=BRIDGE_REGISTRY.find(x=>x.id===id);
 if(!b||!Number.isFinite(year)||year<b.started||year>b.ended)return 'absent';
 if(b.constructionYear&&year<b.openYear)return 'construction';
 return 'open';
}
export function bridgesInYear(year){
 return BRIDGE_REGISTRY.filter(b=>bridgeState(b.id,year)!=='absent');
}
export function bridgeSummary(year){
 return bridgesInYear(year).map(b=>({id:b.id,name:b.name,status:bridgeState(b.id,year),type:b.kind,source:b.source}));
}
