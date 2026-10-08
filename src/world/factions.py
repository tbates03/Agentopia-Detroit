from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any


FACTION_VERSION = 1


class FactionEngine:
    """Persistent faction + recruitment layer for Agentopia.

    Design goals:
    - Keep faction state inside the run directory.
    - Recruit at most one neutral citizen per faction per simulated week.
    - Add 50 *background* citizens when a faction first reaches 10 members.
    - Background citizens count toward world population but do not consume LLM
      cycles until they are recruited/activated.
    - Never add operational cyberattack instructions. Faction identity is a
      narrative/social mechanic only.
    """

    FACTIONS = {
        "thai_guardians": {
            "name": "ThAI Guardians",
            "leader": "TGOT",
            "alignment": "whitehat",
            "doctrine": "Protect people, preserve sovereignty, keep humans accountable for powerful technology.",
        },
        "obsidian_network": {
            "name": "Obsidian Network",
            "leader": "Morbeious",
            "alignment": "blackhat",
            "doctrine": "Accumulate knowledge, influence systems, and expand control through secrecy and leverage.",
        },
    }

    FOUNDER_TARGET = 7  # leader + 6 founders per faction
    RECRUITS_PER_WEEK = 1
    EXPANSION_THRESHOLD = 10
    EXPANSION_SIZE = 50

    FIRST_NAMES = [
        "Amina", "Avery", "Bianca", "Caleb", "Camila", "Cass", "Darius", "Devon",
        "Elena", "Elias", "Fatima", "Felix", "Gabriel", "Grace", "Hana", "Harper",
        "Imani", "Isaac", "Jade", "Jalen", "Kai", "Keira", "Leila", "Leo",
        "Lucia", "Malik", "Maya", "Mateo", "Nadia", "Noah", "Nora", "Omar",
        "Priya", "Quinn", "Rafael", "Rina", "Samira", "Santiago", "Sofia", "Tariq",
        "Theo", "Valentina", "Victor", "Yara", "Zane", "Zara", "Amara", "Kenji",
        "Mei", "Niko", "Anika", "Jonah", "Lena", "Micah", "Naomi", "Ravi",
        "Selene", "Tomas", "Yuki", "Zuri",
    ]
    LAST_NAMES = [
        "Adler", "Alvarez", "Bennett", "Brooks", "Chen", "Clarke", "Diaz", "Dubois",
        "Ellis", "Farouk", "Foster", "Garcia", "Grant", "Haddad", "Hale", "Ibrahim",
        "Ito", "Johnson", "Khan", "Kim", "Laurent", "Lewis", "Martinez", "Mensah",
        "Miller", "Moreno", "Nguyen", "Okafor", "Patel", "Petrov", "Quintero", "Reed",
        "Rivera", "Rossi", "Sato", "Singh", "Sullivan", "Tanaka", "Taylor", "Torres",
        "Vega", "Walker", "Wang", "Williams", "Wilson", "Yamamoto", "Young", "Zhou",
        "Adeyemi", "Bianchi", "Costa", "Duarte", "Evans", "Fischer", "Gupta", "Hernandez",
        "Jensen", "Kowalski", "Lopez", "Morgan",
    ]

    PROFESSIONS = [
        ("Teacher", "Community School", {"teaching": 110, "communication": 90, "planning": 80}),
        ("Nurse", "Community Health Center", {"healthcare": 130, "empathy": 110, "organization": 85}),
        ("Software developer", "Independent Technology Studio", {"programming": 150, "systems_thinking": 120, "research": 90}),
        ("Electrician", "City Trades Cooperative", {"electrical": 145, "troubleshooting": 120, "safety": 100}),
        ("Chef", "Neighborhood Restaurant", {"cooking": 150, "hospitality": 100, "planning": 85}),
        ("Designer", "Creative Cooperative", {"design": 140, "creativity": 120, "communication": 80}),
        ("Logistics coordinator", "Regional Distribution Group", {"logistics": 145, "planning": 125, "negotiation": 90}),
        ("Research analyst", "Civic Research Lab", {"research": 150, "analysis": 140, "writing": 95}),
        ("Mechanic", "Neighborhood Auto Works", {"mechanical": 150, "diagnostics": 125, "customer_service": 75}),
        ("Journalist", "Independent Newsroom", {"journalism": 145, "research": 130, "interviewing": 115}),
        ("Small-business owner", "Local Business", {"business": 135, "negotiation": 115, "leadership": 105}),
        ("Social worker", "Community Services Network", {"social_work": 145, "empathy": 130, "communication": 105}),
        ("Data analyst", "Regional Analytics Group", {"data_analysis": 150, "statistics": 125, "research": 100}),
        ("Artist", "Independent Studio", {"art": 150, "creativity": 140, "communication": 70}),
        ("Security analyst", "Independent Security Cooperative", {"cybersecurity": 145, "analysis": 125, "networking": 100}),
    ]

    def __init__(self, world: Any):
        self.world = world
        self.root = Path("data") / world.data_dir
        self.persona_root = self.root / "persona"
        self.state_path = self.root / "factions.json"
        self.events_path = self.root / "faction_events.jsonl"
        self.state = self._load_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _default_state(self) -> dict[str, Any]:
        return {
            "version": FACTION_VERSION,
            "rules": {
                "founder_target": self.FOUNDER_TARGET,
                "recruits_per_week": self.RECRUITS_PER_WEEK,
                "expansion_threshold": self.EXPANSION_THRESHOLD,
                "expansion_size": self.EXPANSION_SIZE,
                "expansion_mode": "per_faction_once",
            },
            "factions": {
                fid: {
                    **meta,
                    "members": [],
                    "expansion_triggered": False,
                    "expansion_population_added": 0,
                }
                for fid, meta in self.FACTIONS.items()
            },
            "generated_population": 0,
            "last_tick": None,
        }

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and "factions" in data:
                    return data
            except Exception:
                pass
        return self._default_state()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _event(self, kind: str, **payload: Any) -> None:
        row = {
            "time": str(self.world.clock.get_time()),
            "kind": kind,
            **payload,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Profiles / activation
    # ------------------------------------------------------------------
    def _current_year(self) -> int:
        return int(getattr(self.world, "_resume_year", self.world.config["time"]["start_year"]))

    def _profile_path(self, name: str) -> Path | None:
        pdir = self.persona_root / name / "profile"
        if not pdir.exists():
            return None
        files = sorted(pdir.glob("year=*.json"), key=lambda p: p.name)
        return files[-1] if files else None

    def _read_profile(self, name: str) -> dict[str, Any]:
        path = self._profile_path(name)
        if path is None:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_profile(self, name: str, profile: dict[str, Any]) -> None:
        pdir = self.persona_root / name / "profile"
        pdir.mkdir(parents=True, exist_ok=True)
        path = self._profile_path(name) or (pdir / f"year={self._current_year()}.json")
        path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")

    def _faction_block(self, faction_id: str, role: str) -> dict[str, Any]:
        meta = self.FACTIONS[faction_id]
        return {
            "id": faction_id,
            "name": meta["name"],
            "alignment": meta["alignment"],
            "role": role,
            "leader": meta["leader"],
            "joined_at": str(self.world.clock.get_time()),
            "doctrine": meta["doctrine"],
        }

    def _leader_profile(self, name: str, faction_id: str) -> dict[str, Any]:
        year = self._current_year()
        is_guardian = faction_id == "thai_guardians"
        faction_name = self.FACTIONS[faction_id]["name"]
        if is_guardian:
            intro = (
                "TGOT is a veteran technology and cybersecurity strategist with decades of experience spanning "
                "networks, enterprise security, AI, infrastructure, governance, and teaching. He leads the ThAI "
                "Guardians as a whitehat global network focused on protecting Agentopia's citizens and preserving "
                "human control over technology."
            )
            details = (
                "He began exploring technology as a child and grew through multiple generations of computing. "
                "He is strongest when mentoring others, reading complex systems, anticipating adversaries, and "
                "building defensive organizations. He believes knowledge should increase human agency rather than "
                "concentrate control."
            )
            motivation = "Build a generation of defenders capable of protecting Agentopia without surrendering its freedom."
            values = "Human-in-the-loop decisions, digital sovereignty, accountability, mentorship, privacy, resilience, and service."
            conflict = "He understands adversarial thinking deeply and must continually prove that understanding the darkness does not require becoming it."
            org, role = "ThAI Guardians", "Founder and Guardian Commander"
            honesty, integrity, trust = 92, 96, 94
            control, confidence, curiosity = 80, 92, 94
        else:
            intro = (
                "Morbeious is a fictional master technologist with decades of experience comparable in breadth to "
                "TGOT, but he chose the blackhat path. He leads the Obsidian Network, a global underground syndicate "
                "built around information, influence, secrecy, and control."
            )
            details = (
                "Morbeious understands networking, security architecture, AI systems, infrastructure, intelligence, "
                "and the evolution of digital technology across decades. He prefers strategic leverage, recruitment, "
                "and organizational influence over reckless action. The simulation treats his capabilities as fictional "
                "narrative expertise and does not encode real attack procedures."
            )
            motivation = "Become the most informed and influential power in Agentopia without allowing rivals to predict his next move."
            values = "Autonomy, secrecy, loyalty, strategic patience, technical mastery, information advantage, and control."
            conflict = "His need for control competes with the loyalty and independence of the talented people he recruits."
            org, role = "Obsidian Network", "Founder and Supreme Architect"
            honesty, integrity, trust = 52, 48, 58
            control, confidence, curiosity = 98, 94, 98

        return {
            "name": name,
            "gender": "Male",
            "appearance_and_impression": (
                f"{name} carries the composed presence of someone who has spent decades inside complex technical systems. "
                "His posture is deliberate, his attention is intense, and he tends to study a room before speaking."
            ),
            "brief_introduction": intro,
            "talents": {
                "qualitative": details,
                "quantitative": {
                    "beauty": 60,
                    "communication": 92,
                    "creativity": 94,
                    "health": 72,
                    "honesty": honesty,
                    "integrity": integrity,
                    "intelligence": 98,
                    "leadership": 98,
                    "trustworthiness": trust,
                },
            },
            "details": details,
            "conflicts": conflict,
            "core_motivation": motivation,
            "personality_traits": {
                "qualitative": "Strategic, intensely curious, technically confident, observant, independent, and capable of long-range planning.",
                "quantitative": {
                    "confidence": confidence,
                    "control": control,
                    "curiosity": curiosity,
                    "empathy": 72 if is_guardian else 54,
                    "judging": 82,
                    "introversion": 65,
                    "intuition": 94,
                    "patience": 88,
                    "responsibility": 94 if is_guardian else 68,
                    "thinking": 96,
                },
            },
            "preferences": (
                "Likes: difficult technical problems, strategy, mentoring talented people, systems thinking, long-term planning, "
                "and people who can defend their reasoning. Dislikes: shallow thinking, careless operational risk, and wasted talent."
            ),
            "position": {
                "weekly_income": 900,
                "role": role,
                "organization": org,
                "type": "work",
                "description": f"Leads {faction_name} and coordinates its global strategy inside Agentopia.",
                "weekly_delta_skills": {
                    "cybersecurity": 0.5,
                    "systems_architecture": 0.4,
                    "leadership": 0.4,
                },
            },
            "init_skills": {
                "cybersecurity": 300,
                "networking": 300,
                "systems_architecture": 300,
                "ai_orchestration": 290,
                "infrastructure": 285,
                "governance": 280 if is_guardian else 180,
                "intelligence_analysis": 285,
                "mentoring": 275 if is_guardian else 210,
                "strategy": 300,
            },
            "init_assets": {
                "deposit": 25000,
                "possessions": [
                    {"name": "Secure workstation", "description": "A high-end workstation used for research, simulation, and communications."},
                    {"name": "Technical library", "description": "Decades of notes, books, diagrams, and technical references."},
                ],
            },
            "extra_income": 0,
            "values": values,
            "birthday": f"Y{year-58}-W06-activity-D2",
            "birth_year": year - 58,
            "faction": self._faction_block(faction_id, "leader"),
            "world_role": "faction_leader",
        }

    def _ensure_leader(self, faction_id: str) -> None:
        name = self.FACTIONS[faction_id]["leader"]
        p = self._profile_path(name)
        if p is None:
            self._write_profile(name, self._leader_profile(name, faction_id))
            self._event("leader_created", faction=faction_id, member=name)
        else:
            profile = self._read_profile(name)
            profile["faction"] = self._faction_block(faction_id, "leader")
            profile["world_role"] = "faction_leader"
            self._write_profile(name, profile)

        members = self.state["factions"][faction_id]["members"]
        if name not in members:
            members.insert(0, name)
        self._activate_persona(name)

    def _marker(self, name: str) -> Path:
        return self.persona_root / name / "_background.json"

    def _activate_persona(self, name: str) -> None:
        marker = self._marker(name)
        if marker.exists():
            marker.unlink()

        # Agentopia reads profiles by the simulation clock year. Background
        # citizens may have been created years earlier, so copy their latest
        # profile forward (or backward during resume bootstrap) when needed.
        pdir = self.persona_root / name / "profile"
        pdir.mkdir(parents=True, exist_ok=True)
        clock_year = int(self.world.clock.get_time().year)
        clock_profile = pdir / f"year={clock_year}.json"
        if not clock_profile.exists():
            latest = self._profile_path(name)
            if latest is not None:
                clock_profile.write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")

        if name in self.world._name2agent:
            return

        from src.agents.role_agent import RoleAgent

        models = list(getattr(self.world, "_role_models", []))
        if not models:
            return
        h = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
        model = models[h % len(models)]

        assignment_path = self.root / "model_assignment.json"
        try:
            assignment = json.loads(assignment_path.read_text(encoding="utf-8")) if assignment_path.exists() else {}
        except Exception:
            assignment = {}
        assignment[name] = model
        assignment_path.write_text(json.dumps(dict(sorted(assignment.items())), indent=2, ensure_ascii=False), encoding="utf-8")

        agent = RoleAgent(
            name,
            clock=self.world.clock,
            msg_center=self.world.msg_center,
            model=model,
            world_name=self.world.data_dir,
            no_context_engineering=self.world.no_context_engineering,
            no_history=self.world.no_history,
        )
        agent.dm.read_state(exclude_cur_t=False)
        self.world.agents.append(agent)
        self.world._name2agent[name] = agent
        self._event("citizen_activated", member=name)

    def _all_neutral_names(self) -> list[str]:
        used = set()
        for f in self.state["factions"].values():
            used.update(f.get("members", []))
        out = []
        if not self.persona_root.exists():
            return out
        for p in sorted(self.persona_root.iterdir(), key=lambda x: x.name.lower()):
            if p.is_dir() and p.name not in used and self._profile_path(p.name) is not None:
                out.append(p.name)
        return out

    # ------------------------------------------------------------------
    # Affinity / recruitment
    # ------------------------------------------------------------------
    @staticmethod
    def _num(obj: dict[str, Any], key: str, default: float = 50.0) -> float:
        v = obj.get(key, default)
        return float(v) if isinstance(v, (int, float)) else default

    def _contact_exposure(self, candidate: str, members: list[str]) -> int:
        cdir = self.persona_root / candidate / "contact"
        if not cdir.exists():
            return 0
        count = 0
        for member in members:
            f = cdir / f"{member}.jsonl"
            if not f.exists():
                continue
            try:
                with f.open("r", encoding="utf-8", errors="ignore") as h:
                    for _ in h:
                        count += 1
                        if count >= 20:
                            return count
            except Exception:
                continue
        return count

    def _affinity(self, name: str, faction_id: str) -> float:
        p = self._read_profile(name)
        talents = p.get("talents", {}).get("quantitative", {}) if isinstance(p.get("talents"), dict) else {}
        traits = p.get("personality_traits", {}).get("quantitative", {}) if isinstance(p.get("personality_traits"), dict) else {}
        members = self.state["factions"][faction_id]["members"]
        exposure = self._contact_exposure(name, members)

        if faction_id == "thai_guardians":
            base = (
                self._num(talents, "integrity")
                + self._num(talents, "honesty")
                + self._num(talents, "trustworthiness")
                + self._num(traits, "empathy")
                + self._num(traits, "responsibility")
                + self._num(traits, "curiosity")
            ) / 6.0
            text = (str(p.get("values", "")) + " " + str(p.get("core_motivation", ""))).lower()
            keywords = ("protect", "service", "community", "privacy", "ethic", "teach", "help", "freedom")
        else:
            base = (
                self._num(talents, "intelligence")
                + self._num(talents, "leadership")
                + self._num(talents, "creativity")
                + self._num(traits, "control")
                + self._num(traits, "confidence")
                + self._num(traits, "curiosity")
            ) / 6.0
            text = (str(p.get("values", "")) + " " + str(p.get("core_motivation", ""))).lower()
            keywords = ("autonomy", "independent", "ambition", "strategy", "power", "risk", "control", "mastery")

        text_bonus = min(10.0, sum(2.0 for k in keywords if k in text))
        exposure_bonus = min(20.0, exposure * 2.0)
        seed = f"{self.world.data_dir}|{self.world.clock.get_time()}|{faction_id}|{name}"
        noise = (int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16) % 1000) / 1000.0 * 6.0
        return base + text_bonus + exposure_bonus + noise

    def _join(self, name: str, faction_id: str, role: str, score: float | None = None) -> None:
        # Remove from another faction if necessary (should be rare, but state stays consistent).
        for other_id, faction in self.state["factions"].items():
            if other_id != faction_id and name in faction.get("members", []):
                faction["members"].remove(name)

        members = self.state["factions"][faction_id]["members"]
        if name not in members:
            members.append(name)

        profile = self._read_profile(name)
        profile["faction"] = self._faction_block(faction_id, role)
        self._write_profile(name, profile)
        self._activate_persona(name)
        self._event(
            "recruited",
            faction=faction_id,
            faction_name=self.FACTIONS[faction_id]["name"],
            member=name,
            role=role,
            affinity=round(score, 2) if score is not None else None,
            member_count=len(members),
        )

    def _seed_founders(self, faction_id: str) -> None:
        members = self.state["factions"][faction_id]["members"]
        need = max(0, self.FOUNDER_TARGET - len(members))
        if need == 0:
            return
        candidates = self._all_neutral_names()
        ranked = sorted(
            ((self._affinity(n, faction_id), n) for n in candidates),
            key=lambda x: (-x[0], x[1].lower()),
        )
        for score, name in ranked[:need]:
            self._join(name, faction_id, "founder", score)

    # ------------------------------------------------------------------
    # Population generation
    # ------------------------------------------------------------------
    def _existing_names(self) -> set[str]:
        if not self.persona_root.exists():
            return set()
        return {p.name for p in self.persona_root.iterdir() if p.is_dir()}

    def _next_name(self, rng: random.Random, existing: set[str], serial: int) -> str:
        for _ in range(400):
            name = f"{rng.choice(self.FIRST_NAMES)} {rng.choice(self.LAST_NAMES)}"
            if name not in existing:
                return name
        return f"Agentopia Citizen {serial:04d}"

    def _citizen_profile(self, name: str, index: int, rng: random.Random) -> dict[str, Any]:
        year = int(self.world.clock.get_time().year)
        gender = ("Female", "Male", "Non-binary")[index % 3]
        age = rng.randint(19, 62)
        birth_year = year - age
        role, org, skills = self.PROFESSIONS[index % len(self.PROFESSIONS)]
        curiosity = rng.randint(55, 95)
        empathy = rng.randint(50, 92)
        responsibility = rng.randint(52, 94)
        confidence = rng.randint(50, 90)
        control = rng.randint(50, 90)
        intelligence = rng.randint(55, 92)
        leadership = rng.randint(45, 88)
        integrity = rng.randint(48, 94)
        honesty = rng.randint(48, 94)
        trust = rng.randint(48, 94)
        values_pool = [
            "community, independence, practical competence, and fairness",
            "family, learning, reliability, and personal freedom",
            "creativity, autonomy, friendship, and meaningful work",
            "privacy, responsibility, curiosity, and mutual respect",
            "ambition, loyalty, resilience, and technical mastery",
            "service, honesty, education, and community stability",
        ]
        values = rng.choice(values_pool)
        return {
            "name": name,
            "gender": gender,
            "appearance_and_impression": (
                f"{name} is an adult resident of Agentopia with a practical everyday style shaped by work, neighborhood life, "
                "and personal interests. Their expressions and body language change naturally with mood and social context."
            ),
            "brief_introduction": (
                f"{name} works as a {role.lower()} and is one of Agentopia's expanding civilian population. "
                "They begin politically and factionally neutral, with their future alliances determined by relationships, values, and experience."
            ),
            "talents": {
                "qualitative": f"A capable {role.lower()} with a mixture of practical skill, curiosity, and ordinary strengths and weaknesses.",
                "quantitative": {
                    "beauty": rng.randint(45, 78),
                    "communication": rng.randint(45, 90),
                    "creativity": rng.randint(45, 92),
                    "health": rng.randint(50, 90),
                    "honesty": honesty,
                    "integrity": integrity,
                    "intelligence": intelligence,
                    "leadership": leadership,
                    "trustworthiness": trust,
                },
            },
            "details": (
                f"{name} has a normal network of coworkers, neighbors, relatives, and interests. They enter the simulation without faction membership. "
                "Their opinions of TGOT, Morbeious, the ThAI Guardians, and the Obsidian Network should develop through lived Agentopia interactions rather than being predetermined."
            ),
            "conflicts": "Balancing personal goals, financial stability, relationships, and the growing factional tension inside Agentopia.",
            "core_motivation": "Build a satisfying life while deciding which people and institutions deserve trust.",
            "personality_traits": {
                "qualitative": "A distinct but ordinary adult personality shaped by work, relationships, curiosity, caution, and personal priorities.",
                "quantitative": {
                    "confidence": confidence,
                    "control": control,
                    "curiosity": curiosity,
                    "empathy": empathy,
                    "judging": rng.randint(50, 90),
                    "introversion": rng.randint(50, 90),
                    "intuition": rng.randint(50, 90),
                    "patience": rng.randint(45, 90),
                    "responsibility": responsibility,
                    "thinking": rng.randint(50, 95),
                },
            },
            "preferences": "Likes a mix of work, hobbies, friends, neighborhood life, learning, entertainment, and personal projects. Dislikes manipulation, wasted time, and being forced into decisions without enough information.",
            "position": {
                "weekly_income": rng.randint(250, 800),
                "role": role,
                "organization": org,
                "type": "work",
                "description": f"Works as a {role.lower()} within Agentopia's civilian economy.",
                "weekly_delta_skills": {k: 0.2 for k in list(skills)[:2]},
            },
            "init_skills": skills,
            "init_assets": {
                "deposit": rng.randint(400, 9000),
                "possessions": [
                    {"name": "Phone", "description": "A normal personal smartphone used for everyday communication."},
                    {"name": "Personal computer", "description": "A computer used for work, learning, entertainment, and personal projects."},
                ],
            },
            "extra_income": 0,
            "values": f"Values {values}.",
            "birthday": f"Y{birth_year}-W{rng.randint(1,10):02d}-activity-D{rng.randint(1,5)}",
            "birth_year": birth_year,
            "world_role": "background_citizen",
        }

    def _expand_population(self, faction_id: str, count: int) -> list[str]:
        existing = self._existing_names()
        expansion_no = int(self.state.get("generated_population", 0)) // max(1, self.EXPANSION_SIZE) + 1
        seed = f"{self.world.data_dir}|{faction_id}|expansion|{expansion_no}"
        rng = random.Random(seed)
        created: list[str] = []
        for i in range(count):
            serial = len(existing) + i + 1
            name = self._next_name(rng, existing, serial)
            existing.add(name)
            profile = self._citizen_profile(name, i + expansion_no * 1000, rng)
            try:
                from src.world.detroit_lineage import enrich_new_citizen_profile
                profile = enrich_new_citizen_profile(self, profile, name, rng, i + expansion_no * 1000)
            except Exception as exc:
                self.world.logger.warning(f"Detroit lineage enrichment skipped for {name}: {exc}")
            self._write_profile(name, profile)
            marker = self._marker(name)
            marker.write_text(
                json.dumps(
                    {
                        "active": False,
                        "reason": "population_expansion",
                        "triggered_by_faction": faction_id,
                        "created_at": str(self.world.clock.get_time()),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            created.append(name)
        self.state["generated_population"] = int(self.state.get("generated_population", 0)) + len(created)
        return created

    def _check_expansion(self, faction_id: str) -> None:
        faction = self.state["factions"][faction_id]
        if faction.get("expansion_triggered"):
            return
        if len(faction.get("members", [])) < self.EXPANSION_THRESHOLD:
            return
        created = self._expand_population(faction_id, self.EXPANSION_SIZE)
        faction["expansion_triggered"] = True
        faction["expansion_population_added"] = len(created)
        self._event(
            "population_expansion",
            faction=faction_id,
            faction_name=self.FACTIONS[faction_id]["name"],
            threshold=self.EXPANSION_THRESHOLD,
            added=len(created),
            population_total=len(self._existing_names()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def bootstrap(self) -> None:
        self.persona_root.mkdir(parents=True, exist_ok=True)
        # Create both leaders first.
        self._ensure_leader("thai_guardians")
        self._ensure_leader("obsidian_network")
        # Seed six additional founders per faction from existing citizens.
        self._seed_founders("thai_guardians")
        self._seed_founders("obsidian_network")
        self._check_expansion("thai_guardians")
        self._check_expansion("obsidian_network")
        self._save()
        self._event(
            "factions_bootstrapped",
            thai_guardians=len(self.state["factions"]["thai_guardians"]["members"]),
            obsidian_network=len(self.state["factions"]["obsidian_network"]["members"]),
            population_total=len(self._existing_names()),
        )

    def weekly_tick(self) -> None:
        now = str(self.world.clock.get_time())
        if self.state.get("last_tick") == now:
            return

        # Alternate first-mover advantage each week.
        week = int(getattr(self.world.clock.get_time(), "week", 0))
        order = ["thai_guardians", "obsidian_network"] if week % 2 else ["obsidian_network", "thai_guardians"]

        for faction_id in order:
            for _ in range(self.RECRUITS_PER_WEEK):
                candidates = self._all_neutral_names()
                if not candidates:
                    break
                ranked = sorted(
                    ((self._affinity(n, faction_id), n) for n in candidates),
                    key=lambda x: (-x[0], x[1].lower()),
                )
                if not ranked:
                    break
                score, name = ranked[0]
                # This threshold keeps recruitment selective but still allows both
                # factions to grow from their seven-member founding cells.
                if score < 55.0:
                    self._event("recruitment_failed", faction=faction_id, candidate=name, affinity=round(score, 2))
                    break
                self._join(name, faction_id, "recruit", score)
                self._check_expansion(faction_id)

        self.state["last_tick"] = now
        self._save()
        self._event(
            "weekly_faction_tick",
            thai_guardians=len(self.state["factions"]["thai_guardians"]["members"]),
            obsidian_network=len(self.state["factions"]["obsidian_network"]["members"]),
            population_total=len(self._existing_names()),
        )
