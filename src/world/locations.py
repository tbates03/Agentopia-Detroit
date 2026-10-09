from __future__ import annotations

"""
Location store for the world.

Provides a consistent, shared map of locations (public/private).

Persisted layout: data/{world}/locations.json
{
  "public": { ... },
  "private": { "home/<name>": {"owner": "<name>", ... } }
}
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math

from src.config import get_config
from src.utils import get_logger

# Module-level cache: one LocationStore per world
_store_cache: Dict[str, "LocationStore"] = {}


def get_location_store(world_name: str) -> "LocationStore":
    """Get or create a LocationStore for the given world (singleton per world)."""
    if world_name not in _store_cache:
        _store_cache[world_name] = LocationStore(world_name=world_name)
    return _store_cache[world_name]


@dataclass
class Location:
    key: str
    display_name: str
    kind: str  # public|private
    size: str  # small|medium|large
    description: str
    objects: List[str]
    owner: Optional[str] = None  # only for private

    def surroundings_text(self) -> str:
        """Render location description and objects as text."""
        lines: List[str] = []
        lines.append(f"**{self.display_name}**")
        if self.description:
            lines.append(self.description.strip())
        objs = [x for x in (self.objects or []) if str(x).strip()]
        if objs:
            lines.append("")
            lines.append("The objects found in this environment include:")
            for it in objs:
                lines.append(f"- {it}")
        return "\n".join(lines)


class LocationStore:
    def __init__(self, *, world_name: str) -> None:
        self.world = world_name
        self.root = Path("data") / self.world
        self.path = self.root / "locations.json"
        self.loaded = False
        self.public: Dict[str, dict] = {}
        self.private: Dict[str, dict] = {}
        self.logger = get_logger("world", quiet=False)

    # ---------- Public API ----------
    def ensure(
        self, *, persona_names: List[str], force: bool = False, agents_summary: str = ""
    ) -> None:
        """Ensure locations.json exists and every persona has a private home."""
        self._load_or_create(force=force, agents_summary=agents_summary)

        # AGENTOPIA_PUBLIC_MAP_GROWTH_V180
        # Shared civic space grows gradually with the bounded active cohort.
        # This is not one location per citizen; it preserves reusable public
        # infrastructure while preventing a permanent 30-location city.
        self._ensure_public_capacity(
            active_personas=len(persona_names),
            agents_summary=agents_summary,
        )

        # Collect personas needing home generation
        to_generate = []
        for nm in persona_names:
            home_key = self._home_key(nm)
            if home_key not in self.private:
                profile = self._read_profile_for(nm)
                to_generate.append((nm, home_key, profile))

        if not to_generate:
            return

        # Generate homes in parallel
        cfg = get_config()
        max_concurrency = cfg["max_concurrency"]
        self.logger.info(f"Generating {len(to_generate)} homes in parallel...")
        with ThreadPoolExecutor(
            max_workers=min(max_concurrency, len(to_generate))
        ) as executor:
            futures = {
                executor.submit(self._generate_home_via_llm, nm, profile): (
                    nm,
                    home_key,
                )
                for nm, home_key, profile in to_generate
            }
            for future in as_completed(futures):
                nm, home_key = futures[future]
                self.private[home_key] = future.result()
                self.logger.info(f"  Generated home for {nm}")

        self._save()

    def list_all(self) -> Tuple[List[str], List[str]]:
        self._load_or_create()
        return list(self.public.keys()), list(self.private.keys())

    def is_valid(self, loc_key: str) -> bool:
        self._load_or_create()
        return (loc_key in self.public) or (loc_key in self.private)

    def get(self, loc_key: str) -> Location:
        self._load_or_create()
        if loc_key in self.public:
            return self._to_location(loc_key, self.public[loc_key], kind="public")
        if loc_key in self.private:
            return self._to_location(loc_key, self.private[loc_key], kind="private")
        raise KeyError(loc_key)

    def get_surroundings_text(self, loc_key: str) -> str:
        """Return surroundings text for a location."""
        loc = self.get(loc_key)
        return loc.surroundings_text()

    def get_char_home(self, name: str) -> str:
        """Return surroundings text of a character's home."""
        self.ensure(persona_names=[name], force=False)
        key = self._home_key(name)
        return self.get_surroundings_text(key)

    def read_map_text(self, char_name: Optional[str] = None) -> str:
        """Render a human-readable map listing (public + private/home keys).

        Args:
            char_name: If provided, show the character's own home key explicitly.
        """
        self._load_or_create()
        pubs, _ = self.list_all()
        lines: List[str] = []
        lines.append("## Map of Locations")
        if pubs:
            lines.append("- Public:")
            for k in sorted(pubs):
                lines.append(f"  - {k}")
        lines.append("- Private:")
        if char_name:
            lines.append(
                f"  - Your home: 'home/{char_name}' (you can invite others here)"
            )
        lines.append("  - Others' homes: 'home/<name>' (only accessible when invited)")
        return "\n".join(lines)

    # ---------- Internals ----------

    def _ensure_public_capacity(
        self, *, active_personas: int, agents_summary: str = ""
    ) -> None:
        cfg = get_config()
        world_cfg = cfg["world"]
        loc_cfg = world_cfg.get("location", {}) or {}
        growth_cfg = world_cfg.get("growth", {}) or {}

        base = max(1, int(loc_cfg.get("n_locations", 30)))
        people_per_location = max(
            1, int(growth_cfg.get("public_location_people_per_location", 3))
        )
        max_public = max(
            base, int(growth_cfg.get("public_location_max", 120))
        )
        target = min(
            max_public,
            max(base, int(math.ceil(max(1, active_personas) / people_per_location))),
        )
        missing = max(0, target - len(self.public))
        if missing <= 0:
            return

        from src.world.mapgen import generate_locations_via_llm

        self.logger.info(
            "[locations] expanding public map: current=%d target=%d add=%d",
            len(self.public),
            target,
            missing,
        )
        # AGENTOPIA_LOCAL_MAPGEN_FAILSOFT_RC2
        # Public-map growth is optional. An unavailable LLM must never
        # terminate the persistent Detroit world during initialization.
        try:
            generated = generate_locations_via_llm(
                world_cfg,
                {
                    "n_locations": missing,
                    "detail_level": str(loc_cfg.get("detail_level", "medium")).lower(),
                },
                agents_summary,
                avoid_names=list(self.public.keys()),
            )
        except RuntimeError as exc:
            self.logger.warning(
                "[locations] public map expansion deferred; keeping existing map: %s",
                exc,
            )
            return
        added = 0
        for key, value in sorted((generated.get("public") or {}).items()):
            if key in self.public:
                continue
            self.public[key] = value
            added += 1

        if added:
            self._save()
        self.logger.info(
            "[locations] public map expansion complete: added=%d total=%d",
            added,
            len(self.public),
        )

    def _home_key(self, name: str) -> str:
        # Always use English 'home' prefix for consistency
        return f"home/{name}"

    def _read_profile_for(self, name: str) -> dict:
        """Read profile for a persona."""
        cfg = get_config()
        world_cfg = cfg["world"]
        start_year = int(world_cfg["time"]["start_year"])
        base = self.root / "persona" / name / "profile"
        if not base.exists():
            raise FileNotFoundError(f"Profile directory not found: {base}")
        # Try current year first
        cand = base / f"year={start_year}.json"
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8"))
        # Fallback to any year
        ys = sorted(base.glob("year=*.json"))
        if ys:
            return json.loads(ys[0].read_text(encoding="utf-8"))
        raise FileNotFoundError(f"No profile year=*.json found in {base}")

    def _generate_home_via_llm(self, name: str, profile: dict) -> dict:
        """Generate a persona's home via LLM. Raises on failure."""
        from src.utils import get_response_json, clip_str
        from src.agents.data_manager import CLIP_APPEARANCE

        cfg = get_config()
        model = cfg["god_model"]
        lang = cfg["world"].get("language", "zh")

        # Build minimal profile text for home generation
        appearance = clip_str(profile["appearance_and_impression"], CLIP_APPEARANCE)
        brief = profile["brief_introduction"]
        details = profile["details"]

        prof_txt = (
            f"Name: {name}\n"
            f"Appearance: {appearance}\n"
            f"Description: {brief}\n"
            f"Details: {details}"
        )

        prompt = (
            f"Based on the persona profile, generate a brief description of the character's home (bedroom/room) and representative objects.\n\n"
            f"Profile:\n{prof_txt}\n\n"
            f'Output JSON: {{"description": <2-4 sentences>, "objects": [4-6 item names]}}\n'
            f"Output in {lang}."
        )

        data = get_response_json(
            model=model, messages=[{"role": "user", "content": prompt}]
        )

        return {
            "owner": name,
            "display_name": f"{name}'s Home",
            "size": "small",
            "description": str(data.get("description", "")).strip(),
            "objects": [str(x).strip() for x in (data.get("objects") or [])][:6],
        }

    def _to_location(self, key: str, data: dict, *, kind: str) -> Location:
        return Location(
            key=key,
            display_name=str(data.get("display_name", key)),
            kind=kind,
            size=str(data.get("size", "medium")),
            description=str(data.get("description", "")).strip(),
            objects=[str(x) for x in (data.get("objects") or [])],
            owner=(str(data.get("owner")) if data.get("owner") else None),
        )

    def _load_or_create(self, *, force: bool = False, agents_summary: str = "") -> None:
        """Load existing locations.json or generate via LLM.

        Priority:
        1. Current run's locations.json (if exists and has public locations)
        2. load_from_template=true: load from template (data/{world_base}/locations.json)
        3. Generate via LLM

        No fallback. If LLM generation fails, it raises immediately.
        """
        if self.loaded and not force:
            return

        cfg = get_config()
        world_cfg = cfg["world"]
        loc_cfg = world_cfg.get("location", {}) or {}

        # 1. Current run directory already has map with public locations
        if self.path.exists() and not force:
            self._load_from_file(self.path)
            # If public is empty, the file is corrupted - need to regenerate
            if self.public:
                return
            else:
                self.logger.warning(
                    f"[locations] {self.path} has empty public, will regenerate"
                )
                self.loaded = False

        # 2. load_from_template: load from base world template
        if loc_cfg.get("load_from_template", False):
            # Extract base world name (e.g., "schooldays" from "schooldays_02261316")
            world_base = world_cfg["name"]
            template_path = Path("data") / world_base / "locations.json"
            if template_path.exists():
                self._load_from_file(template_path)
                if not self.public:
                    raise RuntimeError(
                        f"Template {template_path} has empty public locations"
                    )
                return
            else:
                raise FileNotFoundError(
                    f"load_from_template=true but template not found: {template_path}"
                )

        # 3. Generate via LLM
        self._generate_via_llm(agents_summary=agents_summary)
        self._save()

    def _load_from_file(self, path: Path) -> None:
        """Load locations from JSON file."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Sort by key for deterministic order in memory
        self.public = dict(sorted(raw.get("public", {}).items()))
        self.private = dict(sorted(raw.get("private", {}).items()))
        self.logger.info(f"[locations] loaded map from: {path}")
        self.loaded = True

    def _generate_via_llm(self, *, agents_summary: str = "") -> None:
        """Generate public map via LLM. Raises on failure."""
        from src.world.mapgen import generate_locations_via_llm

        cfg = get_config()
        world_cfg = cfg["world"]
        loc_cfg = world_cfg.get("location", {}) or {}

        opts = {
            "n_locations": int(loc_cfg.get("n_locations", 30)),
            "detail_level": str(loc_cfg.get("detail_level", "medium")).lower(),
        }

        generated = generate_locations_via_llm(world_cfg, opts, agents_summary)
        # Sort by key for deterministic order in memory
        self.public = dict(sorted(generated["public"].items()))

        # Public locations must exist after generation; raise instead of saving an empty file
        if not self.public:
            raise RuntimeError(
                f"LLM generated empty public locations. "
                f"Check god_model_max_tokens config or LLM output."
            )

        self.private = {}
        self.logger.info(
            f"[locations] generated map via LLM: {len(self.public)} locations"
        )
        self.loaded = True

    def _save(self) -> None:
        # Sort both public and private by key for cache determinism
        # (parallel generation via as_completed produces non-deterministic order)
        sorted_public = dict(sorted(self.public.items()))
        sorted_private = dict(sorted(self.private.items()))
        self._write_locations(
            self.root, {"public": sorted_public, "private": sorted_private}
        )

    def _write_locations(self, root: Path, obj: Dict) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p1 = root / "locations.json"
        p1.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
