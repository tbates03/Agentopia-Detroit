from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, TYPE_CHECKING

from src.config import get_config
from src.utils import (
    get_response_with_retry,
    num_tokens_from_string,
    get_logger,
    get_verify_logger,
    clip_str,
)

if TYPE_CHECKING:
    from src.world.clock import Clock
    from src.world.position_application import Position
    from src.agents.role_agent import RoleAgent

# Module-level variables, initialized by World
_god_clock: "Clock | None" = None
_god_data_dir: str | None = None
_write_lock = threading.Lock()


def init_god_module(clock: "Clock", data_dir: str) -> None:
    """Initialize the God module (called by World at startup)."""
    global _god_clock, _god_data_dir
    _god_clock = clock
    _god_data_dir = data_dir


def save_generation(
    feature: str,
    inputs: List[Dict[str, Any]],
    outputs: List[Dict[str, Any]],
) -> None:
    """Save God Model generation data to two locations.

    1. SFT training data: data/{world_run_id}/god/{feature}/year={YYYY}/week={W}.jsonl
    2. Verification log: logs/verify/{world_run_id}/generations/{feature}.jsonl
    """
    if _god_clock is None or _god_data_dir is None:
        get_logger("error").warning(
            "God module not initialized, skipping save_generation"
        )
        return

    t = _god_clock.get_time()

    # Count tokens
    input_tokens = sum(num_tokens_from_string(m.get("content", "")) for m in inputs)
    output_tokens = sum(num_tokens_from_string(m.get("content", "")) for m in outputs)

    # SFT format (complete inputs/outputs)
    sft_record = {
        "time": str(t),
        "inputs": inputs,
        "outputs": outputs,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }

    # Verification log format (compatible with save_feature_generation)
    from datetime import datetime

    verify_record = {
        "timestamp": datetime.now().isoformat(),
        "messages": inputs,
        "output": outputs[0]["content"] if outputs else "",
    }

    # Build paths
    sft_path = (
        Path("data")
        / _god_data_dir
        / "god"
        / feature
        / f"year={t.year}"
        / f"week={t.week}.jsonl"
    )
    verify_path = (
        Path("logs/verify") / _god_data_dir / "generations" / f"{feature}.jsonl"
    )

    # Use a lock to protect file writes (concurrency-safe)
    with _write_lock:
        # Write SFT data
        sft_path.parent.mkdir(parents=True, exist_ok=True)
        with sft_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sft_record, ensure_ascii=False) + "\n")

        # Write verification log
        verify_path.parent.mkdir(parents=True, exist_ok=True)
        with verify_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(verify_record, ensure_ascii=False) + "\n")


def _pp_parse_env_nsp(resp: object, **kwargs) -> Optional[Dict[str, str]]:
    """Post-processor for ENV_PROMPT_JOINT_ACTIVITY outputs.

    Expect a plain text string with two sections:
    - Environment: <text>
    - Next Speaker: <name or <END CHAT>>

    Validates next speaker against the provided participants (case-insensitive),
    and returns a normalized dict: {"environment": str, "next_speaker": str}.
    Return None to signal retry.
    """
    if not isinstance(resp, str) or not resp.strip():
        return None

    participants: List[str] = kwargs["participants"]

    s = resp.strip()
    m = re.search(
        r"Environment\s*:\s*(.*?)\n\s*Next\s*Speaker\s*:\s*([^\n]+)",
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        env_fdbk = m.group(1).strip()
        nxt_raw = m.group(2).strip()
    else:
        # Fallback: scan lines
        lines = s.replace("\r\n", "\n").splitlines()
        env_lines: List[str] = []
        nxt_raw: Optional[str] = None
        mode = None
        for ln in lines:
            low = ln.lower()
            if low.startswith("next speaker:"):
                nxt_raw = ln.split(":", 1)[1].strip()
                mode = None
                continue
            if low.startswith("environment:"):
                env_lines.append(ln.split(":", 1)[1].strip())
                mode = "env"
                continue
            if mode == "env":
                env_lines.append(ln.strip())
        env_fdbk = " ".join([x for x in env_lines if x]).strip()
        nxt_raw = (nxt_raw or "").strip()

    # Basic format checks
    if not env_fdbk:
        return None
    if not nxt_raw:
        return None

    # Normalize next speaker
    nxt_norm = nxt_raw.strip()
    if nxt_norm.lower() in {"<end chat>", "<end>", "end", "stop"}:
        nxt_norm = "<END CHAT>"
    else:
        # Case-insensitive match to participants; return canonical form
        cand = {p.lower(): p for p in participants}
        nxt_norm = cand.get(nxt_norm.lower(), "")

    # Validate
    if not (nxt_norm == "<END CHAT>" or nxt_norm in participants):
        from src.utils import get_logger

        ERROR_LOGGER = get_logger("error")
        ERROR_LOGGER.warning(
            f"Next Speaker invalid in _pp_parse_env_nsp, raw response: {resp}; participants: {participants}"
        )
        if kwargs["nth_generation"] < kwargs.get("max_retry", 3):
            return None

    # Parse optional Verification line
    verification = "PASS"
    veri_match = re.search(
        r"^Verification\s*:\s*(.+)",
        s,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if veri_match:
        veri_raw = veri_match.group(1).strip()
        if veri_raw.upper().startswith("REJECT"):
            verification = veri_raw  # e.g. "REJECT: reason..."
        # else: PASS (default)

    return {
        "env_fdbk": env_fdbk,
        "speaker": nxt_norm,
        "response": s,
        "verification": verification,
    }


def env_and_nsp(
    messages: List[Dict[str, str]],
    participants: List[str],
    *,
    max_retry: int = 3,
    last_speaker: Optional[str] = None,
    allow_end: bool = True,
) -> Tuple[str, str, str, str]:
    """Wrap LLM call to produce (raw_text, environment, next_speaker, verification).

    - `messages` is a multi-turn list of {from, content}. Only keys used:
      - from: one of system|assistant|user (others treated as user)
      - content: plain text
    - Next speaker is validated against participants; invalid → random participant (excluding last_speaker).
    - END_SIGN constant from prompts is respected.
    - If LLM output is invalid after retries, returns empty response/env_fdbk and random speaker.
    - If allow_end=False, END_SIGN will be treated as invalid and trigger random selection.
    - verification: "PASS" or "REJECT: <reason>". Defaults to "PASS" on parse failure.
    """
    from src.agents.prompts import END_SIGN  # local import to avoid cycles
    import random

    # Map to Chat messages
    model = get_config()["god_model"]
    out = get_response_with_retry(
        post_processing_funcs=[_pp_parse_env_nsp],
        model=model,
        messages=messages,
        max_retry=max_retry,
        participants=participants,
    )

    if not isinstance(out, dict) or "env_fdbk" not in out or "speaker" not in out:
        # Fallback: set empty response/env_fdbk and mark speaker as invalid
        response = ""
        env_fdbk = ""
        speaker = None
        verification = "PASS"
    else:
        response = out["response"]
        env_fdbk = out["env_fdbk"]
        speaker = out["speaker"]
        verification = out.get("verification", "PASS")

    # Save LLM generation for SFT training
    save_generation(
        feature="joint_activity",
        inputs=messages,
        outputs=[{"role": "assistant", "content": response}],
    )

    # Unified logic: if speaker is invalid, randomly select from participants (excluding last_speaker)
    # Also treat END_SIGN as invalid when allow_end=False
    need_random = (speaker is None or speaker not in participants) or (
        speaker == END_SIGN and not allow_end
    )

    if need_random:
        available = [p for p in participants if p != last_speaker]
        if not available:
            available = list(participants)
        # Sort available list for deterministic random choice with same seed
        available = sorted(available)
        # Use hashlib for deterministic seed (Python's hash() is randomized per-run)
        payload = response if response else str(messages)
        h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        rng = random.Random(int(h, 16))
        speaker = rng.choice(available)

    return response, env_fdbk, speaker, verification


def split_response_by_visible_blocks(
    resp: str,
) -> List[Tuple[str, str, Optional[List[str]]]]:
    """Split response into blocks with explicit type for broadcasting logic.

    Output tuples: (blk_type, content, visible_group)
    - blk_type == "public": visible to all; visible_group is None
    - blk_type == "group": visible to specific names; visible_group: List[str]
    - blk_type == "private": speaker-only; visible_group is None

    Supported tags (case-insensitive):
    - <visible to="A,B"> ... </visible>
    - <visible_to="A,B"> ... </visible_to>
    - <visible_to=A, B> ... </visible_to>
    - <visible_to=[A,B]> ... </visible_to>
    - <visible_to=["A","B"]> ... </visible_to>
    - <visible_to="[A,B]"> ... </visible_to>
    """
    import re

    def _parse_visible_to(attr: str, tag: str) -> List[str]:
        """Extract a list of names from attribute string for visible(_to) tags.

        Accepts: to=..., visible_to=..., or for tag 'visible_to' the shorthand
        form where the tag carries the value directly: <visible_to=...> or
        <visible_to"...">.
        """
        s = attr.strip()
        # Try explicit key assignments first
        m = re.search(r"(?i)\b(?:to|visible_to)\s*=\s*\"([^\"]*)\"", s)
        if not m:
            m = re.search(r"(?i)\b(?:to|visible_to)\s*=\s*'([^']*)'", s)
        if not m:
            m = re.search(r"(?i)\b(?:to|visible_to)\s*=\s*(\[[^\]]*\])", s)
        if not m:
            # Greedy until end (handles unquoted with spaces/commas)
            m = re.search(r"(?i)\b(?:to|visible_to)\s*=\s*([^\s].*)\Z", s)

        raw = None
        if m:
            raw = m.group(1).strip()
        else:
            # Shorthand: tag is visible_to and value attached directly
            if tag.lower() == "visible_to":
                # Accept leading '=' or ':'
                t = s.lstrip().lstrip("=:").strip()
                raw = t

        if raw is None:
            return []

        # If wrapped in quotes, strip once
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            raw = raw[1:-1].strip()

        # If it's a bracket list, normalize to comma-split
        if raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            # Remove optional quotes around each item, then split by comma
            parts = [
                p.strip().strip('"').strip("'") for p in inner.split(",") if p.strip()
            ]
            return [p for p in parts if p]

        # Otherwise split by comma directly
        parts = [p.strip().strip('"').strip("'") for p in raw.split(",") if p.strip()]
        return [p for p in parts if p]

    blocks: List[Tuple[str, str, Optional[List[str]]]] = []
    pattern = re.compile(
        r"(?is)"  # DOTALL + IGNORECASE
        # visible/visible_to with attributes and paired closing tag (either name)
        r"<\s*(visible|visible_to)\b([^>]*)>(.*?)</\s*(?:visible|visible_to)\s*>"
        r"|<\s*private\s*>(.*?)</\s*private\s*>"
    )
    pos = 0
    for m in pattern.finditer(resp):
        if m.start() > pos:
            pre = resp[pos : m.start()].strip()
            if pre:
                blocks.append(("public", pre, None))
        tag = m.group(1)
        attrs = m.group(2) if m.group(2) is not None else ""
        vis_content = m.group(3)
        prv_content = m.group(4)
        if tag is not None:
            content = (vis_content or "").strip()
            tos = _parse_visible_to(attrs, tag)
            blocks.append(("group", content, tos))
        else:
            content = (prv_content or "").strip()
            blocks.append(("private", content, None))
        pos = m.end()
    if pos < len(resp):
        rest = resp[pos:].strip()
        if rest:
            blocks.append(("public", rest, None))
    return blocks


def _validate_activity_type_response(response: str, **kwargs) -> dict:
    """Post-processing function for stage 1: validate activity type evaluation.

    Supports two formats:
    1. Consumption event: {is_consumption_event: true}
    2. Non-consumption: {outcome, is_consumption_event: false, delta_*...}

    Args:
        response: LLM output string
        **kwargs: Additional arguments (passed to extract_json)

    Returns:
        Parsed dict if valid, None to trigger retry
    """
    from src.utils import extract_json

    # First extract JSON from response
    data = extract_json(response, **kwargs)
    if not data or not isinstance(data, dict):
        return None

    # Default to non-consumption if key is missing
    is_consumption = data.get("is_consumption_event", False)

    try:
        if is_consumption:
            # For consumption events, only validate flag
            assert isinstance(is_consumption, bool)
            return data
        else:
            # For non-consumption events, validate outcome and all delta fields
            assert "outcome" in data and isinstance(data["outcome"], str)
            assert "delta_vitality" in data and isinstance(
                data["delta_vitality"], (int, float)
            )
            assert "delta_fulfillment" in data and isinstance(
                data["delta_fulfillment"], dict
            )
            assert "delta_skills" in data and isinstance(data["delta_skills"], dict)
            assert "delta_money" in data and isinstance(
                data["delta_money"], (int, float)
            )
            assert "gain_items" in data and isinstance(data["gain_items"], list)
            # Non-consumption events should not have gain_items
            assert data["gain_items"] == [], (
                "Non-consumption events should have empty gain_items"
            )
    except (AssertionError, TypeError, KeyError):
        return None

    return data


def _validate_consumption_offers_response(response: str, **kwargs) -> dict:
    """Post-processing function for stage 2: validate consumption offers.

    Expected format: {outcome: "...", consumption_options: [...]}

    Args:
        response: LLM output string
        **kwargs: Additional arguments (passed to extract_json)

    Returns:
        Parsed dict if valid, None to trigger retry
    """
    from src.utils import extract_json

    # First extract JSON from response
    data = extract_json(response, **kwargs)
    if not data or not isinstance(data, dict):
        return None

    # Validate outcome field
    if "outcome" not in data or not isinstance(data["outcome"], str):
        return None

    # Validate consumption_options field
    if "consumption_options" not in data:
        return None

    options = data["consumption_options"]
    if not isinstance(options, list):
        return None

    # Empty options is valid (items don't fit worldview)
    if len(options) == 0:
        return data

    # Validate each option has name, price, description
    try:
        for opt in options:
            assert isinstance(opt, dict)
            assert "name" in opt and isinstance(opt["name"], str)
            assert "price" in opt and isinstance(opt["price"], (int, float))
            assert "description" in opt and isinstance(opt["description"], str)
    except (AssertionError, TypeError, KeyError):
        return None

    return data


def evaluate_solo_activity(
    agent: "RoleAgent",
    activity_content: str,
) -> tuple[str | None, bool, dict | None]:
    """Stage 1: GodModel evaluates solo activity.

    For non-consumption activities: returns complete evaluation (outcome + deltas).
    For consumption activities: returns only flag, triggering stage 2 offer generation.

    Args:
        agent: RoleAgent instance
        activity_content: Extracted activity content (the "Activity:" section from agent's response)

    Returns:
        Tuple of (outcome_text_or_none, is_consumption_event, deltas_or_none)
        - If consumption: (None, True, None)
        - If non-consumption: (outcome, False, deltas_dict)
    """
    from src.agents.prompts import build_god_eval_solo_activity_prompt

    # Build GodModel prompt with activity content embedded
    prompt_template = build_god_eval_solo_activity_prompt()
    prompt = prompt_template.format(
        agent_name=agent.name,
        agent_info=agent.dm.character_prompt(),
        agent_activity=activity_content,
    )

    messages = [{"role": "system", "content": prompt}]

    data = get_response_with_retry(
        post_processing_funcs=[_validate_activity_type_response],
        model=get_config()["god_model"],
        messages=messages,
    )

    if not isinstance(data, dict):
        get_logger("error").warning(
            f"evaluate_solo_activity: LLM returned {data!r} "
            f"for {agent.name}, returning zero deltas"
        )
        return (
            None,
            False,
            {
                "delta_vitality": 0, "delta_fulfillment": {},
                "delta_skills": {}, "delta_money": 0, "gain_items": [],
            },
        )

    # Save LLM generation for SFT training
    save_generation(
        feature="solo_activity",
        inputs=messages,
        outputs=[
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
        ],
    )

    # Defensive fallback: post_processing_func should have ensured these exist
    is_consumption = data.get("is_consumption_event", False)

    if is_consumption:
        # Consumption event: return flag only, no outcome or deltas yet
        return None, True, None
    else:
        outcome_text = data.get("outcome", "")
        # Non-consumption event: return outcome + deltas
        delta_vitality = int(data.get("delta_vitality", 0))
        delta_fulfillment_raw = data.get("delta_fulfillment", {})
        delta_skills = data.get("delta_skills", {})
        delta_money = int(data.get("delta_money", 0))
        gain_items = data.get("gain_items", [])

        # Read delta limits from config and apply clipping
        config = get_config()
        limits = config["world"]["solo_activity"]["delta_limits"]

        # Apply clipping for vitality
        delta_vitality = max(
            limits["vitality"]["min"], min(limits["vitality"]["max"], delta_vitality)
        )

        # Solo activity constraints: only mood and esteem allowed
        delta_fulfillment = {}
        for key in ["mood", "esteem"]:
            if key in delta_fulfillment_raw and key in limits["fulfillment"]:
                key_limits = limits["fulfillment"][key]
                delta_fulfillment[key] = max(
                    key_limits["min"],
                    min(key_limits["max"], delta_fulfillment_raw[key]),
                )

        # Apply skills clipping
        for key in delta_skills:
            delta_skills[key] = max(
                limits["skills"]["min"], min(limits["skills"]["max"], delta_skills[key])
            )

        # Money clipping: non-consumption events can only earn money, not spend
        if delta_money > 0:
            delta_money = min(limits["money"]["max"], delta_money)
        elif delta_money < 0:
            ERROR_LOGGER = get_logger("error")
            ERROR_LOGGER.warning(
                f"Non-consumption event has negative delta_money: {delta_money}, forcing to 0"
            )
            delta_money = 0

        deltas = {
            "delta_vitality": delta_vitality,
            "delta_fulfillment": delta_fulfillment,
            "delta_skills": delta_skills,
            "delta_money": delta_money,
            "gain_items": gain_items,
        }

        return outcome_text, False, deltas


def generate_consumption_offers(
    agent: "RoleAgent",
    activity_content: str,
) -> tuple[str, list["ConsumptionOption"]]:
    """Stage 2: GodModel generates consumption scenario and offers.

    Args:
        agent: RoleAgent instance
        activity_content: Extracted activity content

    Returns:
        Tuple of (outcome_text, consumption_options)
        If items don't fit worldview, consumption_options will be empty list
    """
    from src.world.solo_activity_data import ConsumptionOption
    from src.agents.prompts import build_god_generate_offers_prompt, _load_price_data

    # Load worldview from worldview.json
    config = get_config()
    world_name = config["world"]["name"]
    price_data = _load_price_data(world_name)

    # Extract worldview as pure string
    worldview = price_data["worldview"]

    # Build GodModel prompt with activity content and worldview
    prompt_template = build_god_generate_offers_prompt()
    prompt = prompt_template.format(
        agent_name=agent.name,
        agent_info=agent.dm.character_prompt(),
        agent_activity=activity_content,
        worldview=worldview,
    )

    messages = [{"role": "system", "content": prompt}]

    data = get_response_with_retry(
        post_processing_funcs=[_validate_consumption_offers_response],
        model=get_config()["god_model"],
        messages=messages,
    )

    # Save LLM generation for SFT training
    save_generation(
        feature="solo_activity",
        inputs=messages,
        outputs=[
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
        ],
    )

    # Parse outcome and consumption options
    if not isinstance(data, dict):
        return "", []
    outcome_text = data["outcome"]
    options_data = data["consumption_options"]
    consumption_opts = [
        ConsumptionOption(
            name=opt["name"],
            price=int(opt["price"]),
            description=opt["description"],
        )
        for opt in options_data
    ]

    return outcome_text, consumption_opts


def _validate_joint_activity_response(response: str, **kwargs) -> dict:
    """Post-processing function for joint activity evaluation.

    Expected format: {agent_name: {delta_vitality, delta_fulfillment, delta_skills}, ...}

    Args:
        response: LLM output string
        **kwargs: Additional arguments (passed to extract_json)

    Returns:
        Parsed dict if valid, None to trigger retry
    """
    from src.utils import extract_json

    # First extract JSON from response
    data = extract_json(response, **kwargs)
    if not data:
        return None

    # Validate dict is non-empty
    if not isinstance(data, dict) or len(data) == 0:
        return None

    # Validate all expected agents are present
    expected_agents = kwargs.get("expected_agents", [])
    if expected_agents:
        missing = set(expected_agents) - set(data.keys())
        if missing:
            return None

    # Validate each outcome entry
    try:
        for agent_name, outcome in data.items():
            assert isinstance(agent_name, str)
            assert isinstance(outcome, dict)
            assert "delta_vitality" in outcome and isinstance(
                outcome["delta_vitality"], (int, float)
            )
            assert "delta_fulfillment" in outcome and isinstance(
                outcome["delta_fulfillment"], dict
            )
            assert "delta_skills" in outcome and isinstance(
                outcome["delta_skills"], dict
            )
    except (AssertionError, TypeError, KeyError):
        return None

    return data


def evaluate_joint_activity(
    agents: List["RoleAgent"],
    activity_background: str,
    dialog_history: str,
) -> Dict[str, "JointActivityOutcome"]:
    """Evaluate joint activity and return deltas for each participant.

    Args:
        agents: All participants
        activity_background: Activity context
        dialog_history: Full dialog transcript

    Returns:
        Dict mapping agent_name to JointActivityOutcome
    """
    from src.world.joint_activity_data import JointActivityOutcome
    from src.agents.prompts import build_god_eval_joint_activity_prompt

    # Build participants info block (condensed profile for evaluation)
    participants_info_lines = []
    for agent in agents:
        profile_info = agent.dm.get_profile_for_activity_eval()
        participants_info_lines.append(f"## {agent.name}\n\n{profile_info}")
    participants_info = "\n\n".join(participants_info_lines)

    # Build GodModel prompt
    prompt_template = build_god_eval_joint_activity_prompt()
    prompt = prompt_template.format(
        activity_background=activity_background,
        participants_info=participants_info,
        dialog_history=dialog_history,
    )

    messages = [{"role": "system", "content": prompt}]

    expected_agents = [agent.name for agent in agents]
    data = get_response_with_retry(
        post_processing_funcs=[_validate_joint_activity_response],
        model=get_config()["god_model"],
        messages=messages,
        expected_agents=expected_agents,
    )

    if not isinstance(data, dict):
        get_logger("error").warning(
            f"evaluate_joint_activity: LLM returned {data!r}, returning zero deltas"
        )
        return {
            agent.name: JointActivityOutcome(
                agent_name=agent.name, delta_vitality=0,
                delta_fulfillment={}, delta_skills={},
                items_sent=[], items_received=[],
            )
            for agent in agents
        }

    # Save LLM generation for SFT training
    save_generation(
        feature="joint_activity",
        inputs=messages,
        outputs=[
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
        ],
    )

    # Parse outcomes and apply delta limits from config
    config = get_config()
    limits = config["world"]["joint_activity"]["delta_limits"]

    outcomes = {}

    for agent_name, outcome_data in data.items():
        # Defensive fallback: post_processing_func should have ensured these exist
        delta_vitality = int(outcome_data.get("delta_vitality", 0))
        delta_vitality = max(
            limits["vitality"]["min"], min(limits["vitality"]["max"], delta_vitality)
        )

        # Apply clipping for fulfillment (mood, social, esteem)
        delta_fulfillment_raw = outcome_data.get("delta_fulfillment", {})
        delta_fulfillment = {}
        for key in ["mood", "social", "esteem"]:
            if key in delta_fulfillment_raw and key in limits["fulfillment"]:
                key_limits = limits["fulfillment"][key]
                delta_fulfillment[key] = max(
                    key_limits["min"],
                    min(key_limits["max"], delta_fulfillment_raw[key]),
                )

        # Apply clipping for skills
        delta_skills = outcome_data.get("delta_skills", {})
        for key in delta_skills:
            delta_skills[key] = max(
                limits["skills"]["min"], min(limits["skills"]["max"], delta_skills[key])
            )

        outcome = JointActivityOutcome(
            agent_name=agent_name,
            delta_vitality=delta_vitality,
            delta_fulfillment=delta_fulfillment,
            delta_skills=delta_skills,
            items_sent=[],  # Filled later in activity.py from gift_actions (for recording only)
            items_received=[],  # Filled later in activity.py from gift_actions (for recording only)
        )
        outcomes[agent_name] = outcome

    return outcomes


def _validate_eval_public_activity_response(response: str, **kwargs) -> dict:
    """Post-processing function for public activity evaluation.

    Expected format: {agent_name: {delta_vitality, delta_fulfillment, delta_skills}, ...}

    Args:
        response: LLM output string
        **kwargs: Must include 'expected_agents' (list of agent names)

    Returns:
        Parsed dict if valid, None to trigger retry
    """
    from src.utils import extract_json

    expected_agents = kwargs.get("expected_agents", [])

    data = extract_json(response, **kwargs)
    if not data:
        return None

    if not isinstance(data, dict) or len(data) == 0:
        return None

    # Validate all expected agents are present
    if expected_agents:
        missing = set(expected_agents) - set(data.keys())
        if missing:
            return None

    # Validate each outcome entry
    try:
        for agent_name, outcome in data.items():
            assert isinstance(agent_name, str)
            assert isinstance(outcome, dict)
            assert "delta_vitality" in outcome and isinstance(
                outcome["delta_vitality"], (int, float)
            )
            assert "delta_fulfillment" in outcome and isinstance(
                outcome["delta_fulfillment"], dict
            )
            assert "delta_skills" in outcome and isinstance(
                outcome["delta_skills"], dict
            )
    except (AssertionError, TypeError, KeyError):
        return None

    return data


def evaluate_public_activity(
    agents: List["RoleAgent"],
    activity_name: str,
    event_description: str,
    participation_outputs: Dict[str, str],
) -> Dict[str, "PublicActivityOutcome"]:
    """Evaluate public activity and return deltas for each participant.

    Args:
        agents: All participants
        activity_name: Name of the public activity
        event_description: Description of the activity
        participation_outputs: Dict mapping agent_name to their participation description

    Returns:
        Dict mapping agent_name to PublicActivityOutcome
    """
    from src.world.public_activity_data import PublicActivityOutcome
    from src.agents.prompts import build_god_eval_public_activity_prompt

    # Build participants info block (condensed profile for evaluation)
    participants_info_lines = []
    for agent in agents:
        profile_info = agent.dm.get_profile_for_activity_eval()
        participants_info_lines.append(f"## {agent.name}\n\n{profile_info}")
    participants_info = "\n\n".join(participants_info_lines)

    # Build participation descriptions block
    participation_lines = []
    for agent in agents:
        desc = participation_outputs[agent.name]
        participation_lines.append(f"## {agent.name}\n\n{desc}")
    participation_descriptions = "\n\n".join(participation_lines)

    # Build GodModel prompt
    prompt_template = build_god_eval_public_activity_prompt()
    prompt = prompt_template.format(
        activity_name=activity_name,
        event_description=event_description,
        participants_info=participants_info,
        participation_descriptions=participation_descriptions,
    )

    messages = [{"role": "system", "content": prompt}]

    expected_agents = [agent.name for agent in agents]

    data = get_response_with_retry(
        post_processing_funcs=[_validate_eval_public_activity_response],
        model=get_config()["god_model"],
        messages=messages,
        expected_agents=expected_agents,
    )

    if not isinstance(data, dict):
        get_logger("error").warning(
            f"evaluate_public_activity: LLM returned {data!r} "
            f"for activity '{activity_name}', returning zero deltas"
        )
        return {
            agent.name: PublicActivityOutcome(
                outcome="", delta_vitality=0,
                delta_fulfillment={}, delta_skills={},
            )
            for agent in agents
        }

    # Save LLM generation
    save_generation(
        feature="public_activity",
        inputs=messages,
        outputs=[
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)}
        ],
    )

    # Parse outcomes and apply delta limits from config
    config = get_config()
    limits = config["world"]["public_activity"]["delta_limits"]

    outcomes = {}

    for agent_name, outcome_data in data.items():
        delta_vitality = int(outcome_data.get("delta_vitality", 0))
        delta_vitality = max(
            limits["vitality"]["min"], min(limits["vitality"]["max"], delta_vitality)
        )

        # Apply clipping for fulfillment (only keys defined in config are processed)
        delta_fulfillment_raw = outcome_data.get("delta_fulfillment", {})
        delta_fulfillment = {}
        for key in ["mood", "social", "esteem"]:
            if key in delta_fulfillment_raw and key in limits["fulfillment"]:
                key_limits = limits["fulfillment"][key]
                delta_fulfillment[key] = max(
                    key_limits["min"],
                    min(key_limits["max"], delta_fulfillment_raw[key]),
                )

        # Apply clipping for skills
        delta_skills = outcome_data.get("delta_skills", {})
        for key in delta_skills:
            delta_skills[key] = max(
                limits["skills"]["min"], min(limits["skills"]["max"], delta_skills[key])
            )

        outcome = PublicActivityOutcome(
            outcome="",  # Public activity doesn't have a separate outcome text
            delta_vitality=delta_vitality,
            delta_fulfillment=delta_fulfillment,
            delta_skills=delta_skills,
        )
        outcomes[agent_name] = outcome

    return outcomes


# =============================================================================
# Public Event Functions
# =============================================================================


def _pp_parse_public_events(resp: object, **kwargs) -> Optional[List[Dict]]:
    """Post-processor for generate_public_events outputs.

    Expects a JSON array of events.
    Returns None to signal retry.

    Required kwargs:
        n_days: int - number of days per week
        max_repeat_weeks: int - maximum repeat weeks allowed
        valid_agent_names: List[str] - list of valid agent names for filtering
        existing_event_names: Set[str] - existing event names to avoid duplicates
    """
    import json
    import re

    if not isinstance(resp, str) or not resp.strip():
        return None

    s = resp.strip()

    # Try to extract JSON array (greedy to capture nested arrays like eligible_participants)
    m = re.search(r"\[[\s\S]*\]", s)
    if not m:
        return None

    try:
        events = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None

    if not isinstance(events, list):
        return None

    # Required kwargs - no fallback
    n_days = kwargs["n_days"]
    max_repeat_weeks = kwargs["max_repeat_weeks"]
    valid_agent_names = set(kwargs["valid_agent_names"])
    existing_event_names = kwargs["existing_event_names"]

    # Validate each event
    valid_events = []
    seen_names: set[str] = set()  # Track names within this batch to avoid duplicates
    for evt in events:
        if not isinstance(evt, dict):
            continue
        # Required fields with type check
        event_name = evt.get("event_name")
        start_day = evt.get("start_day")
        description = evt.get("description")
        if not isinstance(event_name, str) or not event_name.strip():
            continue
        if not isinstance(description, str) or not description.strip():
            continue
        if not isinstance(start_day, int) or start_day < 1 or start_day > n_days:
            continue
        # Check for duplicate names (case-insensitive, whitespace-normalized)
        normalized_name = event_name.strip().lower()
        if normalized_name in existing_event_names or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        # repeat_weeks: default 1, cap at max_repeat_weeks
        repeat_weeks = evt.get("repeat_weeks", 1)
        if not isinstance(repeat_weeks, int) or repeat_weeks < 1:
            repeat_weeks = 1
        elif repeat_weeks > max_repeat_weeks:
            repeat_weeks = max_repeat_weeks
        evt["repeat_weeks"] = repeat_weeks
        # eligible_participants: "all" or list of valid names
        eligible = evt.get("eligible_participants", "all")
        if eligible == "all":
            pass  # keep as "all"
        elif isinstance(eligible, list):
            # Filter to only valid agent names
            eligible = [name for name in eligible if name in valid_agent_names]
        else:
            eligible = "all"
        evt["eligible_participants"] = eligible
        valid_events.append(evt)

    if not valid_events:
        return None

    return valid_events


def generate_public_events(
    agent_summaries: str,
    previous_events: str,
    n_days: int,
    year: int,
    week: int,
    valid_agent_names: List[str],
    existing_event_names: set[str],
) -> List["PublicEvent"]:
    """God Model generates this week's public events.

    Args:
        agent_summaries: Brief information about all roles.
        previous_events: Events created in the past N weeks (N is controlled by config).
        n_days: Number of days in this week (read from config).
        year: Current year.
        week: Current week number.
        valid_agent_names: List of all valid role names (used to filter eligible_participants).
        existing_event_names: Set of existing event names (used to avoid duplicate names).

    Returns:
        List[PublicEvent] of this week's public events.
    """
    from src.agents.prompts import build_god_generate_public_events_prompt
    from src.world.scheduling import PublicEvent
    from src.utils import get_verify_logger

    verify_logger = get_verify_logger(feature="public_activity")
    current_time = f"Y{year}-W{week:02d}"

    config = get_config()
    public_cfg = config["world"]["public_activity"]
    max_events = public_cfg["max_events_per_week"]
    min_events = max(1, max_events // 2)  # Ensure at least 1

    from src.agents.prompts import get_world_setting

    world_name = config["world"]["name"]
    prompt = build_god_generate_public_events_prompt(
        agent_summaries=agent_summaries,
        previous_events=previous_events,
        current_time=current_time,
        n_days=n_days,
        previous_events_weeks=public_cfg["previous_events_weeks"],
        min_events=min_events,
        max_events=max_events,
        max_repeat_weeks=public_cfg["max_repeat_weeks"],
        world_setting=get_world_setting(world_name),
    )

    messages = [{"role": "system", "content": prompt}]

    events_data = get_response_with_retry(
        post_processing_funcs=[_pp_parse_public_events],
        model=config["god_model"],
        messages=messages,
        n_days=n_days,
        max_repeat_weeks=public_cfg["max_repeat_weeks"],
        valid_agent_names=valid_agent_names,
        existing_event_names=existing_event_names,
    )

    # Save generation for SFT training
    save_generation(
        feature="public_activity",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(events_data, ensure_ascii=False),
            }
        ],
    )

    if events_data is None:
        if verify_logger:
            verify_logger.warning(
                f"[VERIFY-PUBLIC] God Model failed to generate events for {current_time}"
            )
        return []

    # AGENTOPIA_V17451_HF1_PUBLIC_EVENT_NORMALIZER
    # Model/post-processing output is not guaranteed to remain a bare
    # list[dict]. Normalize envelopes / JSON strings and fail forward
    # rather than allowing one malformed public event to kill the world.
    def _public_event_warn(message):
        if verify_logger:
            try:
                verify_logger.warning(
                    f"[VERIFY-PUBLIC][NORMALIZE] {current_time}: {message}"
                )
            except Exception:
                pass

    raw_events = events_data

    # Unwrap up to a few common model/parser representations.
    for _ in range(4):
        if isinstance(raw_events, str):
            try:
                raw_events = json.loads(raw_events)
                continue
            except Exception as exc:
                _public_event_warn(
                    f"unable to decode event container string: {type(exc).__name__}"
                )
                raw_events = []
                break

        if isinstance(raw_events, dict):
            required = {
                "event_name",
                "start_day",
                "repeat_weeks",
                "description",
                "eligible_participants",
            }

            # A single event dictionary.
            if required.issubset(raw_events.keys()):
                raw_events = [raw_events]
                break

            # Common response envelopes.
            unwrapped = False
            for key in ("events", "public_events", "items", "data", "results"):
                if key in raw_events:
                    raw_events = raw_events[key]
                    unwrapped = True
                    break

            if unwrapped:
                continue

            # Some models return {"1": {...}, "2": {...}}.
            vals = list(raw_events.values())
            if vals and all(isinstance(v, dict) for v in vals):
                raw_events = vals
                break

            _public_event_warn(
                f"unsupported event mapping keys={list(raw_events.keys())[:8]}"
            )
            raw_events = []
            break

        break

    if not isinstance(raw_events, (list, tuple)):
        _public_event_warn(
            f"unsupported event container type={type(raw_events).__name__}"
        )
        raw_events = []

    public_events = []
    required_fields = (
        "event_name",
        "start_day",
        "repeat_weeks",
        "description",
        "eligible_participants",
    )

    for raw_evt in raw_events:
        evt = raw_evt

        if isinstance(evt, str):
            try:
                evt = json.loads(evt)
            except Exception as exc:
                _public_event_warn(
                    f"skipping undecodable event string: {type(exc).__name__}"
                )
                continue

        if not isinstance(evt, dict):
            _public_event_warn(
                f"skipping event type={type(evt).__name__}"
            )
            continue

        missing = [k for k in required_fields if k not in evt]
        if missing:
            _public_event_warn(
                f"skipping malformed event missing={','.join(missing)}"
            )
            continue

        try:
            i = len(public_events)
            event_id = f"public-{year}-W{week:02d}-{i + 1}"

            public_event = PublicEvent(
                event_id=event_id,
                event_name=evt["event_name"],
                start_year=year,
                start_week=week,
                start_day=evt["start_day"],
                repeat_weeks=evt["repeat_weeks"],
                description=evt["description"],
                eligible_participants=evt["eligible_participants"],
            )
            public_events.append(public_event)

        except Exception as exc:
            _public_event_warn(
                f"skipping invalid event during construction: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

    return public_events


# =============================================================================
#                         ENCOUNTER GENERATION
# =============================================================================


def _pp_parse_encounter_events(
    response: str,
    **kwargs,
) -> Optional[List[Dict]]:
    """Parse encounter events JSON from God Model response.

    Returns:
        List of dicts with participants (list), day, time, location, description.
        None on parse failure.

    Required kwargs:
        valid_agent_names: set of valid agent names
        idle_agents_by_day: dict mapping day (int) -> set of idle agent names
        valid_locations: set of valid location keys
        n_days: int, number of days per week
    """
    import json
    import re

    valid_agent_names: set = kwargs["valid_agent_names"]
    idle_agents_by_day: Dict[int, set] = kwargs["idle_agents_by_day"]
    valid_locations: set = kwargs["valid_locations"]
    n_days: int = kwargs["n_days"]

    # Try to extract JSON array from response
    json_match = re.search(r"\[[\s\S]*\]", response, re.DOTALL)
    if not json_match:
        try:
            data = json.loads(response.strip())
            if not isinstance(data, list):
                return None
        except json.JSONDecodeError:
            return None
    else:
        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

    # Validate structure: track used participants per day
    used_by_day: Dict[int, set] = {d: set() for d in range(1, n_days + 1)}
    valid_encounters = []

    for item in data:
        if not isinstance(item, dict):
            continue

        # Parse participants as list
        participants = item.get("participants", [])
        if not isinstance(participants, list) or len(participants) != 2:
            continue
        p1, p2 = [str(p).strip() for p in participants]

        # Parse day
        day = item.get("day")
        if not isinstance(day, int) or day < 1 or day > n_days:
            continue

        loc = str(item.get("location", "")).strip()
        desc = str(item.get("description", "")).strip()
        time_str = str(item.get("time", "")).strip()

        # Validate participants
        if not p1 or not p2 or p1 == p2:
            continue
        if p1 not in valid_agent_names or p2 not in valid_agent_names:
            continue

        # Check if participants are idle on that day
        idle_on_day = idle_agents_by_day.get(day, set())
        if p1 not in idle_on_day or p2 not in idle_on_day:
            continue

        # Check not already used on that day
        if p1 in used_by_day[day] or p2 in used_by_day[day]:
            continue

        # Validate location - must be in the provided list
        if loc not in valid_locations:
            continue

        # Validate description - must be non-empty
        if not desc:
            continue

        used_by_day[day].add(p1)
        used_by_day[day].add(p2)

        valid_encounters.append(
            {
                "participants": sorted([p1, p2]),  # Sorted for determinism
                "day": day,
                "time": time_str,
                "location": loc,
                "description": desc,
            }
        )

    return valid_encounters if valid_encounters else None


def god_generate_encounter_events(
    current_time: str,
    n_days: int,
    idle_agents_by_day: Dict[int, Dict[str, List[str]]],
    valid_locations: List[str],
    total_encounters: int,
    agents: List["RoleAgent"],
) -> List[Dict]:
    """Use God Model to generate encounter events for the whole week.

    Args:
        current_time: Current time string (Y{year}-W{week} format)
        n_days: Number of days per week
        idle_agents_by_day: Dict mapping day -> {agent_name: [related_names]}
        valid_locations: List of valid location keys from LocationStore
        total_encounters: Total number of encounters to generate for the week
        agents: List of all RoleAgent instances (for profile lookup)

    Returns:
        List of encounter dicts with participants (list), day, time, location, description
    """
    from src.agents.prompts import build_god_generate_encounter_events_prompt
    from src.utils import get_verify_logger

    verify_logger = get_verify_logger(feature="encounter_activity")

    config = get_config()

    # AGENTOPIA_ENCOUNTER_CONTEXT_BOUND_V180
    # Encounter generation used to place every idle citizen and every brief
    # profile into one God-model prompt. Bound and rotate that global context so
    # population growth does not become a context-window ceiling.
    growth = config.get("world", {}).get("growth", {})
    if not isinstance(growth, dict):
        growth = {}
    try:
        per_day_limit = int(
            os.environ.get(
                "AGENTOPIA_ENCOUNTER_CONTEXT_AGENT_LIMIT",
                str(growth.get("encounter_prompt_agents_per_day", 48)),
            )
        )
    except Exception:
        per_day_limit = 48
    per_day_limit = max(2, per_day_limit)

    bounded_idle: Dict[int, Dict[str, List[str]]] = {}
    for day, agents_info in idle_agents_by_day.items():
        names = sorted(
            agents_info.keys(),
            key=lambda name: hashlib.sha256(
                f"encounter-sample|{current_time}|D{day}|{name}".encode("utf-8")
            ).hexdigest(),
        )
        selected = names[:per_day_limit]
        bounded_idle[day] = {name: agents_info[name] for name in selected}
    idle_agents_by_day = bounded_idle

    max_possible = sum(len(v) // 2 for v in idle_agents_by_day.values())
    total_encounters = min(int(total_encounters), max_possible)
    if total_encounters <= 0:
        return []

    # Build name -> agent mapping for profile lookup
    name2agent = {agent.name: agent for agent in agents}

    # Collect all unique idle agent names across all days
    all_idle_names: set[str] = set()
    for agents_info in idle_agents_by_day.values():
        all_idle_names.update(agents_info.keys())

    # Sort by hash for deterministic but non-alphabetical order
    def _hash_key(name: str) -> str:
        return hashlib.sha256(f"encounter-{current_time}-{name}".encode()).hexdigest()

    # Build agent profiles section (sorted by hash for determinism)
    profile_lines = []
    for agent_name in sorted(all_idle_names, key=_hash_key):
        agent = name2agent[agent_name]
        brief = agent.dm.get_brief_intro()
        profile_lines.append(f"## {agent_name}\n{brief}")
    agent_profiles = "\n\n".join(profile_lines)

    # Format idle agents info by day
    day_sections = []
    for day in range(1, n_days + 1):
        agents_info = idle_agents_by_day.get(day, {})
        if not agents_info:
            day_sections.append(f"### Day {day}\nNo idle characters.")
            continue

        lines = []
        for agent_name, related_names in sorted(agents_info.items()):
            if related_names:
                related_str = ", ".join(related_names)
                lines.append(f"- **{agent_name}** (related: {related_str})")
            else:
                lines.append(f"- **{agent_name}** (no close relationships yet)")

        day_sections.append(f"### Day {day}\n" + "\n".join(lines))

    idle_agents_info = "\n\n".join(day_sections)

    # Format available locations
    locations_text = "\n".join(f"- {loc}" for loc in sorted(valid_locations))

    from src.agents.prompts import get_world_setting

    world_name = config["world"]["name"]
    prompt = build_god_generate_encounter_events_prompt(
        current_time=current_time,
        n_days=n_days,
        idle_agents_by_day=idle_agents_info,
        available_locations=locations_text,
        total_encounters=total_encounters,
        agent_profiles=agent_profiles,
        world_setting=get_world_setting(world_name),
    )

    messages = [{"role": "system", "content": prompt}]

    # Build kwargs for parser
    all_agent_names = set()
    idle_by_day_set: Dict[int, set] = {}
    for day, agents_info in idle_agents_by_day.items():
        idle_by_day_set[day] = set(agents_info.keys())
        all_agent_names.update(agents_info.keys())

    encounters_data = get_response_with_retry(
        post_processing_funcs=[_pp_parse_encounter_events],
        model=config["god_model"],
        messages=messages,
        valid_agent_names=all_agent_names,
        idle_agents_by_day=idle_by_day_set,
        valid_locations=set(valid_locations),
        n_days=n_days,
    )

    # Save generation for SFT training
    save_generation(
        feature="encounter_activity",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(encounters_data, ensure_ascii=False)
                if encounters_data
                else "null",
            }
        ],
    )

    if not encounters_data or isinstance(encounters_data, str):
        if verify_logger:
            verify_logger.warning(
                f"[VERIFY-ENCOUNTER] God Model failed to generate encounters for {current_time}"
            )
        return []

    return encounters_data


# =============================================================================
# =============================================================================
#                      POSITION APPLICATION EVALUATION
# =============================================================================


def god_evaluate_position_application(
    round_num: int,
    positions: Optional[List["Position"]],
    candidates: List["RoleAgent"],
    wishes: Optional[Dict[str, List[str]]],
    seed: str,
    sub_round: int = 1,
) -> Dict[str, List[str]]:
    """God Model evaluates position application candidates for Round 1.

    Note: Round 2 (adjustment) has been removed. All agents have original
    positions and fallback to them if not matched in Round 1.

    Args:
        round_num: Must be 1 (wish round)
        positions: List of positions being evaluated (round 1 batch)
        candidates: List of candidate RoleAgent objects
        wishes: Dict mapping agent_name to position name wishes
        seed: Seed for deterministic operations
        sub_round: Which wish is being evaluated (1, 2, or 3)

    Returns:
        Dict[position_name -> List[selected_agent_names]]
    """
    from src.agents.prompts import build_god_evaluate_position_application_prompt
    from src.world.position_application import Position

    config = get_config()
    verify_logger = get_verify_logger(feature="position_application")

    if round_num != 1:
        raise ValueError(f"Only round_num=1 is supported, got {round_num}")

    if not candidates:
        return {}

    # Build candidate info for prompt
    candidates_info = []
    for agent in candidates:
        profile = agent.dm.read_profile()
        birth_year = profile["birth_year"]
        t = agent.clock.get_time()
        age = t.year - birth_year

        # REQ-2: Read skills from state first, fallback to init_skills
        state = agent.dm.read_state(exclude_cur_t=False)
        skills = state.get("skills") or profile["init_skills"]

        candidates_info.append(
            {
                "name": agent.name,
                "age": age,
                "skills": skills,
                "brief": agent.dm.get_brief_intro(),
            }
        )

    # Sort candidates by hash for deterministic prompt
    def _hash_key(c: Dict) -> str:
        return hashlib.sha256(f"{seed}-{c['name']}".encode()).hexdigest()

    candidates_info = sorted(candidates_info, key=_hash_key)

    if verify_logger:
        # Log input details before LLM call
        pos_info = [(p.name, p.available_slots()) for p in (positions or [])]
        cand_names = [c["name"] for c in candidates_info]
        verify_logger.info(
            f"[POSITION_APPLICATION] god_evaluate_position_application INPUT: "
            f"round={round_num}, sub_round={sub_round}, "
            f"positions={pos_info}, candidates={cand_names}"
        )

    # Build prompt
    prompt = build_god_evaluate_position_application_prompt(
        round_num=round_num,
        positions=positions,
        candidates=candidates_info,
        wishes=wishes,
        sub_round=sub_round,
    )

    messages = [{"role": "system", "content": prompt}]

    # Build max_selections_by_pos for batch parser
    max_selections_by_pos = {p.name: p.available_slots() for p in (positions or [])}
    valid_position_names = set(max_selections_by_pos.keys())

    result = get_response_with_retry(
        post_processing_funcs=[_pp_parse_position_application_round1_batch],
        model=config["god_model"],
        messages=messages,
        valid_names={c["name"] for c in candidates_info},
        valid_positions=valid_position_names,
        max_selections_by_pos=max_selections_by_pos,
    )

    save_generation(
        feature="position_application",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(result, ensure_ascii=False) if result else "{}",
            }
        ],
    )

    if verify_logger:
        pos_names = [p.name for p in (positions or [])]
        verify_logger.info(
            f"[POSITION_APPLICATION] Round 1 Sub-{sub_round} - Positions: {pos_names}, "
            f"Candidates: {len(candidates_info)}, Results: {result}"
        )

    return result or {}


def _pp_parse_position_application_round1_batch(
    output: str,
    valid_names: set,
    valid_positions: set,
    max_selections_by_pos: Dict[str, int],
    **kwargs,
) -> Optional[Dict[str, List[str]]]:
    """Parse round 1 batch position application result.

    Expected format: {"Position A": ["Alice", "Bob"], "Position B": []}

    Args:
        output: LLM output string
        valid_names: Set of valid agent names
        valid_positions: Set of valid position names
        max_selections_by_pos: Dict mapping position_name to max allowed selections

    Returns:
        Dict mapping position_name to list of selected agent names
    """
    import re

    if not output:
        return None

    # Try to extract JSON object (greedy to handle nested structure)
    match = re.search(r"\{[\s\S]*\}", output)
    if not match:
        return {}

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    # Filter and validate
    result: Dict[str, List[str]] = {}
    already_selected: set = set()  # Track agents already selected to avoid duplicates

    for pos_name, selected in data.items():
        if not isinstance(pos_name, str) or pos_name not in valid_positions:
            continue
        if not isinstance(selected, list):
            continue

        max_slots = max_selections_by_pos.get(pos_name, 1)
        valid_selected = []
        for name in selected:
            if (
                isinstance(name, str)
                and name in valid_names
                and name not in already_selected
                and len(valid_selected) < max_slots
            ):
                valid_selected.append(name)
                already_selected.add(name)

        result[pos_name] = valid_selected

    return result


# =============================================================================
#                         POSITION DESIGN
# =============================================================================


def _pp_parse_positions(
    output: str,
    min_capacity: int,
    **kwargs,
) -> Optional[List[Dict]]:
    """Parse positions JSON from God Model response.

    Args:
        output: LLM response string
        min_capacity: Minimum total capacity required across all positions

    Returns:
        List of position dicts, or None to trigger retry
    """
    import re

    if not output:
        return None

    # Try to extract JSON array
    match = re.search(r"\[[\s\S]*\]", output)
    if not match:
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list) or len(data) < 1:
        return None

    # Validate and clean each position
    valid_positions = []
    seen_keys = set()  # Track unique {organization}-{role} combinations

    for i, pos in enumerate(data):
        if not isinstance(pos, dict):
            continue

        # Required fields: organization, role (not name)
        organization = pos.get("organization")
        role = pos.get("role")
        pos_type = pos.get("type")
        description = pos.get("description")
        weekly_income = pos.get("weekly_income")

        if not all(
            [
                isinstance(organization, str) and organization.strip(),
                isinstance(role, str) and role.strip(),
                isinstance(pos_type, str) and pos_type in ("work", "non-work"),
                isinstance(description, str),
                isinstance(weekly_income, (int, float)),
            ]
        ):
            continue

        # Avoid duplicate keys (organization/role is unique identifier)
        org_clean = organization.strip()
        role_clean = role.strip()
        key = f"{org_clean}/{role_clean}"
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # Validate weekly_delta_skills
        delta_skills = pos.get("weekly_delta_skills", {})
        if not isinstance(delta_skills, dict):
            delta_skills = {}

        # Validate capacity
        capacity = pos.get("capacity", 1)
        if not isinstance(capacity, int) or capacity < 1:
            capacity = 1

        # Clean position dict (organization + role as identifier)
        # name = "{organization}/{role}" is the unique key
        clean_pos = {
            "name": key,  # Unique identifier
            "organization": org_clean,
            "role": role_clean,
            "type": pos_type,
            "description": description.strip() if description else "",
            "weekly_income": int(weekly_income),
            "weekly_delta_skills": {
                k: int(v)
                for k, v in delta_skills.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            },
            "capacity": capacity,
            "occupied_by": [],
        }

        # Optional fields
        min_age = pos.get("min_age")
        if isinstance(min_age, int) and min_age > 0:
            clean_pos["min_age"] = min_age

        max_age = pos.get("max_age")
        if isinstance(max_age, int) and max_age > 0:
            clean_pos["max_age"] = max_age

        min_skills = pos.get("min_skills")
        if isinstance(min_skills, dict) and min_skills:
            clean_pos["min_skills"] = {
                k: int(v)
                for k, v in min_skills.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            }

        valid_positions.append(clean_pos)

    # Check total capacity >= min_capacity
    total_capacity = sum(p["capacity"] for p in valid_positions)
    if total_capacity < min_capacity:
        # Not enough capacity, retry
        return None

    return valid_positions if valid_positions else None


def god_design_positions(
    agents: List["RoleAgent"],
    world_setting: str,
) -> List[Dict]:
    """God Model designs positions for the world.

    Called when positions.json doesn't exist to generate initial positions
    based on world setting and agent profiles.

    Args:
        agents: List of RoleAgent instances
        world_setting: Description of the world setting

    Returns:
        List of position dicts ready to be saved to positions.json
    """
    from src.agents.prompts import build_god_design_positions_prompt

    config = get_config()
    verify_logger = get_verify_logger(feature="position_application")

    if not agents:
        return []

    # Build agents info for prompt (with top 3 skills only)
    agents_info_lines = []
    for agent in agents:
        profile = agent.dm.read_profile()
        birth_year = profile["birth_year"]
        t = agent.clock.get_time()
        age = t.year - birth_year

        # Read skills from state first (exclude_cur_t=False to get latest)
        # Fallback to init_skills if state has no skills (system just started)
        state = agent.dm.read_state(exclude_cur_t=False)
        skills = state.get("skills") or profile["init_skills"]
        # Top 3 skills only for position design (avoid prompt overflow)
        top_skills = sorted(skills.items(), key=lambda x: -x[1])[:3]
        skills_str = (
            ", ".join(f"{k}: {v}" for k, v in top_skills) if top_skills else "None"
        )

        # position is optional - agent may not have a job yet
        # position has organization and role, unique key is {org}/{role}
        position = profile.get("position")
        if position:
            org = position["organization"]
            role = position["role"]
            position_display = f"{org}/{role}" if org else role
        else:
            position_display = "None"

        brief = agent.dm.get_brief_intro()

        agents_info_lines.append(
            f"- **{agent.name}** (Age: {age})\n"
            f"  - Top Skills: {skills_str}\n"
            f"  - Current Position: {position_display}\n"
            f"  - Brief: {brief}"
        )

    agents_info = "\n".join(agents_info_lines)

    # Extract existing positions from agents' profiles (REQ: existing positions as context)
    # These positions MUST be included in the output (not disappear)
    # Use Position class to ensure data consistency
    from src.world.position_application import Position

    existing_positions: Dict[str, Position] = {}  # key: position.name (org/role)
    for agent in agents:
        profile = agent.dm.read_profile()
        pos_data = profile.get("position")
        if pos_data and pos_data.get("organization") and pos_data.get("role"):
            # Build Position from profile data (profile now has complete fields)
            position = Position.from_dict(pos_data)
            if position.name not in existing_positions:
                existing_positions[position.name] = position
            # Track which agents hold this position
            if agent.name not in existing_positions[position.name].occupied_by:
                existing_positions[position.name].occupied_by.append(agent.name)

    # Build existing positions info for prompt
    if existing_positions:
        existing_positions_lines = []
        for pos_name in sorted(existing_positions.keys()):
            pos = existing_positions[pos_name]
            agents_holding = ", ".join(pos.occupied_by)
            existing_positions_lines.append(
                f"- **{pos_name}** (type={pos.type}): held by [{agents_holding}]"
            )
        existing_positions_info = "\n".join(existing_positions_lines)
    else:
        existing_positions_info = ""

    # Calculate capacity requirements (total slots across all positions)
    total_agents = len(agents)
    min_capacity = total_agents  # Must have at least enough slots for all agents
    max_capacity = int(total_agents * 1.5)  # Allow some buffer

    # Max capacity per work position: ensures job diversity
    # Each work position can have at most 1/3 of total agents
    max_work_capacity = max(1, total_agents // 3)

    # Position count limits (number of distinct position types)
    # min: at least 10 types for variety
    # max: max(10, n_agents / 3) to avoid fragmentation
    min_position_count = 10
    max_position_count = max(10, total_agents // 3)

    # Get income range from config
    economy_config = config["world"]["economy"]
    income_min = economy_config["weekly_income"]["min"]
    income_max = economy_config["weekly_income"]["max"]

    # Get age range from config (REQ-12: Aging prior constraint)
    time_config = config["world"]["time"]
    age_min = time_config["min_age"]
    age_max = age_min + time_config["n_year"] - 1

    prompt = build_god_design_positions_prompt(
        agents_info=agents_info,
        world_setting=world_setting,
        min_capacity=min_capacity,
        max_capacity=max_capacity,
        income_min=income_min,
        income_max=income_max,
        max_work_capacity=max_work_capacity,
        age_min=age_min,
        age_max=age_max,
        existing_positions_info=existing_positions_info,
        min_position_count=min_position_count,
        max_position_count=max_position_count,
    )

    messages = [{"role": "system", "content": prompt}]

    positions_data = get_response_with_retry(
        post_processing_funcs=[_pp_parse_positions],
        model=config["god_model"],
        messages=messages,
        min_capacity=min_capacity,
    )

    # Save generation for SFT training
    save_generation(
        feature="position_application",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(positions_data, ensure_ascii=False)
                if positions_data
                else "[]",
            }
        ],
    )

    if verify_logger:
        verify_logger.info(
            f"[POSITION_APPLICATION] Designed {len(positions_data) if positions_data else 0} positions "
            f"for {total_agents} agents"
        )

    return positions_data or []


def god_grow_positions(
    agents: List["RoleAgent"],
    world_setting: str,
    existing_positions: List["Position"],
    count: int,
    created_year: int,
) -> List[Dict]:
    """God Model generates new challenging positions for yearly growth.

    Called at the start of each year (except the first) to add positions
    that serve as growth targets for agents.

    Args:
        agents: List of RoleAgent instances
        world_setting: Description of the world setting
        existing_positions: Current positions in the world
        count: Number of new positions to generate
        created_year: Year when these positions are being created

    Returns:
        List of position dicts ready for Position.from_dict(), with created_year set
    """
    from src.agents.prompts import build_god_grow_positions_prompt

    config = get_config()
    verify_logger = get_verify_logger(feature="position_application")

    if not agents or count <= 0:
        return []

    # Build existing positions info (sorted for cache determinism)
    existing_positions_lines = []
    for pos in sorted(existing_positions, key=lambda p: p.name):
        skills_str = (
            ", ".join(f"{k}: {v}" for k, v in pos.min_skills.items())
            if pos.min_skills
            else "None"
        )
        existing_positions_lines.append(
            f"- **{pos.name}** (type={pos.type}, income={pos.weekly_income}, "
            f"min_skills={{{skills_str}}}, capacity={pos.capacity})"
        )
    existing_positions_info = (
        "\n".join(existing_positions_lines) or "No existing positions yet."
    )

    # Collect agent skills distribution (max value per skill across all agents)
    all_skills: Dict[str, int] = {}
    for agent in agents:
        state = agent.dm.read_state(exclude_cur_t=False)
        profile = agent.dm.read_profile()
        skills = state.get("skills") or profile["init_skills"]
        for skill, value in skills.items():
            if skill not in all_skills or value > all_skills[skill]:
                all_skills[skill] = value

    agent_skills_lines = [
        f"- {skill}: {all_skills[skill]} (highest)"
        for skill in sorted(all_skills.keys())
    ]
    agent_skills_info = "\n".join(agent_skills_lines) or "No skills data available"

    # Get config values
    time_config = config["world"]["time"]
    age_min = time_config["min_age"]
    age_max = age_min + time_config["n_year"] - 1
    income_max = config["world"]["economy"]["weekly_income"]["max"]

    prompt = build_god_grow_positions_prompt(
        world_setting=world_setting,
        existing_positions_info=existing_positions_info,
        agent_skills_info=agent_skills_info,
        count=count,
        age_min=age_min,
        age_max=age_max,
        income_max=income_max,
    )

    messages = [{"role": "system", "content": prompt}]

    # Reuse _pp_parse_positions for parsing (min_capacity=0 to skip capacity check)
    positions_data = get_response_with_retry(
        post_processing_funcs=[_pp_parse_positions],
        model=config["god_model"],
        messages=messages,
        min_capacity=0,  # No minimum capacity requirement for growth positions
    )

    # Save generation for SFT training
    save_generation(
        feature="position_application",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(positions_data, ensure_ascii=False)
                if positions_data
                else "[]",
            }
        ],
    )

    if positions_data:
        # Add created_year to each position
        for pos_data in positions_data:
            pos_data["created_year"] = created_year

        # Filter out duplicates with existing positions
        existing_names = {p.name for p in existing_positions}
        before_filter = len(positions_data)
        positions_data = [p for p in positions_data if p["name"] not in existing_names]

        # Log warning if fewer positions than requested
        actual = len(positions_data)
        if actual < count and verify_logger:
            verify_logger.warning(
                f"[POSITIONS] Requested {count} positions but got {actual} "
                f"(filtered {before_filter - actual} duplicates)"
            )

    if verify_logger:
        verify_logger.info(
            f"[POSITIONS] Generated {len(positions_data) if positions_data else 0} "
            f"challenging positions for year {created_year}"
        )

    return positions_data or []


# =============================================================================
#                     YEARLY PROFILE UPDATE
# =============================================================================


# Quantitative field definitions
def _clip_quantitative_values(
    old_values: Dict[str, int],
    new_values: Dict[str, int],
    delta_limit: int,
) -> Dict[str, int]:
    """Clip quantitative value changes to delta limits.

    Fields are dynamically determined from old_values (current profile).
    New fields in new_values are allowed but start from 50.

    Args:
        old_values: Current year's quantitative values
        new_values: LLM-proposed new values
        delta_limit: Max absolute change per year (e.g., 5 for personality)

    Returns:
        Clipped values dict, all integers within [0, 100]
    """
    result = {}
    # Process existing fields
    for key in old_values:
        old = int(old_values[key])
        if key in new_values:
            new = int(new_values[key])
            delta = max(-delta_limit, min(delta_limit, new - old))
            result[key] = max(0, min(100, old + delta))
        else:
            # Field not in LLM output, keep unchanged
            result[key] = old

    # Process new fields (if LLM added any based on yearly experiences)
    for key in new_values:
        if key not in old_values:
            # New field: start from 50, apply delta limit
            new = int(new_values[key])
            delta = max(-delta_limit, min(delta_limit, new - 50))
            result[key] = max(0, min(100, 50 + delta))
    return result


def _pp_validate_profile_update(response: str, **kwargs) -> Optional[Dict]:
    """Post-processor: validate and merge profile update from LLM response.

    Returns merged complete profile dict, or None to trigger retry.
    """
    from src.utils import extract_json
    from src.agents.prompts import PROFILE_IMMUTABLE_FIELDS, PROFILE_UPDATABLE_FIELDS

    current_profile = kwargs["current_profile"]

    # 1. Parse JSON from response
    updates = extract_json(response, **kwargs)
    if not updates or not isinstance(updates, dict):
        return None

    # 2. Validate quantitative structure exists
    try:
        personality_q = updates["personality_traits"]["quantitative"]
        talents_q = updates["talents"]["quantitative"]
    except (KeyError, TypeError):
        return None

    # Validate they are dicts (fields vary per agent)
    if not isinstance(personality_q, dict) or not isinstance(talents_q, dict):
        return None

    # 3. Clip quantitative values to delta limits (fields from current profile)
    clipped_personality = _clip_quantitative_values(
        current_profile["personality_traits"]["quantitative"],
        personality_q,
        delta_limit=5,
    )
    clipped_talents = _clip_quantitative_values(
        current_profile["talents"]["quantitative"],
        talents_q,
        delta_limit=3,
    )

    # 4. Build new profile: immutable fields + updated fields
    new_profile = {}

    # Copy immutable fields
    for field in PROFILE_IMMUTABLE_FIELDS:
        if field in current_profile:
            new_profile[field] = current_profile[field]

    # Apply updated fields
    clipped_map = {
        "personality_traits": clipped_personality,
        "talents": clipped_talents,
    }
    for field in PROFILE_UPDATABLE_FIELDS:
        if field in clipped_map:
            # Fields with quantitative sub-structure
            qualitative = updates[field].get(
                "qualitative", current_profile[field]["qualitative"]
            )
            new_profile[field] = {
                "qualitative": qualitative,
                "quantitative": clipped_map[field],
            }
        elif field in updates:
            new_profile[field] = updates[field]
        elif field in current_profile:
            new_profile[field] = current_profile[field]

    return new_profile


def update_yearly_profile(
    agent: "RoleAgent",
    current_year: int,
    next_year: int,
) -> Dict:
    """GodModel generates profile for next year based on yearly experiences.

    Args:
        agent: RoleAgent instance
        current_year: Current year number
        next_year: Next year number

    Returns:
        Complete new profile dict for next year
    """
    from src.agents.prompts import build_god_yearly_profile_update_prompt
    from src.utils import get_verify_logger

    config = get_config()
    verify_logger = get_verify_logger(feature="profile_update")

    # 1. Read current profile
    current_profile = agent.dm.read_profile()

    # 2. Read yearly summaries (sorted by time for deterministic Prompt)
    n_week = config["world"]["time"]["n_week"]
    summaries = agent.dm.read_weekly_summaries(n_weeks=n_week)
    assert summaries, f"No weekly summaries for {agent.name} Y{current_year}"
    # Sort by time to ensure deterministic Prompt (cache stability)
    summaries.sort(key=lambda s: s["time"])

    # Format summaries as text
    summaries_text = "\n\n".join(f"**{s['time']}**:\n{s['content']}" for s in summaries)

    if verify_logger:
        # Log input summary
        cur_pq = current_profile["personality_traits"]["quantitative"]
        cur_tq = current_profile["talents"]["quantitative"]
        verify_logger.info(
            f"[VERIFY-PROFILE] {agent.name} LLM INPUT: "
            f"n_summaries={len(summaries)}, "
            f"cur_personality={cur_pq}, "
            f"cur_talents={cur_tq}"
        )

    # 3. Build prompt
    prompt = build_god_yearly_profile_update_prompt(
        agent_name=agent.name,
        current_profile=current_profile,
        yearly_summaries=summaries_text,
        current_year=current_year,
        next_year=next_year,
    )

    messages = [{"role": "system", "content": prompt}]

    # 4. Call LLM with post-processing
    new_profile = get_response_with_retry(
        post_processing_funcs=[_pp_validate_profile_update],
        model=config["god_model"],
        messages=messages,
        current_profile=current_profile,
    )

    # 5. Save generation for SFT training
    save_generation(
        feature="profile_update",
        inputs=messages,
        outputs=[
            {
                "role": "assistant",
                "content": json.dumps(new_profile, ensure_ascii=False)
                if new_profile
                else "null",
            }
        ],
    )

    # 6. Handle failure
    if new_profile is None:
        if verify_logger:
            verify_logger.error(
                f"[VERIFY-PROFILE] Failed to update profile for {agent.name}, "
                f"keeping current profile"
            )
        # Return current profile as fallback (no changes)
        return current_profile

    # 7. Log changes for verification
    if verify_logger:
        changes = []
        # Log personality trait changes
        cur_pq = current_profile["personality_traits"]["quantitative"]
        new_pq = new_profile["personality_traits"]["quantitative"]
        for key in cur_pq:
            if cur_pq[key] != new_pq.get(key):
                changes.append(f"personality.{key}: {cur_pq[key]} → {new_pq[key]}")
        # Log talent changes
        cur_tq = current_profile["talents"]["quantitative"]
        new_tq = new_profile["talents"]["quantitative"]
        for key in cur_tq:
            if cur_tq[key] != new_tq.get(key):
                changes.append(f"talents.{key}: {cur_tq[key]} → {new_tq[key]}")

        if changes:
            verify_logger.info(
                f"[VERIFY-PROFILE] {agent.name} Y{current_year}→Y{next_year}: "
                + ", ".join(changes)
            )
        else:
            verify_logger.info(
                f"[VERIFY-PROFILE] {agent.name} Y{current_year}→Y{next_year}: no quantitative changes"
            )

    return new_profile
