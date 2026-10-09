from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from file_read_backwards import FileReadBackwards
import os

from src.world.clock import Clock, TimeState, Stage
from src.world.scheduling import Schedule
from src.world.locations import get_location_store
from src.world.position_application import Position
from src.world.reward import FULFILLMENT_DIMS
from src.utils import get_logger, clip_str, num_tokens_from_string
from src.agents.prompts import PERSONA_TEMPLATE
from src.utils import get_config

ERROR_LOGGER = get_logger("error")

config = get_config()

# Clip length constants for profile fields
CLIP_APPEARANCE = 200
CLIP_BRIEF = 200
CLIP_POS_DESC = 150

indent = "    "
double_indent = indent * 2

# Thresholds for misery awareness in roleplay prompts
_MISERY_SEVERE = 10
_MISERY_MILD = 30


def _misery_hint(val: int, pad: str = indent) -> str:
    """Return misery awareness hint if value is below thresholds."""
    if val < _MISERY_SEVERE:
        return f"\n{pad}  ** Your current state in this regard is unbearable — it weighs on you constantly. **"
    if val < _MISERY_MILD:
        return f"\n{pad}  ** Your current state in this regard has been wearing you down. **"
    return ""


def _indent_multiline(text: str, pad: str = indent) -> str:
    """Indent subsequent lines in a multi-line string with pad.

    Only processes strings containing newlines: replaces each \n with \n + pad
    so that wrapped lines stay aligned with the current indentation level.
    """
    if "\n" not in text:
        return text
    return text.replace("\n", "\n" + pad)


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _ensure_file(p: Path) -> None:
    _ensure_dir(p.parent)
    if not p.exists():
        p.touch()


@dataclass
class DataManager:
    """File-backed memory manager for an agent.

    There are two kinds of data:
    - Overwrite-style: stored in jsonl files, appended at the end on each write;
      on read only the entry closest to the input event time t is needed.
    - Cumulative-style: appended at the end on each write, and may be 1) never
      read (e.g. generation); 2) read over a recent time window (e.g.
      contact/weekly_diary); 3) read for all content up to a given time point
      (e.g. history).

    Layout under data/{world}/persona/{name}/:
    - generation/year=<YYYY>/week=<W>.jsonl (append)
    - memory/
        - scratchpad/
            - general.jsonl         (append)
            - characters/<person>.jsonl  (append)
            - others/<thing>.jsonl       (append)
        - weekly_diary.jsonl  (append; unified single file)
    - contact/
        - <person>.jsonl                 (append; unified per-person)
        - sig.jsonl                          (append; unified signal)
    - profile/year=<YYYY>.json                        (flat)
    - state.jsonl            (append; unified single file)
    - schedule.jsonl         (append; unified single file)
    """

    NO_CONTACT_MSG = "You have not sent or received any message."

    char: str
    world: str
    clock: Clock
    model: str = ""
    _scratchpad_create_times: Dict[str, Optional[TimeState]] = field(
        init=False, default_factory=dict
    )
    pad_last_access_map: Dict[str, TimeState] = field(init=False, default_factory=dict)
    # Stores the previous round's action errors, for injection into contact_prompt
    last_slot_errors: str = field(init=False, default="")
    # Send sequence number: the index (starting from 1) of a message within the
    # current slot, keyed by the (slot_str, recipient) dimension
    _send_seq_map: Dict[Tuple[str, str], int] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self.logger = get_logger(f"agent_{self.char}", quiet=True)
        self.generation = (
            Path("data") / self.world / "persona" / self.char / "generation"
        )
        # Persona root directory
        self.root = Path("data") / self.world / "persona" / self.char
        self.contact = self.root / "contact"
        self.memory = self.root / "memory"
        self.weekly_diary = self.memory / "weekly_diary.jsonl"
        # self.activity dir no longer used; activity is a root-level jsonl file
        self.scratch = self.memory / "scratchpad"
        self.general_scratchpad = self.scratch / "general.jsonl"

        self.working_memory = self.scratch / "working_memory.jsonl"
        self.character_scratchpads = self.scratch / "characters"
        self.other_scratchpads = self.scratch / "others"
        # hidden access log to avoid user exposure/listing
        self.access_log = (
            self.scratch / ".access_log.jsonl"
        )  # hidden file, would not be read by list/read/update scratchpad

        for required_dir in (
            self.generation,
            self.memory,
            self.scratch,
            self.character_scratchpads,
            self.other_scratchpads,
            self.contact,
        ):
            _ensure_dir(required_dir)

        for required_file in (
            self.general_scratchpad,
            self.working_memory,
            self.access_log,
        ):
            _ensure_file(required_file)
        # reset cache in case __post_init__ is invoked manually
        self._scratchpad_create_times.clear()
        self._init_last_access_map()

        self.response_this_week = []
        self.last_slot_errors = ""
        self.location_store = get_location_store(self.world)

    def set_last_slot_errors(self, s: str) -> None:
        """Record the previous round's action error text, for display in the next contact_prompt."""
        self.last_slot_errors = str(s or "")

    # ---------- Helpers ----------
    def _format_week(self, week: int) -> str:
        return f"week={week}"

    def _format_year(self, year: int) -> str:
        return f"year={year}"

    def _append_jsonl(self, path: Path, obj: Dict) -> None:
        obj = {
            "time": str(self.clock.get_time()),
            **{k: v for k, v in obj.items() if k != "time"},
        }
        _ensure_dir(path.parent)
        new_t = TimeState.from_string(obj["time"])
        with path.open("a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # Check time ordering: new entry must not be earlier than last entry
                f.seek(0, 2)  # seek to end
                pos = f.tell()
                if pos > 0:
                    # Read last non-empty line in binary mode to avoid
                    # partial-line issues with text-mode reads.
                    last_line = ""
                    with path.open("rb") as bf:
                        end = pos
                        # Skip trailing whitespace / newlines
                        while end > 0:
                            bf.seek(end - 1)
                            if bf.read(1) not in (b"\n", b"\r", b" "):
                                break
                            end -= 1
                        # Walk backward to find \n or file start
                        if end > 0:
                            start = end
                            while start > 0:
                                start = max(0, start - 8192)
                                bf.seek(start)
                                chunk = bf.read(end - start)
                                nl = chunk.rfind(b"\n")
                                if nl != -1 or start == 0:
                                    break
                            last_line = chunk[nl + 1 :].decode("utf-8").strip()
                    if last_line:
                        try:
                            last_t = TimeState.from_string(
                                json.loads(last_line)["time"]
                            )
                        except Exception:
                            last_t = None  # corrupt line — skip check
                        if last_t is not None and new_t < last_t:
                            # AGENTOPIA_RC2_SAME_WEEK_REPLAY_GUARD_V31
                            _agentopia_new_time = str(new_t)
                            _agentopia_old_time = str(last_t)
                            _agentopia_new_week = _agentopia_new_time.split("-", 2)[:2]
                            _agentopia_old_week = _agentopia_old_time.split("-", 2)[:2]
                            if _agentopia_new_week == _agentopia_old_week:
                                print(
                                    f"[STATE_REPLAY_GUARD_V31] skipping stale same-week append "
                                    f"{_agentopia_new_time} after {_agentopia_old_time}",
                                    flush=True,
                                )
                                return
                            raise ValueError(
                                f"Time-order violation in {path.name}: "
                                f"appending {new_t} after {last_t}"
                            )

                # Guard against files missing trailing newline (e.g. hand-edited data)
                f.seek(0, 2)  # seek to end
                if f.tell() > 0:
                    f.seek(f.tell() - 1)
                    if f.read(1) != "\n":
                        f.write("\n")
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _write_json_new(self, path: Path, data: Dict) -> None:
        """Write JSON file (overwrite mode, expects path not to exist).

        Args:
            path: Target file path
            data: Dict to write

        Warning:
            If file already exists, logs WARNING before overwriting.
        """
        _ensure_dir(path.parent)
        if path.exists():
            self.logger.warning(f"Overwriting existing file: {path}")
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def _read_last_summary_of(self, path: Path) -> str:
        """Read the latest summary (or clipped content) of a scratchpad jsonl.

        Uses time-aware _read_jsonl(max_lines=1), which already excludes cur_t
        by default. Returns empty string when no suitable lines.
        """
        rows = self._read_jsonl(path, max_lines=1)
        if not rows:
            return ""
        row = rows[-1]
        if isinstance(row, dict):
            summary = row.get("summary")
            if isinstance(summary, str) and summary:
                return summary.strip()
            content = row.get("content")
            if isinstance(content, str) and content:
                return clip_str(content, 500)
        return ""

    def _render_summary_and_public(
        self,
        *,
        who: str,
        base_indent: str = double_indent,
        in_contact: bool = False,
    ) -> str:
        """Render summary and public info for a character pad by name.

        - Reads summary from characters/{who}.jsonl (latest entry before cur_t).
        - If mutually known: shows full public info (appearance + brief + position).
        - If only I know them: shows only appearance.
        - Order: summary first, then public info. Labels unified.
        """
        who = str(who or "").strip()
        if not who:
            return ""
        lines: List[str] = []

        # Read summary from the character scratchpad if created
        sp = self.character_scratchpads / f"{who}.jsonl"
        summary_txt = self._read_last_summary_of(sp)
        if summary_txt:
            summary_txt = clip_str(summary_txt, 200)

        # Public info based on mutual knowledge (handled inside read_others_pub_info)
        pub_info = self.read_others_pub_info(who)

        # Render in unified order
        if summary_txt:
            summary_indented = _indent_multiline(summary_txt, base_indent)
            if in_contact:
                lines.append(
                    f"{base_indent}- summary of your scratchpad about {who}: {summary_indented}"
                )
            else:
                lines.append(f"{base_indent}- scratchpad summary: {summary_indented}")
        if pub_info:
            pub_indented = _indent_multiline(pub_info, base_indent)
            if in_contact:
                lines.append(
                    f"{base_indent}- public information of {who}: {pub_indented}"
                )
            else:
                lines.append(
                    f"{base_indent}- public information about {who}: {pub_indented}"
                )
        return "\n".join(lines)

    def _read_jsonl(
        self,
        path: Path,
        max_lines: Optional[int] = None,
        max_weeks: Optional[int] = None,
        exclude_cur_t: bool = True,
        *,
        exact_t: Optional[str | TimeState] = None,
        at_t: Optional[str | TimeState] = None,
    ) -> List[Dict]:
        """Read append-only jsonl backwards with time-aware windowing (single file).

        - max_lines: return up to N lines before current time.
        - max_weeks: return lines within [the beginning of (cur_week - N weeks), cur_t) window. Must be >= 1 if not None.
          N=1 returns current week only (including BEGIN), N=2 returns current + previous week, etc.
        - exact_t: when provided, return all lines whose time equals to it.
        - at_t: when provided, use this as the reference time instead of clock.get_time().

        Note: Legacy multi-year file scanning has been removed. All JSONL now
        append to unified single files by design.
        """
        # No longer returns early at entry if the start file doesn't exist;
        # cross-year paths are derived from max_weeks and missing files are skipped during scanning.

        if at_t is not None:
            cur_t = TimeState.from_string(at_t) if isinstance(at_t, str) else at_t
        else:
            cur_t = self.clock.get_time()
        # Argument validation: at least one of max_lines, max_weeks, or exact_t must be set
        if max_lines is None and max_weeks is None and exact_t is None:
            raise ValueError(
                "max_lines and max_weeks cannot be both unset when exact_t is None"
            )

        collected_data: List[Dict] = []
        start_line_found = False
        prev_line_t: Optional[TimeState] = None

        # Single-file read (cross-year enumeration removed)
        paths_to_scan: List[Path] = [path]

        def scan_one_file(p: Path) -> None:
            nonlocal start_line_found, prev_line_t, collected_data
            if not p.exists():
                return
            with FileReadBackwards(p, encoding="utf-8") as frb:
                for line in frb:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        data = json.loads(s)
                        line_t = TimeState.from_string(str(data["time"]))
                    except (
                        json.JSONDecodeError,
                        UnicodeDecodeError,
                        TypeError,
                        ValueError,
                    ) as e:
                        raise ValueError(f"failed to parse line: {s}") from e

                    # Anchor: find the first entry at or before cur_t
                    if not start_line_found:
                        if exact_t is None:
                            if not exclude_cur_t:
                                if (line_t <= cur_t) and (
                                    prev_line_t is None or prev_line_t > cur_t
                                ):
                                    start_line_found = True
                            else:
                                if (line_t < cur_t) and (
                                    prev_line_t is None or prev_line_t >= cur_t
                                ):
                                    start_line_found = True
                        else:
                            if line_t == exact_t:
                                start_line_found = True

                    if start_line_found:
                        if exact_t is not None:
                            if line_t != exact_t:
                                return
                        elif max_lines is not None:
                            if len(collected_data) >= int(max_lines):
                                return
                        elif max_weeks is not None:
                            if line_t < cur_t.minus_x_weeks(int(max_weeks)):
                                return

                        collected_data.append(data)
                    prev_line_t = line_t

        for p in paths_to_scan:
            scan_one_file(p)

        return list(reversed(collected_data))

    def _read_json(self, path: Path) -> Dict:
        if not path.exists():
            raise FileNotFoundError(path.as_posix())
        return json.loads(path.read_text(encoding="utf-8"))

    # ---------- Profile ----------
    def read_profile(self, target_year: Optional[int] = None) -> Dict:
        """Read persona profile for specified year.

        Args:
            target_year: Year to read. Defaults to current clock year.

        Raises:
            FileNotFoundError: If profile for target_year doesn't exist.
        """
        year = target_year if target_year is not None else self.clock.get_time().year
        root = Path("data") / self.world / "persona" / self.char / "profile"
        path = root / f"year={year}.json"
        if not path.exists():
            raise FileNotFoundError(path.as_posix())
        return self._read_json(path)

    def update_position(
        self,
        position_name: Optional[str],
        weekly_income: int,
        weekly_delta_skills: Dict[str, int],
    ) -> None:
        """Update agent's position in profile (used during position application).

        IMPORTANT: This method writes to NEXT year's profile (year+1).
        It assumes yearly profile update has already run and created year+1 profile.

        Updates the following fields in profile:
        - position.organization
        - position.role (role name within organization)
        - position.weekly_income
        - position.weekly_delta_skills

        The unique identifier (position_id) is "{organization}/{role}".

        Args:
            position_name: Position unique identifier "{organization}/{role}", None if unemployed
            weekly_income: New weekly income
            weekly_delta_skills: Skills gained per week from this position

        Raises:
            FileNotFoundError: If next year's profile doesn't exist (yearly update not run)
        """
        next_year = self.clock.get_time().year + 1

        # Read next year's profile (must exist - yearly update should have created it)
        # This will raise FileNotFoundError if yearly update hasn't run
        profile = self.read_profile(next_year)

        # Update position info
        assert "position" in profile, "Profile missing 'position' field"

        if position_name:
            org, role = Position.parse_name(position_name)
            profile["position"]["organization"] = org
            profile["position"]["role"] = role
        else:
            profile["position"]["organization"] = ""
            profile["position"]["role"] = "Unemployed"

        # Update income and skills in position
        profile["position"]["weekly_income"] = weekly_income
        profile["position"]["weekly_delta_skills"] = weekly_delta_skills

        # Write back to next year
        self.write_profile(profile, next_year)

    def write_profile(self, profile: Dict, year: int) -> None:
        """Write profile for a specific year.

        Args:
            profile: Complete profile dict
            year: Target year
        """
        root = Path("data") / self.world / "persona" / self.char / "profile"
        path = root / f"year={year}.json"
        self._write_json_new(path, profile)

    def get_brief_intro(self, do_clip: bool = True) -> str:
        """Get brief introduction.

        Args:
            do_clip: If True, clip to CLIP_BRIEF (200 chars). Default True.

        Returns:
            Brief introduction string.
        """
        profile = self.read_profile()
        brief = profile["brief_introduction"]
        return clip_str(brief, CLIP_BRIEF) if do_clip else brief

    def get_profile_for_home(self) -> str:
        """Get profile for home generation (more detail than brief).

        Used for: mapgen home locations.
        Includes clipped appearance + full description.

        Returns:
            Formatted string with clipped appearance and full description.
        """
        profile = self.read_profile()
        appearance = clip_str(profile["appearance_and_impression"], CLIP_APPEARANCE)
        return (
            f"- Appearance: {appearance}\n"
            f"- Description:\n{profile['brief_introduction']}\n"
            f"{profile['details']}"
        )

    def get_profile_for_activity_eval(self) -> str:
        """Get condensed profile for God Model activity evaluation.

        Used for: evaluate_joint_activity, evaluate_public_activity.
        More detail than brief but clipped to avoid prompt overflow.
        Includes: clipped appearance, brief intro, personality summary, all skills.

        Returns:
            Formatted string for God Model context.
        """
        profile = self.read_profile()
        appearance = clip_str(profile["appearance_and_impression"], CLIP_APPEARANCE)

        # Personality summary (qualitative only, no quantitative details)
        pt = profile["personality_traits"]
        personality = pt["qualitative"]

        # All skills from state
        state = self.read_state(exclude_cur_t=False)
        skills = state.get("skills") or profile.get("init_skills", {})
        skills_str = (
            ", ".join(f"{k}: {v}" for k, v in skills.items()) if skills else "None"
        )

        return (
            f"- Appearance: {appearance}\n"
            f"- Description: {profile['brief_introduction']}\n"
            f"- Personality: {personality}\n"
            f"- Skills: {skills_str}"
        )

    def _read_others_profile(self, who: str) -> Optional[Dict[str, Any]]:
        """Read another persona's profile (current year or fallback to previous).

        Returns None if profile not found.
        """
        if not who:
            return None
        root = Path("data") / self.world / "persona" / who / "profile"
        year = self.clock.get_time().year
        cur = root / f"year={year}.json"
        target = cur if cur.exists() else (root / f"year={year - 1}.json")
        if not target.exists():
            return None
        return self._read_json(target)

    def is_mutually_known(self, who: str) -> bool:
        """Check if self and who mutually know each other.

        Mutual knowledge = both have each other's character scratchpad.
        """
        if not who or who == self.char:
            return False

        # I have their scratchpad?
        my_sp = self.character_scratchpads / f"{who}.jsonl"
        i_know_them = my_sp.exists() and self._created_before_cur_t(my_sp)

        if not i_know_them:
            return False

        # They have my scratchpad?
        their_sp = (
            Path("data")
            / self.world
            / "persona"
            / who
            / "memory"
            / "scratchpad"
            / "characters"
            / f"{self.char}.jsonl"
        )
        they_know_me = their_sp.exists()

        return i_know_them and they_know_me

    def read_others_pub_info(self, who: str) -> str:
        """Return another persona's public info.

        In this world, everyone knows each other's basic public info
        (appearance, brief intro, position) even if not formally acquainted.

        Args:
            who: Name of the other persona.

        Returns:
            Full public info: appearance + brief + position.
        """
        obj = self._read_others_profile(who)
        if not obj:
            return ""

        appearance = clip_str(obj["appearance_and_impression"].strip(), CLIP_APPEARANCE)
        brief = clip_str(obj["brief_introduction"].strip(), CLIP_BRIEF)

        pos = obj["position"]
        org = pos["organization"]
        role = pos["role"]
        pos_type = pos["type"]
        weekly_income = pos["weekly_income"]
        description = clip_str(pos["description"].strip(), CLIP_POS_DESC)

        position_str = f"{org}/{role}" if org else role
        position_block = (
            f"Position: {position_str} ({pos_type}), "
            f"weekly income: {weekly_income}, {description}"
        )

        return f"Appearance: {appearance}\nBrief: {brief}\n{position_block}"

    # ---------- Persona Rendering ----------
    def _infer_age_and_gender_word(self, profile: Dict[str, Any]) -> tuple[str, str]:
        year = self.clock.get_time().year
        age_val: Optional[int] = None
        if isinstance(profile.get("age"), int):
            age_val = profile["age"]
        elif isinstance(profile.get("birth_year"), int):
            age_val = year - int(profile["birth_year"])  # coarse

        gender_raw = str(profile.get("gender", "")).strip()
        male_markers = {"男", "male", "Male", "m", "M"}
        female_markers = {"女", "female", "Female", "f", "F"}
        gender_type: Optional[str] = None
        if gender_raw in male_markers:
            gender_type = "male"
        elif gender_raw in female_markers:
            gender_type = "female"

        if gender_type is None:
            gender_word = "person"
        else:
            if age_val is not None and age_val <= 18:
                gender_word = "boy" if gender_type == "male" else "girl"
            else:
                gender_word = "man" if gender_type == "male" else "woman"

        age_text = str(age_val) if age_val is not None else "unknown"
        return age_text, gender_word

    def _read_state_current(
        self,
        exclude_cur_t: bool = True,
        at_t: Optional[str | TimeState] = None,
    ) -> Dict[str, Any]:
        """Read state from state.jsonl.

        If at_t is provided and no records found at or before that time,
        raises IndexError (the caller is querying a historical time with no data).

        If at_t is None and state.jsonl is empty/missing, initializes from profile.

        Args:
            exclude_cur_t: Whether to exclude entries at current time (default True).
                          Set to False when need to read latest state within same time slot.
            at_t: Reference time. If None, uses clock.get_time().
        """
        path = self.root / "state.jsonl"
        entries = self._read_jsonl(
            path, max_lines=1, exclude_cur_t=exclude_cur_t, at_t=at_t
        )
        if entries:
            return entries[-1]["content"]

        # Historical query with no data — don't pollute state.jsonl
        if at_t is not None:
            raise IndexError(f"No state record found at or before {at_t}")

        # First-time read with no state file — initialize from profile
        return self._initialize_state_from_profile()

    def _initialize_state_from_profile(self) -> Dict[str, Any]:
        """Initialize state from profile and save to state.jsonl.

        Creates initial state with:
        - vitality: 70
        - fulfillment: {mood: 50, material: 50, social: 50, esteem: 50}
        - skills: from profile["init_skills"]
        - assets: from profile["init_assets"] (deposit + possessions)
        """
        profile = self.read_profile()
        init_skills = profile["init_skills"]
        init_assets = profile["init_assets"]

        state = {
            "vitality": 70,
            "fulfillment": {
                "mood": 50,
                "material": 50,
                "social": 50,
                "esteem": 50,
            },
            "skills": init_skills,
            "assets": {
                "deposit": init_assets["deposit"],
                "possessions": init_assets.get("possessions", []),
            },
        }

        # Save initial state (uses clock's current time via _append_jsonl)
        self._append_jsonl(
            self.root / "state.jsonl",
            {"content": state},
        )
        self.logger.info(f"Initialized state from profile for {self.char}")
        return state

    def read_vitality_prompt(self) -> str:
        """Build vitality prompt section."""
        state = self._read_state_current(exclude_cur_t=False)
        val = state["vitality"]
        vitality_line = (
            f"{indent}- Vitality: {val}/100 (physical energy level)\n"
            f"{indent}  (10 = extremely exhausted/stressed/unhealthy, 30 = fatigued, 50 = baseline, 70 = energetic, 90 = highly relaxed and energized)"
        )
        vitality_line += _misery_hint(val, indent)
        return f"### Vitality\n{vitality_line}"

    def read_fulfillment_prompt(self) -> str:
        """Build fulfillment prompt section."""
        state = self._read_state_current(exclude_cur_t=False)
        fulfillment_header = (
            f"{indent}- Fulfillment: (0-100, higher values indicate greater fulfillment)\n"
            f"{indent}  (10 = extremely unsatisfied, 30 = somewhat unsatisfied, 50 = neutral, 70 = somewhat satisfied, 90 = extremely satisfied/euphoric)"
        )
        fulfillment_definitions = {
            "mood": "mental and physical pleasure from experiences",
            "material": "material satisfaction from consumption and possession",
            "social": "social connection and belonging",
            "esteem": "sense of competence, achievement, and recognition",
        }
        lines = []
        for k in FULFILLMENT_DIMS:
            val = state["fulfillment"][k]
            line = (
                f"{indent}- {k.capitalize()}: {val}/100 ({fulfillment_definitions[k]})"
            )
            line += _misery_hint(val, indent)
            lines.append(line)
        fulfillment_lines = "\n".join(lines)
        fulfillment_block = fulfillment_header + "\n" + fulfillment_lines
        return f"### Fulfillment\n{fulfillment_block}"

    def read_assets_prompt(self) -> str:
        """Build assets prompt section (includes weekly_income, deposit, possessions)."""
        state = self._read_state_current(exclude_cur_t=False)
        assets = state["assets"]

        # REQ-10: Income from two sources
        # weekly_income = position income + extra_income
        profile = self.read_profile()
        position = profile["position"]  # Required field - must exist
        role = position["role"]
        org = position["organization"]
        position_income = position["weekly_income"]  # Required field in position
        extra_income = profile.get("extra_income", 0)  # Optional: LLM may omit this
        total_weekly_income = position_income + extra_income

        assets_income = (
            f"{indent}- Weekly Income: {total_weekly_income} "
            f"({role}@{org}: {position_income}, other source: {extra_income})"
        )
        assets_deposit = f"{indent}- Deposit: {assets['deposit']}"

        # Build detailed possessions list with limit info
        possessions = assets["possessions"]
        max_possessions = config["world"]["solo_activity"]["max_possessions"]
        count = len(possessions)

        if possessions:
            possession_lines = [f"{indent}- Possessions ({count}/{max_possessions}):"]
            for item in possessions:
                # Required fields: direct access to expose errors
                name = item["name"]
                desc = item["description"]

                # Format base information
                details = f"{double_indent}- {name} ({desc})"

                # Optional fields: check existence before appending
                if "purchase_price" in item:
                    details += f", price: {item['purchase_price']}"
                if "from" in item:
                    details += f", from: {item['from']}"

                possession_lines.append(details)

            assets_possessions = "\n".join(possession_lines)
        else:
            assets_possessions = f"{indent}- Possessions (0/{max_possessions}): None"

        assets_block = "\n".join([assets_income, assets_deposit, assets_possessions])
        return f"### Assets\n{assets_block}"

    def read_skills_prompt(self) -> str:
        """Build skills prompt section."""
        state = self._read_state_current(exclude_cur_t=False)
        skills = state["skills"]
        if skills:
            skills_block = "\n".join([f"{indent}- {k}: {v}" for k, v in skills.items()])
        else:
            skills_block = f"{indent}- No skills yet"
        return f"### Skills\n{skills_block}"

    def read_state_prompt(self) -> str:
        """Build complete prompt with vitality/fulfillment/assets/skills sections.

        Wrapper that combines output from the four sub-functions.
        """
        return "\n\n".join(
            [
                self.read_vitality_prompt(),
                self.read_fulfillment_prompt(),
                self.read_assets_prompt(),
                self.read_skills_prompt(),
            ]
        )

    def read_state(
        self,
        exclude_cur_t: bool = True,
        at_t: Optional[str | TimeState] = None,
    ) -> Dict[str, Any]:
        """Public method to read current state.

        Args:
            exclude_cur_t: Whether to exclude entries at current time (default True).
                          Set to False when need to read latest state within same time slot.
            at_t: Reference time. If None, uses clock.get_time().

        Returns the full state dict with vitality, fulfillment, skills, and assets.
        """
        return self._read_state_current(exclude_cur_t=exclude_cur_t, at_t=at_t)

    def get_deposit(self) -> int:
        """Get current deposit from state."""
        state = self._read_state_current(exclude_cur_t=False)
        return state["assets"]["deposit"]

    def get_deposit_at_year_start(self, year: int) -> int:
        """Get deposit at the beginning of a year from state.jsonl.

        Reads the state entry at Y{year}-W00-begin, which is written during
        world initialization (first year) or year-end transitions.
        Falls back to initial profile deposit if no state exists yet (e.g. resume).
        """
        year_begin = TimeState.get_year_begin(year)
        try:
            state = self.read_state(at_t=year_begin, exclude_cur_t=False)
        except IndexError:
            profile = self.read_profile()
            return profile["init_assets"]["deposit"]
        return state["assets"]["deposit"]

    def save_state(self, state: Dict[str, Any]) -> None:
        """Save full state dict to state.jsonl."""
        self._append_jsonl(self.root / "state.jsonl", {"content": state})

    def get_fulfillment(self) -> Dict[str, int]:
        """Get current fulfillment values."""
        state = self._read_state_current(exclude_cur_t=False)
        return state["fulfillment"]

    def get_recent_weekly_deltas(self, n_weeks: int) -> Dict[str, List[int]]:
        """Get fulfillment deltas (changes) for the last N weeks.

        Reads state.jsonl and computes week-over-week changes for each
        fulfillment dimension. Returns both positive and negative deltas.

        Args:
            n_weeks: Number of past weeks to include.

        Returns:
            Dict mapping dimension name to list of weekly deltas.
            E.g., {"mood": [5, -2, 3], "social": [2, 4, -1], ...}
        """
        state_path = self.root / "state.jsonl"
        if not state_path.exists():
            return {}

        cur_t = self.clock.get_time()

        # Need n_weeks+1 state snapshots to compute n_weeks deltas.
        # E.g. to compute deltas for W02 and W03, we need snapshots at W01, W02, W03.
        weeks_to_query = [cur_t.minus_x_weeks(i + 1) for i in range(n_weeks, -1, -1)]

        # Fetch the state snapshot at the start of each week
        week_states: Dict[str, Dict[str, int]] = {}
        for week_t in weeks_to_query:
            week_key = week_t.repr_week()
            try:
                state = self.read_state(at_t=week_t, exclude_cur_t=False)
                week_states[week_key] = state["fulfillment"]
            except (IndexError, KeyError):
                # No records before this week — skip
                continue

        if len(week_states) < 2:
            return {}

        # Sort weeks and compute deltas
        sorted_weeks = sorted(week_states.keys())
        first_state = week_states[sorted_weeks[0]]
        result: Dict[str, List[int]] = {k: [] for k in first_state.keys()}

        for i in range(1, len(sorted_weeks)):
            prev_state = week_states[sorted_weeks[i - 1]]
            curr_state = week_states[sorted_weeks[i]]
            for key in result:
                result[key].append(curr_state[key] - prev_state[key])

        return result

    def get_fulfillment_history(self, n_weeks: int) -> List[Dict[str, Any]]:
        """Get fulfillment snapshots for the last N weeks.

        Used for subjective reward calculation.

        Args:
            n_weeks: Number of data points to include.
                     Returns N-1 historical week BEGINs + current state.

        Returns:
            List of dicts, each containing:
            - time: str (e.g., "Y2020-W05-begin" or "Y2020-W05-activity-D3")
            - fulfillment: Dict[str, int] (mood, material, social, esteem)
            - vitality: int
            Sorted from oldest to newest.
        """
        state_path = self.root / "state.jsonl"
        if not state_path.exists():
            return []

        cur_t = self.clock.get_time()
        results: List[Dict[str, Any]] = []

        for i in range(n_weeks - 1, -1, -1):
            if i > 0:
                week_t = cur_t.minus_x_weeks(i)
            else:
                # i == 0: current week's current state
                week_t = cur_t
            try:
                state = self.read_state(at_t=week_t, exclude_cur_t=False)
            except IndexError:
                # No state recorded for this week yet - expected for early weeks
                continue
            # Direct access - let KeyError propagate if schema is wrong
            results.append(
                {
                    "time": str(week_t),
                    "fulfillment": state["fulfillment"],
                    "vitality": state["vitality"],
                }
            )

        return results

    def apply_fulfillment_decay(self, decays: Dict[str, int]) -> None:
        """Apply decay values to current fulfillment.

        Args:
            decays: Dict mapping dimension name to decay amount.
                    Must contain all keys present in state fulfillment.
        """
        current = self._read_state_current(exclude_cur_t=False)
        for key in decays:
            old_value = current["fulfillment"][key]
            new_value = max(0, old_value - decays[key])
            current["fulfillment"][key] = new_value
        self.save_state(current)

    def update_deposit(self, new_deposit: int) -> None:
        """Update deposit in state."""
        current = self._read_state_current(exclude_cur_t=False)
        current["assets"]["deposit"] = new_deposit
        self.save_state(current)

    def get_possessions(self) -> List[Dict[str, str]]:
        """Get current possessions list from state (as object list)."""
        state = self._read_state_current(exclude_cur_t=False)
        return state["assets"]["possessions"]

    def update_possessions(self, new_possessions: List[Dict[str, str]]) -> None:
        """Update possessions in state (replaces entire list with object list)."""
        current = self._read_state_current(exclude_cur_t=False)
        current["assets"]["possessions"] = new_possessions
        self.save_state(current)

    def character_prompt(self) -> str:
        """Render PERSONA_TEMPLATE using current time, profile, and state.

        Debug-friendly: required fields missing -> return ERROR message (not raise).
        Only keep minimal necessary fallbacks (e.g., state when absent).
        """
        profile = self.read_profile()

        # Infer age/gender (error if gender invalid)
        age_text, gender_word = self._infer_age_and_gender_word(profile)

        # Position
        position_block = "\n".join(
            [f"{indent}- {k}: {v}" for k, v in profile["position"].items() if v != ""]
        )

        # Personality traits
        pt = profile["personality_traits"]
        qualitative_block = f"{indent}- Qualitative: {pt['qualitative']}"
        quantitative_block = f"{indent}- Quantitative (0-100):\n" + "\n".join(
            [f"{double_indent}- {k}: {v}" for k, v in pt["quantitative"].items()]
        )

        personality_block = qualitative_block + "\n" + quantitative_block

        core_motivation = f"{indent}- Core Motivation:{profile['core_motivation']}"
        conflicts = f"{indent}- Conflicts:{profile['conflicts']}"
        values = f"{indent}- Values:{profile['values']}"

        # Detroit civic identity
        founder_id = profile.get("founder_id")
        lineage = profile.get("lineage") if isinstance(profile.get("lineage"), dict) else {}
        origin = profile.get("origin") if isinstance(profile.get("origin"), dict) else {}
        if founder_id:
            values += f"\n{indent}- Agentopia Detroit Founding Citizen: {founder_id}"
        elif lineage.get("type"):
            values += f"\n{indent}- Agentopia Detroit Lineage: {lineage.get('type')}"
        if origin.get("city"):
            place = ", ".join(str(x) for x in (origin.get("city"), origin.get("region"), origin.get("country")) if x)
            values += f"\n{indent}- Civic Origin: {place}"

        faction = profile.get("faction")
        if isinstance(faction, dict) and faction.get("name"):
            faction_name = str(faction.get("name"))
            faction_role = str(faction.get("role") or "member")
            faction_alignment = str(faction.get("alignment") or "")
            faction_doctrine = str(faction.get("doctrine") or "")
            values += (
                f"\n{indent}- Faction: {faction_name}"
                f"\n{double_indent}- Role: {faction_role}"
                f"\n{double_indent}- Alignment: {faction_alignment}"
                f"\n{double_indent}- Doctrine: {faction_doctrine}"
            )

        # Talents
        talents = profile["talents"]
        talents_qualitative = f"{indent}- Qualitative: {talents['qualitative']}"
        talents_quantitative = f"{indent}- Quantitative:\n" + "\n".join(
            [f"{double_indent}- {k}: {v}" for k, v in talents["quantitative"].items()]
        )
        talents_block = talents_qualitative + "\n" + talents_quantitative

        # Current state (Vitality, Fulfillment, Assets, Skills from state.jsonl)
        vitality_prompt = self.read_vitality_prompt()
        fulfillment_prompt = self.read_fulfillment_prompt()
        assets_prompt = self.read_assets_prompt()
        skills_prompt = self.read_skills_prompt()

        return PERSONA_TEMPLATE.format(
            name=self.char,
            age=age_text,
            gender=gender_word,
            appearance_and_impression=profile["appearance_and_impression"],
            brief_introduction=profile["brief_introduction"],
            details=profile["details"],
            position=position_block,
            personality_traits=personality_block,
            core_motivation=core_motivation,
            conflicts=conflicts,
            values=values,
            preferences=profile["preferences"],
            talents=talents_block,
            vitality=vitality_prompt,
            fulfillment=fulfillment_prompt,
            assets=assets_prompt,
            skills=skills_prompt,
        )

    def roleplay_prompt(
        self,
        *,
        required_characters: Optional[List[str]] = None,
        location_desc: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build the base roleplay prompt (persona + worldview + scratchpads).

        When used inside JointActivity, pass participants as
        `required_characters` so their character pads are guaranteed to
        appear in the scratchpad listing even under a tight limit.
        """
        persona_text = self.character_prompt()
        recent_scratchpads = self.list_scratchpads(
            character_limit=24, required_characters=required_characters
        )

        from src.agents.prompts import (
            WORLDVIEW,
            SCRATCHPAD_PROMPT,
            COMMONSENSE,
            REQUIREMENTS,
            ROLEPLAY_PRINCIPLES,
        )

        # Current location info: only included when explicitly provided (e.g. joint/public activity).
        # Solo activity passes no location_desc, so no location block is added to the prompt.
        location_block = (
            f"## Current Location and Surroundings:\n{location_desc}"
            if location_desc
            else ""
        )

        parts = [
            persona_text,
            WORLDVIEW,
            SCRATCHPAD_PROMPT.format(recent_scratchpads=recent_scratchpads),
            self.recent_history_prompt(),
            location_block,
            COMMONSENSE,
            ROLEPLAY_PRINCIPLES,
            REQUIREMENTS.replace("<char>", self.char),
            self.time_prompt(),
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "system", "content": prompt}]

    def time_prompt(self) -> str:
        t = self.clock.get_time()
        return f"## Current Time:\n{str(t)} (year={t.year}, week={t.week}, stage={t.stage.name.lower()}).\n\n"

    def plan_prompt(self) -> List[Dict[str, str]]:
        """Build weekly planning messages with persona text and time context."""

        from src.agents.prompts import PLAN_PROMPT

        parts = [
            self.list_schedule(),
            PLAN_PROMPT,
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "user", "content": prompt}]

    def signup_prompt(self, events_list: str) -> List[Dict[str, str]]:
        """Build the BEFORE_CONTACT phase prompt for public event signup.

        Args:
            events_list: Formatted string of available public events
        """
        from src.agents.prompts import PUBLIC_SIGNUP_PROMPT

        parts = [
            self.list_schedule(),
            PUBLIC_SIGNUP_PROMPT.format(events_list=events_list),
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "user", "content": prompt}]

    def contact_prompt(self) -> List[Dict[str, str]]:
        """Build the per-contact-phase prompt with concrete time window tips.

        Adds an explicit, unambiguous scheduling window based on config:
        allowed weeks are [current, current+N] inclusive, where N is
        contact.max_weeks_for_future_schedule. This reduces LLM ambiguity.
        """
        t = self.clock.get_time()
        from src.agents.prompts import CONTACT_PROMPT

        # Compute closed-interval upper bound week for clarity in prompt
        max_weeks = int(
            config["world"]["contact"]["max_weeks_for_future_schedule"]
        )  # e.g. 4
        n_week = int(config["world"]["time"]["n_week"])  # for wrap

        last_y = t.year
        last_w = t.week + max_weeks
        while last_w > n_week:
            last_w -= n_week
            last_y += 1
        window_line = f"(You may only schedule future activities within weeks Y{t.year}-W{t.week:02d} to Y{last_y}-W{last_w:02d} (inclusive).)"
        last_slot_errors = (
            "## Errors from Last Contact Slot\n(Role actions with errors are treated as invalid and automatically discarded. They won't be sent to others.)\n\n"
            + self.last_slot_errors
            if self.last_slot_errors
            else ""
        )

        contact_history = "## Contact History\n\n" + self.read_message()

        # Auto-inject map so Agent doesn't need to call read_map() manually
        map_info = self.read_map()

        parts = [
            self.list_schedule(),
            last_slot_errors,
            contact_history,
            map_info,
            window_line,
            CONTACT_PROMPT,
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "user", "content": prompt}]

    def finalize_contact_prompt(
        self, scheduling_results_str: str
    ) -> List[Dict[str, str]]:
        t = self.clock.get_time()
        from src.agents.prompts import CONTACT_PROMPT, AFTER_CONTACT_PROMPT

        contact_history = "## Contact History\n\n" + self.read_message()

        parts = [
            self.list_schedule(),
            CONTACT_PROMPT,
            contact_history,
            AFTER_CONTACT_PROMPT.format(scheduling_results=scheduling_results_str),
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "user", "content": prompt}]

    def _build_participants_pub_info_block(
        self,
        participants: Optional[List[str]],
    ) -> str:
        """Build lines of other participants' public info (no header)."""
        if not participants:
            return ""
        lines: List[str] = []
        for nm in participants:
            if nm == self.char:
                continue
            info = self.read_others_pub_info(nm)
            assert len(info) > 0, f"No public info for {nm}"
            lines.append(f"- {nm}:\n  {info.replace(chr(10), chr(10) + '  ')}")
        return "\n".join(lines)

    def activity_prompt(
        self,
        activity_type: str,
        activity_background: Optional[str] = None,
        location_desc: Optional[str] = None,
        participants: Optional[List[str]] = None,
        on_enter_activity: bool = False,
        activity_name: Optional[str] = None,
        event_description: Optional[str] = None,
        group_info: str = "",
    ) -> List[Dict[str, str]]:
        """Build the initial Activity-stage prompt for the agent.

        Args:
            activity_type: 'joint', 'solo', or 'public'
            activity_background: concise background for today's activity (who/what/why)
            location_desc: pre-generated location description (including extras)
            participants: list of participant names (for joint/public activities)
            on_enter_activity: whether this is the entry phase (joint only)
            activity_name: name of the activity (for public activities)
            event_description: description of the event (for public activities)
            group_info: group info string for large public activities (e.g. " (Group 1 of 3)")
        """

        if activity_type == "joint":
            if on_enter_activity:
                from src.agents.prompts import ENTER_ACTIVITY_PROMPT

                ACTIVITY_PROMPT = ENTER_ACTIVITY_PROMPT
            else:
                from src.agents.prompts import JOINT_ACTIVITY_PROMPT

                ACTIVITY_PROMPT = JOINT_ACTIVITY_PROMPT

            participants_info = self._build_participants_pub_info_block(participants)
            participants_info_blk = (
                "## Other Participants\n" + participants_info
                if participants_info
                else ""
            )

            environment_description = (
                f"## Activity Location:\n{location_desc}" if location_desc else ""
            )

            parts = [
                self.list_schedule(),
                activity_background,
                environment_description,
                participants_info_blk,
                ACTIVITY_PROMPT,
            ]

        elif activity_type == "solo":
            from src.agents.prompts import SOLO_ACTIVITY_PROMPT

            ACTIVITY_PROMPT = SOLO_ACTIVITY_PROMPT

            parts = [
                self.list_schedule(),
                ACTIVITY_PROMPT,
            ]

        elif activity_type == "public":
            from src.agents.prompts import PUBLIC_ACTIVITY_PROMPT

            participants_info = self._build_participants_pub_info_block(participants)
            # Build group notice if activity is split into groups
            group_notice = (
                f"\n\nNote: Due to the large number of participants, this activity is split into groups. "
                f"You are in{group_info}. You can only see and interact with people in your group."
                if group_info
                else ""
            )
            other_participants_blk = (
                f"## Other Participants Present{group_info} (observe only, no interaction)\n"
                + participants_info
                + group_notice
                if participants_info
                else ""
            )

            ACTIVITY_PROMPT = PUBLIC_ACTIVITY_PROMPT.format(
                event_name=activity_name,
                event_description=event_description or "",
                other_participants_block=other_participants_blk,
            )

            parts = [
                self.list_schedule(),
                ACTIVITY_PROMPT,
            ]

        else:
            raise ValueError(f"Unknown activity_type: {activity_type}")

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])

        return [{"role": "user", "content": prompt}]

    def review_prompt(self) -> List[Dict[str, str]]:
        """Build the review-phase prompt with this week's context."""
        from src.agents.prompts import REVIEW_PROMPT

        parts = [
            REVIEW_PROMPT,
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])
        return [{"role": "user", "content": prompt}]

    def settle_prompt(self, discard_count: int, max_items: int) -> List[Dict[str, str]]:
        """Build the settle-phase prompt for weekly cleanup.

        Note: Should be combined with roleplay_prompt() at call site.
        """
        from src.agents.prompts import SETTLE_DISCARD_PROMPT

        possessions = self.get_possessions()
        possessions_formatted = "\n".join(
            [f"- {item['name']}: {item.get('description', '')}" for item in possessions]
        )

        parts = [
            SETTLE_DISCARD_PROMPT.format(
                possessions=possessions_formatted,
                discard_count=discard_count,
                max_items=max_items,
            ),
        ]

        prompt = "\n\n".join([h.strip() for h in parts if h.strip() != ""])
        return [{"role": "user", "content": prompt}]

    def clear_week_responses(self) -> None:
        self.response_this_week = []

    def save_to_week_response(self, response: str) -> None:
        self.response_this_week.append(
            {"time": self.clock.get_time(), "response": response}
        )

    def recent_history_prompt(self) -> str:
        """Compose a brief context of recent history for prompts.

        1) Previous weeks: weekly diary summaries
        2) Recent activities: joint/solo activity records
        3) This week: already-generated responses earlier than current time
        """
        parts: List[str] = []

        # 1) Weekly summaries from previous weeks
        n_weeks = config["world"]["context"]["recent_summary_weeks"]
        summaries = self.read_weekly_summaries(n_weeks=n_weeks)
        if summaries:
            parts.append("## Your Summaries from Previous Weeks")
            for s in summaries:
                t_obj = TimeState.from_string(s["time"])
                week_str = t_obj.repr_week()
                content = s["content"]
                parts.append(f"- [{week_str}] {content}")

        # 2) Recent activities
        max_weeks = config["world"]["context"]["recent_activities_weeks"]
        recent_activities = self.read_recent_activities(max_weeks=max_weeks)
        if recent_activities:
            parts.append(recent_activities)

        # 3) This week's earlier thoughts/actions/responses
        t = self.clock.get_time()
        if self.response_this_week:
            parts.append("## Your Previous Thoughts, Actions and Responses This Week")
            for resp in self.response_this_week:
                rt = resp["time"]

                # CONTACT responses only shown during CONTACT stage
                if rt.stage == Stage.CONTACT and t.stage != Stage.CONTACT:
                    continue

                parts.append(f"- [{rt}] {resp['response']}")

        return "\n\n".join(parts)

    def read_home_info(self) -> str:
        """Return surroundings text for the character's home."""
        return self.location_store.get_char_home(self.char)

    def _load_create_timestate(self, path: Path) -> Optional[TimeState]:
        # Return None if file does not exist or is empty

        if not path.exists():
            ERROR_LOGGER.warning(
                "Scratchpad file does not exist for create_timestate lookup: %s",
                path.as_posix(),
            )
            return None

        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue

                data = json.loads(line)
                return TimeState.from_string(data["time"])

            ERROR_LOGGER.warning(
                "Scratchpad file is empty for create_timestate lookup: %s",
                path.as_posix(),
            )
            return None

    def _get_create_timestate(self, scratchpad: Path | str) -> Optional[TimeState]:
        key = str(scratchpad)

        if key in self._scratchpad_create_times:
            return self._scratchpad_create_times[key]

        create_time = self._load_create_timestate(scratchpad)
        if create_time:
            self._scratchpad_create_times[key] = create_time

        return create_time

    def _created_before_cur_t(self, p: Path | str) -> bool:
        create_time = self._get_create_timestate(p)
        if create_time:
            return create_time < self.clock.get_time()
        else:
            # Not created yet
            return False

    def _pad_id_of(self, path: Path) -> str:
        """Return canonical scratchpad id for a given jsonl path."""
        if path == self.general_scratchpad:
            return "general"
        return path.relative_to(self.scratch).with_suffix("").as_posix()

    # --- Character Scratchpad Utilities ---
    def initiate_character_scratchpad(self, who: str) -> bool:
        """Create characters/<who>.jsonl with first impression when missing.

        Called when participants first meet in Joint/Encounter/Public activities.

        Args:
            who: Name of the character to create scratchpad for

        Returns:
            True if created successfully, False if already exists or invalid
        """
        who = str(who).strip()
        if not who or who == self.char:
            return False

        path = self.character_scratchpads / f"{who}.jsonl"

        if path.exists():
            create_t = self._get_create_timestate(path)
            if create_t is not None:
                # File has content — already created
                return False
            # File exists but is empty (e.g. leftover from interrupted write)
            # — proceed to (re-)create

        # First-meet: read_others_pub_info returns appearance only (not mutually known yet)
        pub_info = self.read_others_pub_info(who)
        t_str = str(self.clock.get_time())

        content = f"You first met {who} at {t_str}. Your first impression of {who}: {pub_info}"
        body = f"<summary>{content}</summary>\n<full>{content}</full>"
        res = self.update_scratchpad(
            f"characters/{who}",
            body,
            create_new_scratchpad=True,
            allow_characters_create=True,
        )
        return res.startswith("SUCCESS:")

    def _init_last_access_map(self) -> None:
        """Initialize last-access map by scanning access_log once (backwards)."""
        self.pad_last_access_map.clear()
        cur_t = self.clock.get_time()

        with FileReadBackwards(self.access_log, encoding="utf-8") as frb:
            for line in frb:
                # line belike: {"time": "Y2025-W10-plan", "pad": "characters/alice", "action": "write"}
                s = line.strip()
                if not s:
                    continue
                try:
                    data = json.loads(s)
                except Exception:
                    continue
                pad = data.get("pad")
                if not isinstance(pad, str) or not pad:
                    continue
                if pad in self.pad_last_access_map:
                    continue
                try:
                    t = TimeState.from_string(str(data.get("time", "")))
                except Exception:
                    continue
                if t < cur_t:
                    self.pad_last_access_map[pad] = t
        # print(self.pad_last_access_map)
        # belike: {'characters/bob': TimeState(year=2025, week=10, stage=<Stage.PLAN: 1>, day=0, slot=0), 'characters/alice': TimeState(year=2025, week=10, stage=<Stage.PLAN: 1>, day=0, slot=0)}

    # ---------- Scratchpad ----------

    def _get_sorted_scratchpad_paths(
        self, base_dir: Path, limit: Optional[int] = None
    ) -> List[Path]:
        """Return sorted scratchpad paths (generic version).

        Args:
            base_dir: Scratchpad directory (character_scratchpads or other_scratchpads).
            limit: Optional maximum number of results to return.

        Returns:
            Paths sorted by most-recently-accessed time.
        """

        def _filter_future(paths: List[Path]) -> List[Path]:
            eligible: List[Path] = []
            for p in paths:
                if self._created_before_cur_t(p):
                    eligible.append(p)
            return eligible

        def _sort_paths(paths: List[Path]) -> List[Path]:
            def _key(path: Path) -> Tuple[int, TimeState | None, str]:
                pid = self._pad_id_of(path)
                last = self.pad_last_access_map.get(pid)
                return (1 if last is not None else 0, last, pid)

            return sorted(paths, key=_key, reverse=True)

        # Collect and filter
        paths = _filter_future(
            sorted(base_dir.rglob("*.jsonl"), key=lambda p: p.as_posix())
        )

        # Sort by recency
        paths = _sort_paths(paths)

        # Apply limit
        if limit is not None and limit > 0:
            paths = paths[:limit]

        return paths

    def list_scratchpads(
        self,
        character_limit: Optional[int] = 50,
        other_limit: Optional[int] = 10,
        with_explain: Optional[bool] = False,
        required_characters: Optional[List[str]] = None,
    ) -> str:
        """List scratchpads with optional limits and required characters.

        - character_limit: max number of character scratchpads to show (default 50).
        - other_limit: max number of other scratchpads to show (default 10).
        - None means no limit (show all).
        - Sort by last access time from access_log (desc); fallback to
          creation time (desc) when no access record.
        - required_characters: ensure these character pads (if exist) appear
          in the characters section even when applying limit.

        The characters section also serves as the list of interactable people
        in this simulation - agents can only interact with characters shown here.
        """

        def _format_items(paths: List[Path]) -> List[str]:
            lines: List[str] = []
            for p in paths:
                name = p.with_suffix(".txt").name
                item_lines: List[str] = [f"{indent}- {name}"]
                if p.parent == self.character_scratchpads:
                    who = p.with_suffix("").name
                    item_lines.append(
                        self._render_summary_and_public(
                            who=who, base_indent=double_indent
                        )
                    )
                else:
                    # For non-character pads, only show summary (if any)
                    summary = self._read_last_summary_of(p)
                    if summary:
                        summary_indented = _indent_multiline(summary, double_indent)
                        item_lines.append(
                            f"{double_indent}- scratchpad summary: {summary_indented}"
                        )
                lines.append("\n".join(item_lines))
            return lines

        def _normalize_required(names: Optional[List[str]]) -> List[str]:
            if not names:
                return []
            out: List[str] = []
            for n in names:
                s = str(n).strip()
                if not s:
                    continue
                if s.startswith("characters/"):
                    s = s[len("characters/") :]
                if s.endswith(".txt"):
                    s = s[:-4]
                if s.endswith(".jsonl"):
                    s = s[:-6]
                out.append(s)
            return out

        # Get sorted paths using shared method (no limit yet - need full list for required merge)
        character_paths = self._get_sorted_scratchpad_paths(self.character_scratchpads)
        other_paths = self._get_sorted_scratchpad_paths(self.other_scratchpads)

        # Apply limits and required characters
        req = _normalize_required(required_characters)
        # Handle required_characters: ensure they appear first
        if req:
            name_to_path: Dict[str, Path] = {
                p.with_suffix("").name: p for p in character_paths
            }
            required_selected: List[Path] = []
            for name in req:
                p = name_to_path.get(name)
                if p is not None:
                    required_selected.append(p)

            # Deduplicate preserving order: required first, then the rest
            merged: List[Path] = []
            seen: set[str] = set()
            for p in required_selected + character_paths:
                key = p.as_posix()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(p)
            character_paths = merged
        # Apply character_limit
        if character_limit is not None and character_limit > 0:
            character_paths = character_paths[:character_limit]
        # Apply other_limit
        if other_limit is not None and other_limit > 0:
            other_paths = other_paths[:other_limit]

        # Compose output
        parts: List[str] = []
        if with_explain:
            parts.append(
                "You have previously maintained the following scratchpads. You can access one or more of them to recall your saved information using the read_scratchpad tool."
            )

        # General (always included)
        gen_summary = self._read_last_summary_of(self.general_scratchpad)
        gen_line = "- general.txt"
        if with_explain:
            gen_line += f"\n{indent}(Your overall long-term goals, planning, reflections, and lessons learned.)"
        if gen_summary:
        # Append summary to general scratchpad
        # Multi-line summary indentation matches characters/others behaviour
            gen_summary_indented = _indent_multiline(gen_summary, indent)
            gen_line += f"\n{indent}- summary: {gen_summary_indented}"
        parts.append(gen_line)

        if character_paths:
            parts.append("- characters/")
            if with_explain:
                parts.append(f"{indent}(Your knowledge about other persons.)")
            parts.append(
                f"{indent}(IMPORTANT: You can ONLY interact with characters listed below. "
                "These are the interactable people in this simulation.)"
            )
            parts.extend(_format_items(character_paths))

        if other_paths:
            parts.append(f"- others/")
            if with_explain:
                parts.append(f"{indent}(Other scratchpads you have created.)")
            parts.extend(_format_items(other_paths))

        return "\n".join(parts)

    def get_top_related_names(self, limit: int = 10) -> List[str]:
        """Return top N related character names sorted by recency.

        Used for encounter generation - only returns names without content.

        Args:
            limit: Maximum number of names to return

        Returns:
            List of character names (sorted by last access time, most recent first)
        """
        paths = self._get_sorted_scratchpad_paths(self.character_scratchpads, limit)
        return [p.with_suffix("").name for p in paths]

    def read_known_people_notes(self, known_names: List[str]) -> str:
        """Build summary of agent's notes about known people.

        Reads the latest summary from each character's scratchpad file.
        Used for social ranking prompt to provide context.

        Args:
            known_names: List of character names to include

        Returns:
            Formatted string with each person's scratchpad summary
        """
        if not known_names:
            return ""

        summaries = []
        for name in sorted(known_names):
            path = self.character_scratchpads / f"{name}.jsonl"
            if not path.exists():
                continue

            summary = self._read_last_summary_of(path)
            if summary:
                summaries.append(f"### {name}\n{summary}")

        return "\n\n".join(summaries) if summaries else ""

    def read_scratchpad(self, s_name: str) -> str:
        """Read scratchpad content by name; supports general/characters/*/others/*.

        Mapping rules:
          - `general(.txt|.jsonl)` -> `scratchpad/general.jsonl`
          - `characters/<who>(.txt|.jsonl)` -> `scratchpad/characters/<who>.jsonl`
          - `others/<name>(.txt|.jsonl)` -> `scratchpad/others/<name>.jsonl`
        Only allows reading if the file was created at or before the current time.
        Returns each line's `content` field (or the raw JSON if missing).
        """
        raw = s_name.strip()
        # Strip user-facing display extension (case-insensitive)
        lower = raw.lower()
        if lower.endswith(".txt"):
            name = raw[:-4]
        elif lower.endswith(".jsonl"):
            name = raw[:-6]
        else:
            name = raw

        # Strict name-to-path mapping (consistent with list_scratchpads output)
        if name == "general":
            path = self.general_scratchpad
        elif name == "working_memory":
            path = self.working_memory
        elif name.startswith("characters/") or name.startswith("others/"):
            path = (self.scratch / name).with_suffix(".jsonl")
        else:
            return f"ERROR: Invalid scratchpad name: {s_name}"

        created = (path.exists() and self._created_before_cur_t(path)) or (
            name in ["general", "working_memory"]
        )

        if not created:
            return f"ERROR: Scratchpad not found: {s_name}"

        # Use the unified JSONL read logic; only 1 entry needed
        entries = self._read_jsonl(path, max_lines=1)

        if len(entries) > 1:
            raise ValueError(f"expected 1 entry, got {len(entries)}")
        elif len(entries) == 0:
            assert name in ["general", "working_memory"]
            name += ".txt"
            return f"SUCCESS: Content of {name} is empty"
        else:
            content = entries[0]["content"]
            name += ".txt"
            # Record a read access (for recency tracking)
            pad_rel = self._pad_id_of(path)
            self._append_jsonl(self.access_log, {"pad": pad_rel, "action": "read"})
            # Dynamically maintain last-access map
            self.pad_last_access_map[pad_rel] = self.clock.get_time()

            return f"SUCCESS: Content of {name}:\n{content}"

    def update_scratchpad(
        self,
        s_name: str,
        content: str,
        create_new_scratchpad: bool = False,
        *,
        allow_characters_create: bool = False,
    ) -> str:
        raw = s_name.strip()
        lower = raw.lower()
        if lower.endswith(".txt"):
            name = raw[:-4]
        elif lower.endswith(".jsonl"):
            name = raw[:-6]
        else:
            name = raw

        # Resolve name to a concrete path; rules are consistent with read_scratchpad
        if name == "general":
            path = self.general_scratchpad
        elif name == "working_memory":
            path = self.working_memory
        elif name.startswith("characters/") or name.startswith("others/"):
            path = (self.scratch / name).with_suffix(".jsonl")
        else:
            return f"ERROR: Invalid scratchpad name: {s_name}"

        created = (name in ["general", "working_memory"]) or (
            path.exists() and self._created_before_cur_t(path)
        )
        # An empty file is treated as "not yet created": externally identical to "file not found"

        split_word = "</summary>" if "</summary>" in content else "<full>"
        if split_word in content:
            summary, full = content.split(split_word, 1)
            summary = summary.replace("<summary>", "").replace("</summary>", "")
            full = full.replace("<full>", "").replace("</full>", "")
        else:
            summary = ""
            full = (
                content.replace("<summary>", "")
                .replace("</summary>", "")
                .replace("<full>", "")
                .replace("</full>", "")
            )

        if create_new_scratchpad:
            if created:
                return f"ERROR: Scratchpad already exists: {s_name}"

            # Allow creating under others/ by default; characters/ requires explicit permission
            if name.startswith("others/"):
                pass  # always allowed
            elif name.startswith("characters/"):
                if not allow_characters_create:
                    return "ERROR: Creating character scratchpads is not allowed in this context"
            else:
                return "ERROR: `s_name` must start with `others/` or `characters/`"

            if summary == "":
                summary = clip_str(full, 500)

            summary = summary.strip()
            full = full.strip()
            record = {"summary": summary, "content": full}
            self._append_jsonl(path, record)
            # Record write access
            pad_rel = self._pad_id_of(path)
            self._append_jsonl(self.access_log, {"pad": pad_rel, "action": "write"})
            # Dynamically maintain last-access map
            self.pad_last_access_map[pad_rel] = self.clock.get_time()

            return f"SUCCESS: Scratchpad {s_name} has been created"
        else:
            if not created:
                return f"ERROR: Scratchpad not found: {s_name}"

            if summary == "":
                # Read previous summary before overwriting
                entries = self._read_jsonl(path, max_lines=1)
                if entries:
                    summary = entries[-1]["summary"]
                else:
                    summary = clip_str(full, 500)

            # Append one JSONL line with time and content
            summary = summary.strip()
            full = full.strip()
            record = {"summary": summary, "content": full}
            self._append_jsonl(path, record)
            # Record write access
            pad_rel = self._pad_id_of(path)
            self._append_jsonl(self.access_log, {"pad": pad_rel, "action": "write"})
            # Dynamically maintain last-access map
            self.pad_last_access_map[pad_rel] = self.clock.get_time()

            return f"SUCCESS: Content of scratchpad {s_name} has been updated"

    def read_location_info(self, location: str) -> str:
        """Return surroundings text for a specified location key.

        Keys should come from read_map(), including public names and private homes.
        """
        return self.location_store.get_surroundings_text(str(location).strip())

    def read_map(self) -> str:
        """List all locations (public + private) as human-readable text.

        Thin wrapper that delegates to LocationStore.read_map_text().
        """
        return self.location_store.read_map_text(self.char)

    # ---------- Message ----------
    def check_char_exist(self, who: str) -> bool:
        """Check whether a persona exists at current time.

        Conditions:
        - The persona directory exists: data/{world}/persona/{who}/profile/
        - At least one profile/year=<YYYY>.json exists; its creation time is
          treated as the BEGIN of that directory's earliest year.
        - That creation time is strictly before the current time.
        """
        profile_dir = Path("data") / self.world / "persona" / who / "profile"
        if not profile_dir.exists() or not profile_dir.is_dir():
            return False

        # Find the earliest profile year: year=YYYY.json
        earliest_year: Optional[int] = None
        for p in profile_dir.glob("year=*.json"):
            stem = p.stem  # like 'year=2020'
            try:
                y = int(stem.split("=")[-1])
            except Exception:
                continue
            if earliest_year is None or y < earliest_year:
                earliest_year = y

        if earliest_year is None:
            return False

        cur_t = self.clock.get_time()
        created_t = TimeState(year=earliest_year, week=1, stage=Stage.BEGIN)
        return created_t < cur_t

    def _sort_contact_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort contact rows for deterministic output.

        Sorting rules:
        1. By time ascending
        2. Within same time: outbound (from=self) before inbound
        3. Within same direction: by seq ascending
        4. Tie-breaker: from, content (for full determinism)
        """

        def _row_key(r: Dict[str, Any]) -> tuple:
            line_t = TimeState.from_string(r["time"])
            frm = r["from"]
            content = r["content"]
            outbound_first = 0 if frm == self.char else 1
            seq = int(r["seq"])
            return (line_t, outbound_first, seq, frm, content)

        return sorted(rows, key=_row_key)

    def send_message(self, to: str, content: str) -> bool:
        """Append a message to both sides' logs and unified signals.

        Layout (append-only, unified files):
        - recipient conversation log: data/{world}/persona/{to}/contact/{me}.jsonl
        - my conversation log:        data/{world}/persona/{me}/contact/{to}.jsonl
        - unified signal per persona: data/{world}/persona/*/contact/sig.jsonl
            - both sender and recipient sides append the same schema:
              {"from": <sender>, "to": <recipient>}

        _append_jsonl will add the current TimeState string as time.
        """
        t = self.clock.get_time()

        # Resolve paths (unified single-file layout)
        to_root = Path("data") / self.world / "persona" / to
        # Validate recipient exists to avoid polluting tree with typos
        if not to_root.exists() or not to_root.is_dir():
            ERROR_LOGGER.error(f"ERROR: recipient '{to}' not found for msg {content}")
            return False
        my_conv = self.contact / f"{to}.jsonl"
        to_conv = to_root / "contact" / f"{self.char}.jsonl"
        # unified signal files record send/receive events per persona
        to_signal = to_root / "contact" / "sig.jsonl"
        my_signal = self.contact / "sig.jsonl"

        # Ensure files exist
        _ensure_file(my_conv)
        _ensure_file(to_conv)
        _ensure_file(to_signal)
        _ensure_file(my_signal)

        # Inject a stable sequence number (seq, starting from 1) for messages
        # within the same CONTACT slot from sender->recipient.
        # This allows the reader to sort by (time, outbound_first, seq) even if
        # concurrent writes cause the physical file order to vary.
        slot_key = str(self.clock.get_time())
        key = (slot_key, to)
        cur_seq = self._send_seq_map.get(key, 0) + 1
        self._send_seq_map[key] = cur_seq

        rec = {"from": self.char, "content": content, "seq": cur_seq}

        # Write conversation on both sides
        self._append_jsonl(my_conv, rec)
        self._append_jsonl(to_conv, rec)

        # Mark unified signals on both sides with the same schema
        sig_row = {"from": self.char, "to": to}
        self._append_jsonl(to_signal, sig_row)
        self._append_jsonl(my_signal, sig_row)
        return True

    def read_message(self) -> str:
        """Build a short context of newly received messages and recent history.

        Definition of "new" here: messages from others whose timestamp equals the
        immediately previous CONTACT slot (same year/week, slot-1). This avoids
        double-reading current-slot outputs and keeps the context small.
        """
        t = self.clock.get_time()
        prev_slot_t = self.clock.prev_contact_slot()
        base = self.contact

        # Read my unified signal: collect all peers involved with me within window (both directions)
        peers: List[str] = []
        my_signal = self.contact / "sig.jsonl"
        if my_signal.exists():
            # Default window: last 2 weeks
            weeks_window = 2  # if t.slot == 1 else 1
            rows = self._read_jsonl(my_signal, max_weeks=weeks_window)
            for obj in rows:
                # Direct access without fallback per coding standards
                frm = str(obj["from"]).strip()
                to = str(obj["to"]).strip()

                if frm == self.char:
                    if to and to not in peers:
                        peers.append(to)
                else:
                    assert to == self.char
                    if frm and frm not in peers:
                        peers.append(frm)

        # Under concurrency, write order within a slot in sig.jsonl is non-deterministic.
        # Use dict.fromkeys to deduplicate while preserving insertion order, then sorted for determinism.
        if peers:
            peers = sorted(dict.fromkeys(peers))
        else:
            return self.NO_CONTACT_MSG

        MAX_LEN = 800
        if config["world"].get("language") in ["zh", "cn"]:
            MAX_LEN = MAX_LEN // 4

        # Build per-sender recent contact history
        n_weeks = int(config["world"]["contact"]["n_prev_week_contact_history"])
        lines: List[str] = [
            "Here are your recent contact messages, along with your key insights about these persons. You can use function calls (such as read_scratchpad) to recall further details"
        ]
        for who in peers:
            conv_file = base / f"{who}.jsonl"
            rows = self._read_jsonl(conv_file, max_weeks=n_weeks)
            rows = self._sort_contact_rows(rows)
            lines.append(f"- With {who}:")
            # Append scratchpad recent summary and hint

            sp = self.character_scratchpads / f"{who}.jsonl"
            i_know_them = sp.exists() and self._created_before_cur_t(sp)
            summary_txt = ""

            if i_know_them:
                s_rows = self._read_jsonl(sp, max_lines=1)
                if s_rows:
                    last = s_rows[-1]
                    if isinstance(last, dict):
                        s_val = last.get("summary", "")
                        if isinstance(s_val, str) and s_val.strip():
                            summary_txt = s_val.strip()
                        else:
                            ERROR_LOGGER.error(
                                f"ERROR: found no summary for {sp} with row {last}"
                            )
                            c_val = last.get("content", "")
                            if isinstance(c_val, str) and c_val.strip():
                                content = c_val.strip()
                                summary_txt = clip_str(content, MAX_LEN)

            # pub_info internally checks is_mutually_known: returns full info if mutual, else appearance only
            pub_info = self.read_others_pub_info(who)

            about_lines = [f"{indent}(About {who}:"]
            if i_know_them and summary_txt:
                summary_indented = _indent_multiline(
                    clip_str(summary_txt, 200), double_indent
                )
                about_lines.append(
                    f"{double_indent}- summary of your scratchpad about {who}: {summary_indented}"
                )
            if pub_info:
                about_lines.append(f"{double_indent}- {pub_info}")
            if not i_know_them:
                about_lines.append(
                    f"{double_indent}- (System note: You don't know this person yet)"
                )
            about_lines.append(f"{indent})")
            lines.append("\n".join(about_lines))

            if not rows:
                # Per error-handling convention: functions read by LLM do not raise directly.
                # To force a raise, change to: raise RuntimeError(...).
                lines.append(
                    f"  - ERROR: missing conversation log for sender '{who}' at {prev_slot_t}"
                )
                ERROR_LOGGER.error(
                    f"  - ERROR: missing conversation log for sender '{who}' at {prev_slot_t}"
                )
                continue
            for r in rows:
                # Direct access without fallback per coding standards
                line_t = TimeState.from_string(str(r["time"]))
                frm = r["from"]
                content = str(r["content"]).strip()

                if line_t == prev_slot_t and frm != self.char:
        # Indent multi-line message bodies to match characters/others list formatting
                    content_indented = _indent_multiline(content, indent)
                    lines.append(
                        f"{indent}- [NEW!] [{line_t}] {frm}: {content_indented}"
                    )
                else:
                    # Clip extremely long message except for prev_slot_t
                    content = clip_str(content, MAX_LEN)
                    content_indented = _indent_multiline(content, indent)
                    lines.append(f"{indent}- [{line_t}] {frm}: {content_indented}")

        return "\n".join(lines)

    # ----------Schedule & Activity ----------
    def add_schedule(self, schedule: Schedule) -> None:
        """Append one created schedule to schedule.jsonl.

        Accepts either a Schedule object (preferred), or legacy named fields
        to construct a created Schedule. Only 'created' schedules are persisted.
        """

        if schedule.status != "created":
            raise ValueError("only created schedules are persisted")

        # Basic required fields for all schedule types
        if (
            not schedule.activity_id
            or not schedule.activity_name
            or not schedule.activity_time
        ):
            raise ValueError("add_schedule requires id/name/time")

        # Type-specific validation
        if schedule.type == "joint":
            # Joint activities require proposer
            if not schedule.proposer:
                raise ValueError("joint schedule requires proposer")
        # public and encounter types don't require proposer

        if len(schedule.participants) != len(set(schedule.participants)):
            raise ValueError("participants must be unique")

        t = self.clock.get_time()
        schedule_file = self.root / "schedule.jsonl"
        self._append_jsonl(schedule_file, schedule.to_dict())

    def get_future_schedules(self, include_current_time: bool = True) -> List[Schedule]:
        """Get future schedules within the scheduling window.

        Args:
            include_current_time: If True, include schedules at current time.
                                  If False, only include schedules strictly after current time.

        Returns:
            List of Schedule objects sorted by (activity_time, activity_name).
        """
        n_weeks = int(config["world"]["contact"]["max_weeks_for_future_schedule"])
        t = self.clock.get_time()

        schedule_file = self.root / "schedule.jsonl"
        rows = self._read_jsonl(
            schedule_file, max_weeks=n_weeks + 1
        )  # semantics differ: max_weeks=1 means current week only; +1 to include N future weeks

        # Compute upper bound (exclusive) for "next N weeks"
        n_week_per_year = int(config["world"]["time"]["n_week"])
        ub_year = t.year
        ub_week = t.week + n_weeks
        while ub_week > n_week_per_year:
            ub_week -= n_week_per_year
            ub_year += 1
        ub = TimeState(year=ub_year, week=ub_week, stage=Stage.BEGIN)

        # Convert to Schedule objects and filter future ones
        schedules = []
        for r in rows:
            sch = Schedule.from_dict(r)
            if sch.status != "created":
                continue
            at = sch.activity_time
            # Filter by time
            if include_current_time:
                if at >= t and at < ub:
                    schedules.append(sch)
            else:
                if at > t and at < ub:
                    schedules.append(sch)

        # Deduplicate by day: an agent can only do one activity per day.
        # Priority: joint > public > encounter. Within same type, last written wins.
        day_best: dict[tuple[int, int, int], Schedule] = {}
        for sch in schedules:
            at = sch.activity_time
            key = (at.year, at.week, at.day)
            prev = day_best.get(key)
            if prev is None:
                day_best[key] = sch
            else:
                prev_pri = self._SCHEDULE_TYPE_PRIORITY[prev.type]
                cur_pri = self._SCHEDULE_TYPE_PRIORITY[sch.type]
                if cur_pri >= prev_pri:
                    day_best[key] = sch

        result = list(day_best.values())
        # Sort by (activity_time, activity_name) for deterministic output (cache stability)
        result.sort(key=lambda s: (s.activity_time, s.activity_name))
        return result

    def list_schedule(self) -> str:
        """Format future schedules as a string for LLM prompt."""
        n_weeks = int(config["world"]["contact"]["max_weeks_for_future_schedule"])
        parts: List[str] = [f"## Your Schedule for the Next {n_weeks} Weeks"]

        schedules = self.get_future_schedules()

        for sch in schedules:
            if sch.type == "joint":
                # Joint activity: has proposer and actions
                proposer = sch.proposer
                proposer_action = sch.actions[proposer] if sch.actions else ""
                # participants order is deterministic from confirm_schedule(): [proposer] + sorted(others)
                parts.append(
                    f"- [Joint Activity] {sch.activity_name} at {sch.activity_time}; proposed by {proposer}; location: {sch.location}; "
                    f"participants: {', '.join(sch.participants)}; detailed proposal: {proposer_action}"
                )
            elif sch.type == "public":
                # Public activity: no proposer, has event_description
                parts.append(
                    f"- [Public Event] {sch.activity_name} at {sch.activity_time}; "
                    f"description: {sch.event_description}"
                )
            elif sch.type == "encounter":
                # Encounter: system-arranged meeting; not shown in list_schedule for the LLM.
                # Agent has no foreknowledge — learns about it only when it executes that day.
                continue
            else:
                # Unknown type, show basic info
                raise ValueError(f"Unknown activity type: {sch.type}")

        if len(parts) == 1:
            parts.append("There are no future schedules.")

        return "\n\n".join(parts)

    def get_busy_days_this_week(self) -> set[int]:
        """Return set of days (1-n) where agent has scheduled activities this week.

        Uses get_future_schedules() to correctly include cross-week schedules
        (e.g., joint activities created last week for this week).
        """
        t = self.clock.get_time()
        busy_days: set[int] = set()
        for sch in self.get_future_schedules():
            at = sch.activity_time
            if at.year == t.year and at.week == t.week and at.day > 0:
                busy_days.add(at.day)
        return busy_days

    def get_today_schedule(self) -> Schedule | None:
        """Return the unique Schedule for 'today' or None.

        - Uses _read_jsonl week-window reading (handles cross-year automatically).
        - Parses each row's activity_time as a TimeState and compares to today's t.
        - Asserts at most one activity per day (raises if multiple found).
        """
        t = self.clock.get_time()
        return self.get_schedule_for_day(t.year, t.week, t.day)

    # Priority: joint > public > encounter (higher number wins)
    _SCHEDULE_TYPE_PRIORITY = {"encounter": 0, "public": 1, "joint": 2}

    def get_schedule_for_day(self, year: int, week: int, day: int) -> Schedule | None:
        """Return the highest-priority Schedule for a specific day or None.

        When multiple schedules exist for the same day, priority is
        determined by type: joint > public > encounter.
        Within the same type, the last-written entry wins.
        """
        n_weeks = int(config["world"]["contact"]["max_weeks_for_future_schedule"])
        schedule_file = self.root / "schedule.jsonl"
        # exclude_cur_t=False: schedules written in current stage must be visible
        # (e.g., joint schedules written in AFTER_CONTACT must be readable by
        # _generate_encounter_events() in the same stage)
        rows = self._read_jsonl(
            schedule_file, max_weeks=n_weeks + 1, exclude_cur_t=False
        )

        filtered: List[Schedule] = []
        for r in rows:
            sch = Schedule.from_dict(r)
            if sch.status != "created":
                continue
            at = sch.activity_time
            if at.year == year and at.week == week and at.day == day:
                filtered.append(sch)

        if not filtered:
            return None
        # Pick by type priority (highest wins); within same type, last written wins
        return max(
            filtered,
            key=lambda s: (self._SCHEDULE_TYPE_PRIORITY[s.type], filtered.index(s)),
        )

    # ---------- Diary / History / Contact ----------
    def append_weekly_summary(self, content: str | Dict) -> None:
        """Append weekly summary to weekly_diary.jsonl.

        Args:
            content: Either a string (will be wrapped as {"content": str})
                    or a dict (will be used directly).
        """
        if isinstance(content, str):
            data = {"content": content}
        else:
            data = content
        self._append_jsonl(self.weekly_diary, data)

    def read_weekly_summaries(self, n_weeks: int = 4) -> List[Dict]:
        """Read recent weekly summaries.

        Returns list of dicts with 'time' and 'content' keys.
        """
        if not self.weekly_diary.exists():
            return []
        return self._read_jsonl(
            self.weekly_diary, max_weeks=n_weeks + 1
        )  # max_weeks includes the current week; to get the previous n weeks, pass n+1

    # ---------- Generation ----------
    def save_generation(
        self, inputs: List[Dict], outputs: List[Dict], filename: str | None = None
    ) -> None:
        t = self.clock.get_time()

        # Use provided filename or default to week=X format
        base_name = filename if filename else self._format_week(t.week)

        # Count input/output tokens (content may be None, e.g. tool_calls messages)
        input_tokens = sum(
            num_tokens_from_string(m.get("content") or "") for m in inputs
        )
        output_tokens = sum(
            num_tokens_from_string(m.get("content") or "") for m in outputs
        )

        record = {
            "time": str(t),
            "inputs": inputs,
            "outputs": outputs,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        jsonl_path = self.generation / (
            self._format_year(t.year) + "/" + base_name + ".jsonl"
        )
        md_path = self.generation / (
            self._format_year(t.year) + "/" + base_name + ".md"
        )

        # 1) Append to jsonl (original behavior)
        self._append_jsonl(jsonl_path, record)

        # 2) Append human-readable Markdown for visualization / collapsing
        try:
            with md_path.open("a", encoding="utf-8") as f:
                print_inputs = (
                    True  # all(msg['role'] in ['user', 'system'] for msg in inputs)
                )

                if print_inputs:
                    # Markdown heading with current simulation time (collapsible in editors)
                    f.write(f"# ==== llm inputs at ({t}) ====\n")
                    for idx, msg in enumerate(inputs):
                        content = msg["content"]
                        if msg["role"] == "assistant":
                            f.write(f"[output message {idx}]\n{content}\n")
                        else:
                            f.write(f"[input message {idx}]\n{content}\n")

                # Markdown heading with current simulation time (collapsible in editors)
                f.write(f"# ==== llm outputs at ({t}) ====\n")
                for idx, msg in enumerate(outputs):
                    # No tool_calls (or empty list): treat as a plain message and print content
                    if not msg.get("tool_calls"):
                        content = msg["content"]
                        f.write(f"[output message {idx}]\n{content}\n")
                    else:
                        # Has tool_calls: print each tool_call's full JSON in order
                        for it, tc in enumerate(msg["tool_calls"]):
                            f.write(f"[tool call {idx}-{it}]:\n")
                            f.write(json.dumps(tc, ensure_ascii=False, indent=2))
                            f.write("\n")
                f.write("\n---\n\n")
        except Exception as e:
            # Writing txt should not affect the main flow; log errors but do not raise
            ERROR_LOGGER.error("failed to write generation markdown: %s", e)

    def mark_generation_rejected(self, reason: str) -> None:
        """Mark the last record in the current week's generation JSONL as rejected.

        Modifies the last line in-place by adding {"rejected": true, "reason": ...}.
        """
        t = self.clock.get_time()
        jsonl_path = self.generation / (
            self._format_year(t.year) + "/" + self._format_week(t.week) + ".jsonl"
        )
        if not jsonl_path.exists():
            ERROR_LOGGER.warning(
                f"[{self.char}] mark_generation_rejected: {jsonl_path} not found"
            )
            return

        with jsonl_path.open("r+b") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                # Find start of last line (byte-level seek for UTF-8 safety)
                f.seek(0, 2)
                pos = f.tell()
                if pos == 0:
                    return
                # Step back past all trailing newlines
                pos -= 1
                while pos > 0:
                    f.seek(pos)
                    if f.read(1) != b"\n":
                        break
                    pos -= 1
                # Now pos is at last non-newline byte (or 0); find line start
                while pos > 0:
                    f.seek(pos)
                    if f.read(1) == b"\n":
                        break
                    pos -= 1
                last_line_start = pos + 1 if pos > 0 else 0
                f.seek(last_line_start)
                last_line = f.readline().decode("utf-8")
                record = json.loads(last_line)
                record["rejected"] = True
                record["reject_reason"] = reason
                # Truncate and rewrite
                f.seek(last_line_start)
                f.truncate()
                f.write(json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    # ---------- Activity Outcome Support ----------
    def apply_activity_outcome(
        self,
        outcome,  # ActionOutcome or JointActivityOutcome
        possessions: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Apply activity outcome deltas to vitality/fulfillment/skills/assets.

        Unified method for both Solo and Joint activities.

        Args:
            outcome: ActionOutcome (Solo) or JointActivityOutcome (Joint)
            possessions: Optional possessions list from gift transfers (Joint only).
                        If provided, replaces current possessions.
                        If None and outcome has gain_items, extends possessions.

        Returns:
            The applied state dict (for verification).
        """
        current = self.read_state(exclude_cur_t=False)

        # Possessions: Joint uses parameter (replace), Solo uses gain_items (extend)
        if possessions is not None:
            current["assets"]["possessions"] = possessions
        elif hasattr(outcome, "gain_items") and outcome.gain_items:
            current["assets"]["possessions"].extend(outcome.gain_items)

        # Vitality
        current["vitality"] = max(
            0, min(100, current["vitality"] + outcome.delta_vitality)
        )

        # Fulfillment
        for key, delta in outcome.delta_fulfillment.items():
            if key in current["fulfillment"]:
                current["fulfillment"][key] = max(
                    0, min(100, current["fulfillment"][key] + delta)
                )

        # Skills
        for skill, delta in outcome.delta_skills.items():
            current["skills"][skill] = max(0, current["skills"].get(skill, 0) + delta)

        # Money (Solo only)
        if hasattr(outcome, "delta_money"):
            current["assets"]["deposit"] = max(
                0, current["assets"]["deposit"] + outcome.delta_money
            )

        self.save_state(current)
        return current

    def append_activity_record(self, record: "SoloActivityRecord") -> None:
        """Append solo activity record to activity.jsonl."""
        from src.world.solo_activity_data import SoloActivityRecord

        path = self.root / "activity.jsonl"
        self._append_jsonl(path, record.to_dict())

    def append_joint_activity_record(self, record: "JointActivityRecord") -> None:
        """Append joint activity record to activity.jsonl.

        Joint activities now include deltas for vitality/fulfillment/skills/items.
        """
        from src.world.joint_activity_data import JointActivityRecord

        path = self.root / "activity.jsonl"
        self._append_jsonl(path, record.to_dict())

    def append_public_activity_record(self, record: "PublicActivityRecord") -> None:
        """Append public activity record to activity.jsonl."""
        from src.world.public_activity_data import PublicActivityRecord

        path = self.root / "activity.jsonl"
        self._append_jsonl(path, record.to_dict())

    def read_recent_activities(self, max_weeks: int = 4) -> str:
        """Read recent activity records and format as prompt string.

        Returns formatted prompt text for LLM consumption.
        """
        path = self.root / "activity.jsonl"
        if not path.exists():
            return ""

        rows = self._read_jsonl(path, max_weeks=max_weeks)
        if not rows:
            return ""

        lines = ["## Recent Activities"]
        for row in rows:
            time_str = row["time"]
            activity_type = row["type"]

            if activity_type == "joint":
                activity_name = row["activity_name"]
                summary = clip_str(row["summary"])
                reflection = clip_str(row["reflection"])
                lines.append(f"- [{time_str}] Joint: {activity_name}")
                lines.append(f"  Summary: {summary}")
                lines.append(f"  Reflection: {reflection}")
            elif activity_type == "solo":
                content = clip_str(row["content"])
                outcome_text = clip_str(row["outcome"]["outcome"])
                reflection = clip_str(row["reflection"])
                lines.append(f"- [{time_str}] Solo: {content}")
                lines.append(f"  Outcome: {outcome_text}")
                if reflection:
                    lines.append(f"  Reflection: {reflection}")
            elif activity_type == "public":
                activity_name = row["activity_name"]
                participation = clip_str(row["participation"], max_len=200)
                reflection = clip_str(row["reflection"], max_len=200)
                lines.append(f"- [{time_str}] Public: {activity_name}")
                if participation:
                    lines.append(f"  Participation: {participation}")
                if reflection:
                    lines.append(f"  Reflection: {reflection}")
            elif activity_type == "encounter":
                # Encounter is displayed in recent activities (shown after the fact)
                # but NOT in list_schedule (not shown in advance)
                activity_name = row["activity_name"]
                summary = clip_str(row["summary"])
                reflection = clip_str(row["reflection"])
                lines.append(f"- [{time_str}] Encounter: {activity_name}")
                lines.append(f"  Summary: {summary}")
                if reflection:
                    lines.append(f"  Reflection: {reflection}")
            else:
                raise ValueError(
                    f"Unknown activity type '{activity_type}' at {time_str}"
                )

        return "\n".join(lines)

    # =========================================================================
    # Reward Data
    # =========================================================================

    def save_reward(
        self,
        ranking: Optional["SocialRanking"],
        social: "SocialReward",
        subjective: "SubjectiveReward",
        total: "TotalReward",
    ) -> None:
        """Save reward data for this agent.

        File: persona/{name}/reward.jsonl

        Args:
            ranking: SocialRanking from judge_others() (can be None if no known people)
            social: SocialReward from PageRank calculation
            subjective: SubjectiveReward from fulfillment history
            total: TotalReward combining social and subjective
        """
        record = {
            # time is auto-injected by _append_jsonl
            "ranking": {
                "affection_scores": ranking.affection_scores if ranking else {},
                "respect_scores": ranking.respect_scores if ranking else {},
            },
            "social": {
                # Raw PageRank scores (for debugging/analysis)
                "affection_score": social.affection_score,
                "respect_score": social.respect_score,
                "combined_score": social.combined_score,
            },
            "subjective": {
                "score": subjective.score,
                "n_penalties": subjective.n_penalties,
            },
            "economy": {
                "score": total.economy_score,
            },
            "total_score": total.total_score,
        }

        path = self.root / "reward.jsonl"
        self._append_jsonl(path, record)

    def save_achievement(self, score: float, raw_score: int) -> None:
        """Save achievement score from position application.

        File: persona/{name}/achievement.jsonl
        Note: time is auto-injected by _append_jsonl
        """
        record = {"score": score, "raw_score": raw_score}
        path = self.root / "achievement.jsonl"
        self._append_jsonl(path, record)

    def read_latest_achievement(self) -> Optional[float]:
        """Read the most recent achievement raw score.

        Returns:
            Latest raw_score (sum_min_skills), or None if no records exist
        """
        path = self.root / "achievement.jsonl"
        if not path.exists():
            return None

        records = self._read_jsonl(path, max_lines=1, exclude_cur_t=False)
        if not records:
            return None

        return float(records[-1]["raw_score"])
