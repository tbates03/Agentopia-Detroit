/* Pure chronology: no architecture before documentary start; no demolished structures after end. */
export const HISTORIC_SCHEMA='agentopia.detroit.historic-waterfront.v1';
export function activeLandmarks(pack,year){
 if(!pack||pack.schema!==HISTORIC_SCHEMA||!Array.isArray(pack.landmarks)||!Number.isInteger(year))return [];
 return pack.landmarks.filter(v=>v&&Number.isInteger(v.from)&&Number.isInteger(v.through)&&year>=v.from&&year<=v.through&&v.source?.startsWith('https://'));
}
export function historicalPhase(id,year){
 if(id==='penobscot')return year<1905?'absent':year<1916?'1905-original':year<1928?'1916-addition':'1928-greater-tower';
 if(id==='rencen')return year<1976?'absent':year<1981?'five-tower-core':'seven-tower-complex';
 if(id==='ford')return year<1956?'absent':year>2010?'demolished':'auditorium-standing';
 return 'documented-era';
}
