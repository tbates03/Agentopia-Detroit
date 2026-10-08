#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
DT = WORLD / "digital_twin"
VERSION = "1.2.0"

MARKET = {
  "epoch": "2026-09",
  "desktop_os_us": {"Windows":64.45,"macOS":26.51,"ChromeOS":5.34,"Linux":3.69,"Other":0.01},
  "mobile_os_us": {"iOS":53.55,"Android":46.26,"Other":0.19},
  "pc_vendor_us_2q26": {"HP":24.4,"Dell":21.2,"Apple":18.8,"Lenovo":18.5,"Acer":6.9,"Other":10.1},
  "mobile_vendor_us_sep26": {"Apple":53.58,"Samsung":28.11,"Xiaomi":5.89,"Motorola":3.49,"Google":3.16,"Other":5.77},
  "notes": [
    "StatCounter September 2026 U.S. OS baseline; OS X + macOS combined for simulation.",
    "Omdia U.S. PC shipments 2Q26 used for PC-vendor weighting.",
    "Detroit ARPA reporting indicates roughly 30% of households lack broadband or computing devices; used only as a coarse access baseline.",
  ],
}

INFRA = [
  {"id":"DT-ENERGY","sector":"energy","inspiration":"DTE Energy regional electric/gas services","criticality":95,"zones":["enterprise_it","operations_dmz","ot_control","field_assets","safety"],"synthetic":True},
  {"id":"DT-WATER","sector":"water_wastewater","inspiration":"GLWA/DWSD regional/local water and wastewater services","criticality":100,"zones":["enterprise_it","operations_dmz","plant_control","pump_stations","field_telemetry","safety"],"synthetic":True},
  {"id":"DT-TRAFFIC","sector":"traffic_mobility","inspiration":"Detroit traffic signals and SMART MODES","criticality":80,"zones":["enterprise_it","mobility_cloud","edge_intersections","signal_control"],"synthetic":True},
  {"id":"DT-TRANSIT","sector":"public_transit","inspiration":"DDOT/QLINE-style transit operations","criticality":75,"zones":["enterprise_it","dispatch","vehicle_network","stations","fare_services"],"synthetic":True},
  {"id":"DT-CITY","sector":"municipal_it","inspiration":"City of Detroit DoIT services","criticality":90,"zones":["identity","data_center","enterprise_wan","department_lans","cloud_services","public_web"],"synthetic":True},
  {"id":"DT-HEALTH","sector":"healthcare","inspiration":"synthetic Detroit healthcare ecosystem","criticality":100,"zones":["identity","clinical_it","medical_iot","guest","backup","vendor_access"],"synthetic":True},
  {"id":"DT-AUTO","sector":"automotive_manufacturing","inspiration":"Detroit-region manufacturing ecosystem","criticality":90,"zones":["enterprise_it","plant_dmz","mes","plc_cells","robots","quality","safety"],"synthetic":True},
  {"id":"DT-TELCO","sector":"telecommunications","inspiration":"synthetic metro telecom/cellular infrastructure","criticality":90,"zones":["core","access","mobile_edge","customer","management"],"synthetic":True},
  {"id":"DT-PUBLIC-SAFETY","sector":"public_safety","inspiration":"synthetic emergency/public-safety technology","criticality":100,"zones":["dispatch","records","radio","mobile_units","evidence"],"synthetic":True},
  {"id":"DT-MICH-CENTRAL","sector":"mobility_innovation","inspiration":"Michigan Central mobility innovation district","criticality":70,"zones":["enterprise","labs","test_track","iot","guest"],"synthetic":True},
]

VENDOR_CATALOG = {
  "endpoint":["HP","Dell","Lenovo","Apple","ASUS","Acer","Microsoft"],
  "network":["Cisco","HPE Aruba","Juniper","Fortinet","Palo Alto Networks","Ubiquiti"],
  "server":["HPE","Dell","Lenovo","Supermicro"],
  "ot":["Rockwell Automation","Siemens","Schneider Electric","ABB","Honeywell","Emerson"],
  "security":["Cisco","Fortinet","Palo Alto Networks","Microsoft","CrowdStrike","SentinelOne","Suricata-compatible NIDS","Zeek-compatible NSM"],
}

THREATS = [
  ("phishing",0.18),("deepfake_social_engineering",0.08),("credential_abuse",0.13),("ransomware",0.11),
  ("worm",0.06),("virus_trojan",0.07),("apt_campaign",0.09),("zero_day",0.07),("supply_chain",0.05),
  ("ddos",0.06),("ot_disruption",0.05),("insider",0.03),("mobile_malware",0.02),
]
CONTROLS = ["NGFW","network_segmentation","NIDS","HIDS_EDR","SIEM","MFA","PAM","immutable_backup","patch_management","vulnerability_management","email_security","DMARC","NAC","DLP","application_allowlisting","OT_DMZ","asset_inventory","security_awareness","incident_response","threat_intelligence"]
FRAMEWORKS = {
 "healthcare":["HIPAA Security Rule","NIST CSF 2.0","CIS Controls","ISO/IEC 27001"],
 "energy":["NERC CIP","NIST SP 800-82","NIST CSF 2.0","CIS Controls"],
 "water_wastewater":["NIST SP 800-82","NIST CSF 2.0","CIS Controls"],
 "public_safety":["CJIS-aligned controls","NIST CSF 2.0","CIS Controls"],
 "default":["NIST CSF 2.0","CIS Controls","ISO/IEC 27001"],
}


def now(): return datetime.now(timezone.utc).isoformat()
def load(p, d):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except Exception: return d

def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True); t=p.with_suffix(p.suffix+".tmp"); t.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8"); t.replace(p)
def append(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a",encoding="utf-8") as f:f.write(json.dumps(obj,ensure_ascii=False)+"\n")
def rng_for(key): return random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16],16))
def weighted(rng, mapping):
    x=rng.random()*sum(mapping.values()); s=0
    for k,v in mapping.items():
        s+=v
        if x<=s:return k
    return next(reversed(mapping))


def ensure_base():
    DT.mkdir(parents=True, exist_ok=True)
    save(DT/"market_model.json", MARKET)
    save(DT/"infrastructure.json", {"version":VERSION,"scope":"public-data-informed synthetic Detroit digital twin","safety":"No real internal topology, addresses, credentials, or exploit payloads.","nodes":INFRA,"vendor_catalog":VENDOR_CATALOG})
    save(DT/"threat_catalog.json", {"simulation_only":True,"no_payload_generation":True,"threats":[x[0] for x in THREATS],"controls":CONTROLS,"frameworks":FRAMEWORKS})
    teams={
      "Morbeious":{"faction":"Obsidian Network","preferred_operator_os":["Kali Linux","Parrot Security OS"],"roles":["recon_hunter","identity_hunter","vulnerability_hunter","malware_ransomware_operator","social_engineering_deepfake_operator","ot_intrusion_simulator","threat_intel"],"execution":"Agentopia cyber range only"},
      "TGOT":{"faction":"ThAI Guardians","preferred_operator_os":["Kali Linux","Parrot Security OS"],"roles":["soc_hunter","network_blue_team","endpoint_blue_team","purple_team","grc_compliance","ot_defender","dfir","threat_intel"],"execution":"defense/audit and simulated purple-team validation"},
    }
    save(DT/"cyber_teams.json", teams)
    state=load(DT/"state.json",{})
    if not state:
      state={"version":VERSION,"tick":0,"last_checkpoint":None,"created_at":now(),"campaigns":0,"blocked":0,"detected":0,"successful":0,"resilience":65.0}
      save(DT/"state.json",state)
    assets=load(DT/"infrastructure_state.json",{})
    if not assets:
      assets={}
      for n in INFRA:
        r=rng_for(n["id"])
        controls={c:round(r.uniform(.35,.88),2) for c in CONTROLS}
        assets[n["id"]]={"sector":n["sector"],"criticality":n["criticality"],"patch_level":round(r.uniform(55,90),1),"controls":controls,"open_vulnerabilities":[],"last_audit":None}
      save(DT/"infrastructure_state.json",assets)
    sync_citizens()


def sync_citizens():
    out=load(DT/"citizen_devices.json",{})
    if not isinstance(out,dict):out={}
    root=WORLD/"persona"
    if not root.exists():return
    for p in sorted(root.iterdir(),key=lambda x:x.name.casefold()):
      if not p.is_dir() or p.name in out:continue
      r=rng_for("device:"+p.name)
      phone_os=weighted(r,MARKET["mobile_os_us"])
      if phone_os=="iOS":phone_vendor="Apple"
      elif phone_os=="Android":phone_vendor=weighted(r,{"Samsung":28.11,"Xiaomi":5.89,"Motorola":3.49,"Google":3.16,"Other":5.77})
      else:phone_vendor="Other"
      has_pc=r.random()<.70
      pc=None
      if has_pc:
        pc_os=weighted(r,MARKET["desktop_os_us"])
        pc_vendor=weighted(r,MARKET["pc_vendor_us_2q26"])
        if pc_vendor=="Other":pc_vendor=r.choice(["ASUS","Acer","Microsoft","Other"])
        pc={"os":pc_os,"vendor":pc_vendor,"managed":r.random()<.42,"patch_age_days":r.randint(0,120)}
      out[p.name]={"smartphone":{"os":phone_os,"vendor":phone_vendor,"patch_age_days":r.randint(0,90)},"computer":pc,"home_broadband":r.random()<.70,"router_vendor":r.choice(["ASUS","TP-Link","Netgear","Eero","Ubiquiti","ISP Gateway"]) if r.random()<.70 else None}
    save(DT/"citizen_devices.json",out)


def add_vulns(assets,r,year):
    seq=load(DT/"vuln_sequence.json",{"n":0})
    for aid,a in assets.items():
      # patchable known vuln appears occasionally; zero-day less often
      if r.random()<.22:
        seq["n"]+=1; zero=r.random()<.14
        v={"id":f"ATV-{year}-{seq['n']:06d}","synthetic":True,"zero_day":zero,"severity":round(r.uniform(5.0,9.9),1),"exploitability":round(r.uniform(.35,.9),2),"patch_available":not zero,"class":r.choice(["auth_bypass","memory_corruption","insecure_service","misconfiguration","credential_exposure","supply_chain_component"]),"payload":"NOT GENERATED - simulation only","created_at":now()}
        a["open_vulnerabilities"].append(v)
    save(DT/"vuln_sequence.json",seq)


def patch_cycle(assets,r):
    for a in assets.values():
      pm=a["controls"].get("patch_management",.5); a["patch_level"]=min(100,round(a["patch_level"]+r.uniform(.2,2.2)*pm,1))
      keep=[]
      for v in a["open_vulnerabilities"]:
        if v.get("zero_day") and r.random()<.12: v["zero_day"]=False; v["patch_available"]=True
        if v.get("patch_available") and r.random()<pm*.35: continue
        keep.append(v)
      a["open_vulnerabilities"]=keep


def tick(checkpoint):
    ensure_base(); sync_citizens()
    state=load(DT/"state.json",{}); assets=load(DT/"infrastructure_state.json",{})
    key=json.dumps(checkpoint,sort_keys=True)
    if key==state.get("last_checkpoint"):return state
    year=int(checkpoint.get("year",2045)) if isinstance(checkpoint,dict) else 2045
    r=rng_for(f"{key}:{state.get('tick',0)}")
    add_vulns(assets,r,year); patch_cycle(assets,r)
    # one abstract campaign per checkpoint with probability; no exploit execution
    if r.random()<.72:
      threat=weighted(r,dict(THREATS)); target_id=r.choice(list(assets)); target=assets[target_id]
      vulns=target.get("open_vulnerabilities",[]); vuln=max(vulns,key=lambda v:v.get("severity",0),default=None)
      defense=sum(target["controls"].values())/max(1,len(target["controls"]))
      attack_skill=.72 + (.10 if threat in {"apt_campaign","zero_day","ransomware"} else 0)
      exploit_bonus=(vuln.get("exploitability",0)*.22 if vuln else 0)
      success_p=max(.04,min(.92,attack_skill+exploit_bonus-defense*.78))
      success=r.random()<success_p
      detect_p=max(.08,min(.97,(target["controls"].get("SIEM",.5)+target["controls"].get("NIDS",.5)+target["controls"].get("HIDS_EDR",.5))/3*.92))
      detected=r.random()<detect_p
      event={"time":now(),"checkpoint":checkpoint,"actor":"Morbeious / Obsidian Network","target":target_id,"sector":target["sector"],"threat":threat,"vulnerability":vuln["id"] if vuln else None,"zero_day":bool(vuln and vuln.get("zero_day")),"result":"success" if success else "blocked","detected":detected,"simulation_only":True,"exploit_payload_generated":False}
      if threat=="ransomware" and success:event["impact"]={"systems_encrypted_percent":r.randint(8,72),"service_disruption":"simulated"}
      elif threat=="deepfake_social_engineering":event["impact"]={"trust_manipulation":"simulated","identity_verification_pressure":True}
      elif threat=="ot_disruption" and success:event["impact"]={"process_disruption":"simulated","safety_systems":"not bypassed by simulator"}
      append(DT/"cyber_events.jsonl",event)
      state["campaigns"]=int(state.get("campaigns",0))+1
      if success:state["successful"]=int(state.get("successful",0))+1
      else:state["blocked"]=int(state.get("blocked",0))+1
      if detected:state["detected"]=int(state.get("detected",0))+1
      # TGOT blue/purple response improves one or more controls and records an audit.
      improvements=r.sample(CONTROLS,k=2)
      for c in improvements:target["controls"][c]=min(1.0,round(target["controls"].get(c,.5)+r.uniform(.01,.05),2))
      frameworks=FRAMEWORKS.get(target["sector"],FRAMEWORKS["default"])
      audit={"time":now(),"actor":"TGOT / ThAI Guardians","target":target_id,"trigger":"post-incident purple-team review" if success else "preventive validation","frameworks":frameworks,"improved_controls":improvements,"simulation_only":True}
      append(DT/"audit_events.jsonl",audit)
      target["last_audit"]=audit["time"]
    state["tick"]=int(state.get("tick",0))+1; state["last_checkpoint"]=key; state["last_tick_at"]=now()
    avg=sum(sum(a["controls"].values())/len(a["controls"]) for a in assets.values())/len(assets)
    state["resilience"]=round(avg*100,1)
    save(DT/"infrastructure_state.json",assets); save(DT/"state.json",state)
    return state


def status():
    ensure_base(); s=load(DT/"state.json",{}); devices=load(DT/"citizen_devices.json",{})
    print("Agentopia Detroit Digital Twin v"+VERSION)
    print("Citizens modeled:",len(devices)); print("Twin ticks:",s.get("tick",0)); print("Campaigns:",s.get("campaigns",0)); print("Blocked:",s.get("blocked",0)); print("Detected:",s.get("detected",0)); print("Successful simulated incidents:",s.get("successful",0)); print("Resilience:",s.get("resilience",0))

p=argparse.ArgumentParser();p.add_argument("command",choices=["init","tick","status"]);p.add_argument("--checkpoint",default=None);a=p.parse_args()
if a.command=="init":ensure_base();status()
elif a.command=="status":status()
else:
    cp=load(Path(a.checkpoint) if a.checkpoint else WORLD/"checkpoint.json",{}); print(json.dumps(tick(cp),indent=2))
