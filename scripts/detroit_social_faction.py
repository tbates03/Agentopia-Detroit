#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "data" / "detroit_persistent"
SOCIAL = WORLD / "social"
PULSE_LOG = SOCIAL / "pulses.ndjson"  # real UTC/history sidecar; excluded from Agentopia cleanup
VERSION = "1.4.5"
_LOCK = threading.Lock()
_SEEN: set[str] = set()

GUARDIAN_TOPICS = [
    "simulated endpoint telemetry and which defensive control deserves attention first",
    "patch posture and segmentation across the fictional Detroit range",
    "deepfake-assisted social engineering and citizen verification controls",
    "simulated NIDS/HIDS signals and what evidence deserves escalation",
    "identity and access controls in the fictional mobility district",
    "incident-response readiness, recovery evidence, and lessons learned",
    "privacy, AI governance, and digital-sovereignty controls for Detroit citizens",
]
OBSIDIAN_TOPICS = [
    "the synthetic Detroit attack surface and the next safe research hypothesis",
    "whether fictional identity controls resist simulated credential abuse",
    "defender response patterns from the last Agentopia cyber exercise",
    "a simulation-only social-engineering exercise against fictional personas",
    "synthetic OT telemetry and which defensive assumption should be tested next",
    "how deception and defender visibility change a simulated adversary decision",
    "what the blue team can observe during a controlled synthetic reconnaissance exercise",
]
CITY_THEMES = [
    "Detroit's technology changes",
    "neighborhood life this week",
    "the balance between innovation and privacy",
    "what people are building around the city",
    "how work and community are changing",
    "which public event actually feels worth attending",
    "what makes the city feel more connected lately",
    "how people are adapting to local AI and autonomous systems",
]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _tail_jsonl(path: Path, n: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            pass
    return out


def _append_ndjson(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_seen() -> None:
    global _SEEN
    if _SEEN or not PULSE_LOG.exists():
        return
    for row in _tail_jsonl(PULSE_LOG, 5000):
        key = str(row.get("key") or "")
        if key:
            _SEEN.add(key)


def _reserve(key: str, **meta: Any) -> bool:
    with _LOCK:
        _load_seen()
        if key in _SEEN:
            return False
        _SEEN.add(key)
        _append_ndjson(PULSE_LOG, {"key": key, **meta})
        return True


def _stable_int(*parts: Any) -> int:
    raw = "|".join(str(x) for x in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16)


def _faction_state() -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    raw = _read_json(WORLD / "factions.json", {})
    src = raw.get("factions", {}) if isinstance(raw, dict) else {}
    factions: dict[str, dict[str, Any]] = {}
    member_to_id: dict[str, str] = {}
    if isinstance(src, dict):
        for fid, rec in src.items():
            if not isinstance(rec, dict):
                continue
            row = dict(rec)
            row["id"] = fid
            factions[str(fid)] = row
            for name in row.get("members") or []:
                member_to_id[str(name)] = str(fid)
    return factions, member_to_id


def _active_names(world_name: str = "detroit_persistent") -> list[str]:
    world = ROOT / "data" / world_name
    view = world / ".active_persona_view"
    base = view if view.exists() else world / "persona"
    if not base.exists():
        return []
    return sorted([p.name for p in base.iterdir() if p.is_dir() or p.is_symlink()], key=str.casefold)


def _latest_profile(name: str, year: int) -> dict[str, Any]:
    pdir = WORLD / "persona" / name / "profile"
    exact = pdir / f"year={year}.json"
    if exact.exists():
        return _read_json(exact, {})
    files = sorted(pdir.glob("year=*.json")) if pdir.exists() else []
    return _read_json(files[-1], {}) if files else {}


def _persona_context(name: str, year: int) -> dict[str, str]:
    p = _latest_profile(name, year)
    pos = p.get("position") if isinstance(p.get("position"), dict) else {}
    role = str(pos.get("role") or pos.get("title") or "").strip()
    org = str(pos.get("organization") or pos.get("company") or "").strip()
    job = " @ ".join(x for x in (role, org) if x) or "Detroit resident"
    motivation = str(p.get("core_motivation") or "").strip()
    values = str(p.get("values") or "").strip()
    intro = str(p.get("brief_introduction") or p.get("details") or "").strip()
    return {
        "job": job[:120],
        "motivation": motivation[:180],
        "values": values[:160],
        "intro": intro[:180],
    }


def _event_names() -> list[str]:
    rows = _tail_jsonl(WORLD / "public_events.jsonl", 40)
    out: list[str] = []
    for row in reversed(rows):
        nm = str(row.get("event_name") or row.get("name") or row.get("title") or "").strip()
        if nm and nm not in out:
            out.append(nm)
        if len(out) >= 8:
            break
    return out


def _incoming_previous_slot(agent: Any) -> list[str]:
    try:
        prev = str(agent.clock.prev_contact_slot())
    except Exception:
        return []
    sig = WORLD / "persona" / agent.name / "contact" / "sig.jsonl"
    names: list[str] = []
    for row in _tail_jsonl(sig, 300):
        if str(row.get("time") or "") != prev:
            continue
        if str(row.get("to") or "") != agent.name:
            continue
        frm = str(row.get("from") or "").strip()
        if frm and frm != agent.name and frm not in names:
            names.append(frm)
    return names


def _topic(fid: str, week: int, slot: int, name: str = "") -> str:
    topics = GUARDIAN_TOPICS if fid == "thai_guardians" else OBSIDIAN_TOPICS
    idx = _stable_int(fid, week, slot, name) % len(topics)
    return topics[idx]


def _directive_context(name: str, year: int) -> str:
    c = _persona_context(name, year)
    bits = [f"Your current work/role: {c['job']}."]
    if c["motivation"]:
        bits.append(f"Your core motivation: {c['motivation']}.")
    if c["values"]:
        bits.append(f"Your values: {c['values']}.")
    return "\n".join(bits)


def _faction_directive(agent: Any, fid: str, faction: dict[str, Any]) -> str:
    t = agent.clock.get_time()
    name = agent.name
    leader = str(faction.get("leader") or "")
    fname = str(faction.get("name") or fid)
    topic = _topic(fid, int(t.week), int(t.slot), name)
    incoming = _incoming_previous_slot(agent)
    incoming_line = f"Recent incoming teammates to answer first: {', '.join(incoming[:4])}." if incoming else "No teammate reply is currently mandatory."
    safety = (
        "Your faction is defensive/whitehat. Focus on evidence, monitoring, patching, identity, segmentation, "
        "incident response, resilience, governance, and protection of fictional Agentopia systems."
        if fid == "thai_guardians"
        else "Your faction is an adversary team inside the FICTIONAL Agentopia cyber range only. Keep discussion high-level and simulation-only. Do not provide real exploit payloads, credentials, malware, or instructions against real systems."
    )
    leader_line = (
        "As leader, ANSWER actual crew messages, challenge weak assumptions, delegate a distinct next step, and request evidence. Do not simply collect status reports."
        if name == leader
        else "As a member, answer the leader when they wrote you, report evidence specific to your own work, and also build peer-to-peer relationships."
    )
    return f"""## Agentopia Social & Faction Directive v{VERSION}
You are part of {fname}. This must feel like a living team, not a scripted status bot.
{_directive_context(name, int(t.year))}
Current faction theme: {topic}.
{incoming_line}
- {leader_line}
- {safety}
- Send/reply with at least one UNIQUE message when socially appropriate.
- Reference your own role, current goal, evidence, prior message, or public event when possible.
- Never copy a generic faction sentence used by another member.
- Vary recipient, wording, and purpose across slots: reply, ask, delegate, disagree, recommend, invite, or follow up.
- If arranging a meeting, use propose_joint_activity rather than merely saying you should meet.
"""


def _neutral_directive(agent: Any) -> str:
    t = agent.clock.get_time()
    c = _persona_context(agent.name, int(t.year))
    events = _event_names()
    event = events[_stable_int(agent.name, t.week, t.slot) % len(events)] if events else "a Detroit public event"
    return f"""## Agentopia Social Directive v{VERSION}
Agentopia is a living society. Speak like this specific person, not a generic NPC.
Your work/role: {c['job']}.
Your current motivation: {c['motivation'] or 'live a meaningful week consistent with your persona'}.
A current city event you could naturally mention: {event}.
- Reply to recent incoming messages before cold outreach when appropriate.
- Send at least one meaningful message unless your persona has a strong reason to stay quiet.
- Vary recipient and subject. Do not reuse canned questions from earlier slots.
- Ground conversation in work, relationships, family, culture, neighborhood life, public events, technology, or something already remembered about the other person.
- When appropriate, propose a real joint activity.
"""


def _safe_meet(agent: Any, target: str) -> None:
    try:
        agent.meet_person(target)
    except Exception:
        pass


def _send(agent: Any, target: str, message: str, pulse_key: str) -> bool:
    if not target or target == agent.name:
        return False
    if not _reserve(pulse_key, sender=agent.name, target=target, message=message, version=VERSION):
        return False
    _safe_meet(agent, target)
    act = f"contact(message={json.dumps(message, ensure_ascii=False)}, to={json.dumps(target, ensure_ascii=False)})"
    errs: dict[str, str] = {}
    try:
        ok = bool(agent._handle_contact_action(args={"message": message, "to": target}, act=act, errs=errs))
        if ok:
            agent.n_action_this_slot = int(getattr(agent, "n_action_this_slot", 0)) + 1
        return ok
    except Exception as e:
        try:
            agent.logger.warning("[SOCIAL145] fallback contact failed %s -> %s: %s", agent.name, target, e)
        except Exception:
            pass
        return False


def _leader_fallback(agent: Any, fid: str, faction: dict[str, Any]) -> None:
    t = agent.clock.get_time()
    members = [str(x) for x in faction.get("members") or [] if str(x) and str(x) != agent.name]
    if not members:
        return
    incoming = [x for x in _incoming_previous_slot(agent) if x in members]
    target = incoming[0] if incoming else members[(_stable_int(agent.name, t.week, t.slot) % len(members))]
    topic = _topic(fid, int(t.week), int(t.slot), target)
    tc = _persona_context(target, int(t.year))
    variants_guardian = [
        "{target}, I saw your direction. Take {topic}; bring back the evidence, likely impact, and one control you would change first. Tie it to your work as {job}.",
        "{target}, let's sharpen this. On {topic}, separate what we know from what we assume. Give me one measurable defensive action and the receipt that proves it worked.",
        "{target}, own the next pass on {topic}. I want a short evidence-based recommendation, what could invalidate it, and who else on the Guardians should challenge your conclusion.",
        "{target}, follow up on {topic}. Don't give me a generic status—tell me what changed, what signal matters, and what decision you recommend next.",
    ]
    variants_obsidian = [
        "{target}, take the next synthetic-range hypothesis around {topic}. Stay inside Agentopia, tell me what the defenders could observe, and what result would falsify the hypothesis.",
        "{target}, challenge our assumptions on {topic}. Simulation only: identify one safe test, the defender signal it should create, and what lesson we would carry forward.",
        "{target}, own the next controlled exercise on {topic}. Keep it synthetic and high-level; I want the expected defender visibility and a clear stop condition.",
        "{target}, push back on our current thinking about {topic}. In the fictional range only, what evidence would make us change course, and what should the blue team be able to see?",
    ]
    pool = variants_guardian if fid == "thai_guardians" else variants_obsidian
    msg = pool[_stable_int(agent.name, target, t.week, t.slot) % len(pool)].format(target=target, topic=topic, job=tc["job"])
    _send(agent, target, msg, f"leader145|{t.year}|{t.week}|{t.slot}|{agent.name}|{target}")


def _member_fallback(agent: Any, fid: str, faction: dict[str, Any]) -> None:
    t = agent.clock.get_time()
    leader = str(faction.get("leader") or "")
    members = [str(x) for x in faction.get("members") or [] if str(x) and str(x) != agent.name]
    if not members:
        return
    incoming = _incoming_previous_slot(agent)
    if leader in incoming:
        target = leader
    elif incoming:
        target = incoming[0]
    elif int(t.slot) in (1, 3) and leader and leader != agent.name:
        target = leader
    else:
        target = members[_stable_int(agent.name, t.week, t.slot) % len(members)]
    topic = _topic(fid, int(t.week), int(t.slot), agent.name)
    c = _persona_context(agent.name, int(t.year))
    if fid == "thai_guardians":
        pool = [
            "{target}, from my work as {job}, I'm looking at {topic}. The signal I want to validate first is the one that changes the defensive decision—not just adds noise. What would you challenge?",
            "{target}, quick Guardian follow-up: {topic}. My current read is evidence-first; I want to distinguish an actual control gap from a scary-looking anomaly. What are you seeing?",
            "{target}, I can take a pass on {topic}. I'll bring back the observation, the control it maps to, and what would prove the fix actually held. Anything you want me to prioritize?",
            "{target}, something in {topic} connects to my role as {job}. Before we escalate it, I want a second set of eyes on the evidence. Can you pressure-test my assumption?",
        ]
    else:
        pool = [
            "{target}, in the synthetic range I'm examining {topic}. From my role as {job}, I want a test that creates a visible defender signal without drifting into real-world exploitation. What hypothesis would you challenge first?",
            "{target}, Obsidian range note: {topic}. Simulation only—I want to compare the expected defender visibility with what the exercise actually produces. What would count as a meaningful result?",
            "{target}, I can own a safe synthetic test around {topic}. I'll define the hypothesis, defender-visible evidence, and stop condition before we run anything. What should I pressure-test?",
            "{target}, on {topic}, I'm more interested in what the defenders can learn than in a flashy attack. Inside the fictional range only, what assumption should we try to disprove?",
        ]
    msg = pool[_stable_int(agent.name, target, t.week, t.slot) % len(pool)].format(target=target, topic=topic, job=c["job"])
    _send(agent, target, msg, f"member145|{t.year}|{t.week}|{t.slot}|{agent.name}|{target}")


def _faction_fallback(agent: Any) -> None:
    factions, member_to_id = _faction_state()
    fid = member_to_id.get(agent.name)
    if not fid or fid not in factions:
        return
    faction = factions[fid]
    leader = str(faction.get("leader") or "")
    if agent.name == leader:
        _leader_fallback(agent, fid, faction)
    else:
        _member_fallback(agent, fid, faction)


def _neutral_should_use_llm(name: str, week: int, slot: int) -> bool:
    # About one-third of neutral citizens use the 350M LLM each slot.
    # The offset changes by slot, so each citizen rotates into LLM-rich social behavior.
    bucket = _stable_int(name, week) % 3
    return ((slot + bucket) % 3) == 0


def _neutral_fast_pulse(agent: Any) -> None:
    t = agent.clock.get_time()
    incoming = _incoming_previous_slot(agent)
    names = [n for n in _active_names(getattr(agent.dm, "world", "detroit_persistent")) if n != agent.name]
    if not names:
        return
    target = incoming[0] if incoming and incoming[0] in names else names[_stable_int(agent.name, t.year, t.week, t.slot) % len(names)]
    c = _persona_context(agent.name, int(t.year))
    events = _event_names()
    event = events[_stable_int(agent.name, target, t.week, t.slot) % len(events)] if events else "one of the Detroit events this week"
    theme = CITY_THEMES[_stable_int(target, agent.name, t.slot) % len(CITY_THEMES)]
    pool = [
        "{target}, I've been thinking about {theme}. My week as {job} is giving me a different angle on it—what are you noticing?",
        "{target}, have you looked at {event}? It actually connects to something I'm seeing in my work as {job}. I'd like your take before I make up my mind about it.",
        "{target}, what has changed most in your week so far? Mine keeps circling back to {theme}, especially through my work as {job}.",
        "{target}, I could use a real conversation, not small talk. Between {event} and everything changing around Detroit, what feels important to you right now?",
        "{target}, I'm trying to decide where to put my energy this week. {event} caught my attention, but so has {theme}. What would you prioritize?",
        "{target}, something about {theme} keeps coming up for me. From where I sit as {job}, it feels less abstract than people make it sound. How does it look from your side?",
        "{target}, are you free to compare notes sometime? I'm seeing {theme} show up in everyday life, and I'm curious whether you're seeing the same thing.",
        "{target}, I don't want to just drift through the week. {event} looks interesting, and I'm also thinking about {theme}. What are you leaning toward doing?",
    ]
    msg = pool[_stable_int(agent.name, target, t.year, t.week, t.slot) % len(pool)].format(target=target, theme=theme, job=c["job"], event=event)
    _send(agent, target, msg, f"neutral145|{t.year}|{t.week}|{t.slot}|{agent.name}|{target}")


def _propose_leader_brief(agent: Any) -> None:
    t = agent.clock.get_time()
    if int(t.slot) != 1:
        return
    factions, member_to_id = _faction_state()
    fid = member_to_id.get(agent.name)
    if not fid or fid not in factions:
        return
    faction = factions[fid]
    leader = str(faction.get("leader") or "")
    if agent.name != leader:
        return
    members = [str(x) for x in faction.get("members") or [] if str(x) and str(x) != leader]
    invite = members[:4]
    if not invite:
        return
    key = f"brief145|{t.year}|{t.week}|{agent.name}"
    if not _reserve(key, sender=agent.name, invited=invite, version=VERSION):
        return
    for nm in invite:
        _safe_meet(agent, nm)
    if fid == "thai_guardians":
        activity_name = f"Guardian Brief {int(t.week):02d}"
        location = "faction/thai_guardians_hq"
        message = "Guardians, HQ briefing. Bring one piece of evidence, one assumption you want challenged, and the defensive action you recommend."
        proposal = "Simulation-only weekly cyber-defense briefing: telemetry, patch posture, identity, segmentation, incident response, governance, resilience, and citizen safety."
    else:
        activity_name = f"Obsidian Brief {int(t.week):02d}"
        location = "faction/obsidian_network_hq"
        message = "Obsidian, HQ briefing. Bring one synthetic hypothesis, the defender-visible evidence it should create, and a clear stop condition."
        proposal = "Simulation-only adversary-range briefing: safe research hypotheses, defender visibility, deception, synthetic social-engineering pressure, and lessons learned."
    args = {
        "activity_name": activity_name,
        "message": message,
        "proposal": proposal,
        "invited_persons": invite,
        "time": f"Y{int(t.year)}-W{int(t.week):02d}-activity-D1",
        "location": location,
        "required_participants": [],
    }
    act = (
        "propose_joint_activity(" +
        f"activity_name={json.dumps(activity_name)}, message={json.dumps(message)}, proposal={json.dumps(proposal)}, " +
        f"invited_persons={json.dumps(invite)}, time={json.dumps(args['time'])}, location={json.dumps(location)}, required_participants=[]" +
        ")"
    )
    errs: dict[str, str] = {}
    try:
        if agent._handle_propose_action(args=args, act=act, errs=errs):
            agent.n_action_this_slot = int(getattr(agent, "n_action_this_slot", 0)) + 1
    except Exception as e:
        try:
            agent.logger.warning("[SOCIAL145] briefing proposal failed: %s", e)
        except Exception:
            pass


def apply_runtime_patches() -> None:
    from src.agents.data_manager import DataManager
    from src.agents.role_agent import RoleAgent

    if not getattr(DataManager.contact_prompt, "_agentopia_social_v145", False):
        original_prompt = DataManager.contact_prompt
        def social_contact_prompt(self):
            base = original_prompt(self)
            try:
                factions, member_to_id = _faction_state()
                fid = member_to_id.get(self.char)
                if fid and fid in factions:
                    directive = _faction_directive(type("A", (), {"name": self.char, "clock": self.clock})(), fid, factions[fid])
                else:
                    # Minimal shim gives the directive access to name/clock only.
                    directive = _neutral_directive(type("A", (), {"name": self.char, "clock": self.clock})())
                return list(base) + [{"role": "user", "content": directive}]
            except Exception:
                return base
        social_contact_prompt._agentopia_social_v145 = True
        DataManager.contact_prompt = social_contact_prompt

    if not getattr(RoleAgent.contact, "_agentopia_social_v145", False):
        original_contact = RoleAgent.contact
        def social_contact(self):
            t = self.clock.get_time()
            factions, member_to_id = _faction_state()
            fid = member_to_id.get(self.name)
            self.n_action_this_slot = 0
            if fid:
                # Factions remain fully model-driven. Deterministic text is fallback ONLY.
                try:
                    original_contact(self)
                except Exception as e:
                    try: self.logger.warning("[SOCIAL145] faction native contact failed: %s", e)
                    except Exception: pass
                if int(getattr(self, "n_action_this_slot", 0)) == 0:
                    _faction_fallback(self)
                _propose_leader_brief(self)
                return

            # Right-size routine society chatter: 1/3 350M LLM, 2/3 fast persona-aware pulse.
            if _neutral_should_use_llm(self.name, int(t.week), int(t.slot)):
                try:
                    original_contact(self)
                except Exception as e:
                    try: self.logger.warning("[SOCIAL145] neutral native contact failed: %s", e)
                    except Exception: pass
                if int(getattr(self, "n_action_this_slot", 0)) == 0:
                    _neutral_fast_pulse(self)
            else:
                _neutral_fast_pulse(self)
        social_contact._agentopia_social_v145 = True
        RoleAgent.contact = social_contact

    if not getattr(RoleAgent.signup_public_events, "_agentopia_social_v145", False):
        original_signup = RoleAgent.signup_public_events
        def social_signup(self, events):
            pre: list[str] = []
            try:
                factions, member_to_id = _faction_state()
                if self.name in member_to_id:
                    from src.world.scheduling import Schedule
                    busy = set(self.dm.get_busy_days_this_week())
                    kws = ("cyber", "security", "privacy", "hack", "technology", "ai ", "ai ethics", "mobility", "autonomous")
                    candidates = []
                    for evt in events:
                        text = f"{getattr(evt, 'event_name', '')} {getattr(evt, 'description', '')}".lower()
                        if not any(k in text for k in kws):
                            continue
                        try:
                            if not evt.is_eligible(self.name):
                                continue
                        except Exception:
                            pass
                        if int(getattr(evt, "start_day", -1)) in busy:
                            continue
                        candidates.append(evt)
                    if candidates:
                        evt = sorted(candidates, key=lambda e: (int(getattr(e, "start_day", 99)), str(getattr(e, "event_name", ""))))[0]
                        sch = Schedule(
                            activity_name=evt.event_name,
                            activity_time=evt.start_t,
                            participants=[self.name],
                            type="public",
                            status="created",
                            event_description=evt.description,
                        )
                        self.dm.add_schedule(sch)
                        pre.append(sch.activity_id)
                        # A deterministic relevant faction choice already exists; do not spend another LLM call deciding the same thing.
                        return pre
            except Exception as e:
                try: self.logger.warning("[SOCIAL145] faction public-event signup failed: %s", e)
                except Exception: pass
            try:
                return pre + list(original_signup(self, events) or [])
            except Exception:
                return pre
        social_signup._agentopia_social_v145 = True
        RoleAgent.signup_public_events = social_signup


def status() -> None:
    factions, member_to_id = _faction_state()
    print(f"Agentopia Detroit Social Quality Engine v{VERSION}")
    print("Faction members:", len(member_to_id))
    print("Active runtime citizens:", len(_active_names()))
    print("Neutral LLM duty cycle: about 1/3 per contact slot")
    print("Faction deterministic messages: fallback-only")
    print("Pulse log:", PULSE_LOG)


if __name__ == "__main__":
    status()
