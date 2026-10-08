from __future__ import annotations

"""
Map generation via LLM.

Returned schema:
{
  "public": {
    "Location Name": {"display_name": "Location Name", "size": "small|medium|large", "description": "...", "objects": [...]},
    ...
  }
}

Private homes are handled separately by LocationStore.ensure().
"""

from typing import Dict, List, Optional

from src.config import get_config


# Detail level presets
DETAIL_PRESETS = {
    "low": {"desc_sentences": "2-3", "objects": "3-4"},
    "medium": {"desc_sentences": "4-6", "objects": "5-6"},
    "high": {"desc_sentences": "6-8", "objects": "7-10"},
}


def _validate_locations_response(response: str, **kwargs) -> dict:
    """Validate LLM output contains non-empty public locations.

    Returns parsed & normalized dict if valid, None to trigger retry.
    """
    from src.utils import extract_json

    data = extract_json(response, **kwargs)
    if not data or not isinstance(data, dict):
        return None

    normalized = _normalize(data)
    if not normalized["public"]:
        return None

    return normalized


def generate_locations_via_llm(
    world_cfg: Dict,
    opts: Dict,
    agents_summary: str,
    avoid_names: Optional[List[str]] = None,
) -> Dict[str, Dict]:
    """Generate a public map via LLM.

    Args:
        world_cfg: World configuration dict
        opts: {"n_locations": int, "detail_level": "low"|"medium"|"high"}
        agents_summary: Formatted string with all agents' profile summaries

    Returns:
        {"public": {location_name: location_data, ...}}

    Raises on any failure - no fallback.
    """
    from src.utils import get_response_with_retry

    from src.agents.prompts import get_world_setting

    cfg = get_config()
    model = cfg["god_model"]
    language = cfg["world"].get("language", "zh")
    world_name = str((world_cfg or {}).get("name", "world"))

    n_locations = int(opts.get("n_locations", 30))
    detail_level = str(opts.get("detail_level", "medium")).lower()
    if detail_level not in DETAIL_PRESETS:
        detail_level = "medium"
    detail = DETAIL_PRESETS[detail_level]

    # Build prompt
    lang_hint = "Chinese" if language in ("zh", "cn") else "English"
    world_setting = get_world_setting(world_name)
    avoid_names = sorted({str(x).strip() for x in (avoid_names or []) if str(x).strip()})
    avoid_block = (
        "\nExisting public location names that MUST NOT be reused:\n"
        + "\n".join(f"- {name}" for name in avoid_names[:200])
        if avoid_names
        else ""
    )

    prompt = f"""You are designing a public location map for a role-play simulation world.

## World Setting
{world_setting}

World name: {world_name}
Language: {lang_hint}
Number of locations: {n_locations}

# Characters in this world
{agents_summary}
{avoid_block}

Requirements:
1. Generate exactly {n_locations} public locations that fit this world's setting
2. Each location needs:
   - display_name: the location name
   - size: "small", "medium", or "large"
   - description: {detail["desc_sentences"]} sentences describing the place (include spatial layout, atmosphere)
   - objects: {detail["objects"]} items found there
3. Mix of sizes: roughly 50% small, 35% medium, 15% large
4. Do NOT include private homes
5. Avoid real-world brand names or proper nouns
6. Do not reuse any location name listed in the existing-location block
7. IMPORTANT: All strings must be valid JSON. Escape any quotes inside strings with backslash (e.g., "sign says \\"Hello\\"" not "sign says "Hello"")

Output ONLY valid JSON in this format (use actual descriptive location names, NOT placeholder names like "Location1"):
{{"public": {{"Cafeteria": {{"display_name": "Cafeteria", "size": "large", "description": "...", "objects": ["item1", "item2"]}}, "Library": {{"display_name": "Library", "size": "large", "description": "...", "objects": [...]}}, ...}}}}
"""

    data = get_response_with_retry(
        post_processing_funcs=[_validate_locations_response],
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )

    if not isinstance(data, dict) or not data.get("public"):
        raise RuntimeError(
            "Failed to generate locations via LLM after retries. "
            f"Response: {str(data)[:200]}"
        )

    return data


def _normalize(data: Dict) -> Dict:
    """Normalize LLM output to ensure consistent schema."""
    result = {"public": {}}
    pub = data.get("public", {}) if isinstance(data, dict) else {}

    if not isinstance(pub, dict):
        return result

    for key, val in pub.items():
        name = str(key).strip()
        if not name:
            continue

        size = str(val.get("size", "medium"))
        if size not in ("small", "medium", "large"):
            size = "medium"

        desc = str(val.get("description", "")).strip()
        objs = [str(x).strip() for x in (val.get("objects") or []) if str(x).strip()]

        result["public"][name] = {
            "display_name": name,
            "size": size,
            "description": desc,
            "objects": objs,
        }

    return result
