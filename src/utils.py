import os
import re
import random
import openai
import json
import logging
import time
import jsonlines
import requests
import io
import hashlib
import pickle
import random
import tiktoken
import copy
import threading
import __main__
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv
from src.config import get_config

load_dotenv()

streaming = False
# Deprecated mock switch (no-op). Mock paths removed to avoid divergence.
_MOCK_MODE = False
_ERROR_RESPONSE = "NO_RESPONSE"
_MAX_GENERATION = 5
_USE_CHAT_COMPLETIONS = True
_USE_RESPONSES_API = False


def _get_max_tokens_for_model(model: str, kwargs: dict) -> int:
    """Get max_tokens for a model.

    Rules:
    1. Explicit max_tokens/max_output_tokens in kwargs → use it
    2. model_type="role" → role_model_max_tokens
    3. Everything else (including fallback) → god_model_max_tokens
    """
    # 1. Check explicit kwargs
    if "max_tokens" in kwargs:
        return int(kwargs["max_tokens"])
    if "max_output_tokens" in kwargs:
        return int(kwargs["max_output_tokens"])

    cfg = get_config()

    # 2. Per-model override (e.g. reasoning models that consume tokens internally)
    model_cfg = cfg.get("models", {}).get(model, {})
    if "max_tokens" in model_cfg:
        return int(model_cfg["max_tokens"])

    # 3. Only RoleAgent uses role_model_max_tokens
    if kwargs.get("model_type") == "role":
        return int(cfg["role_model_max_tokens"])

    # 4. Everything else uses god_model_max_tokens
    return int(cfg["god_model_max_tokens"])


def setup_logger(name, level=logging.INFO, quiet=False):
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        logger.handlers.clear()

    # If a run_id is set, write logs to logs/{run_id}/; otherwise write to logs/
    if _current_run_id:
        target_dir = get_project_root() / "logs" / _current_run_id
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = logs_dir

    log_file = str(target_dir / f"{name}.log")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    if not quiet:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_formatter = logging.Formatter(
            "%(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    return logger


# Get the project root and ensure the logs directory exists
from pathlib import Path

_logger_registry: Dict[str, logging.Logger] = {}
_current_run_id: str | None = None  # run_id of the current run, used for the log directory


def set_log_run_id(run_id: str) -> None:
    """Set the run_id for the current run; logs will be written to logs/{run_id}/.

    Should be called during World initialization, passing the run_id extracted
    from data_dir. Migrates all existing loggers' file handlers to the new directory.
    """
    global _current_run_id
    _current_run_id = run_id
    # Ensure the directory exists
    run_logs_dir = get_project_root() / "logs" / run_id
    run_logs_dir.mkdir(parents=True, exist_ok=True)

    # Migrate existing loggers to the new run-specific directory
    for name, logger in _logger_registry.items():
        new_handlers = []
        for h in logger.handlers:
            if isinstance(h, logging.FileHandler):
                new_path = str(run_logs_dir / f"{name}.log")
                new_fh = logging.FileHandler(new_path, encoding="utf-8")
                new_fh.setLevel(h.level)
                new_fh.setFormatter(h.formatter)
                h.close()
                new_handlers.append(new_fh)
            else:
                new_handlers.append(h)
        logger.handlers = new_handlers


def get_logger(
    name: str, level: int = logging.INFO, quiet: bool = False
) -> logging.Logger:
    """Return a cached logger configured through ``setup_logger``.

    The first call for a given ``name`` creates and stores the logger; subsequent
    calls return the same instance so handler configuration stays consistent.
    """
    if name not in _logger_registry:
        _logger_registry[name] = setup_logger(name, level=level, quiet=quiet)
    return _logger_registry[name]


def get_project_root():
    return Path(__file__).parent.parent


project_root = get_project_root()
logs_dir = project_root / "logs"
logs_dir.mkdir(exist_ok=True)


# ============================================================
# Feature Verification Logging Utilities
# ============================================================
# Utilities for feature development verification logging
# Log path: logs/verify/{feature_name}_{run_id}/

_feature_logger_registry: Dict[str, logging.Logger] = {}


def get_verify_logger(
    feature: str | None = None, thread_id: str | None = None
) -> logging.Logger:
    """Get a verification logger (always enabled, one log file per feature).

    Args:
        feature: Feature name (e.g. "solo_activity", "joint_activity", "economy").
                If None, "main" is used.
        thread_id: Thread identifier (optional, used for concurrency).

    Returns:
        A verification logger (never None).

    Log path: logs/verify/{world_run_id}/{feature}.log
              or logs/verify/{world_run_id}/{feature}_thread_{id}.log (concurrent case)

    How it works:
    - Extracts world_run_id from config["world"]["data_dir"] (format: data/{name}_{runid}).
    - Falls back to "unknown" if data_dir is missing or malformed.
    - Each feature is written to its own log file.

    Log file structure:
        logs/verify/schooldays_01201830/
        ├── solo_activity.log          # Solo Activity only
        ├── joint_activity.log         # Joint Activity only
        ├── economy.log                # Economy system only
        └── main.log                   # Other general logs

    Example:
        logger = get_verify_logger(feature="solo_activity")
        if logger:
            logger.info("[VERIFY-SOLO] Starting...")
    """
    from src.config import get_config
    from pathlib import Path

    config = get_config()
    data_dir = config["world"].get("data_dir", "")

    # Extract world_run_id from data_dir (format: data/{name}_{runid})
    # e.g. "schooldays_01201830" <- "data/schooldays_01201830"
    if data_dir:
        world_run_id = Path(data_dir).name
    else:
        # Fallback: verification logging called before World init (rare edge case)
        world_run_id = "unknown"

    if feature is None:
        feature = "main"

    # Log directory: logs/verify/{world_run_id}/
    verify_dir = logs_dir / "verify" / world_run_id
    verify_dir.mkdir(parents=True, exist_ok=True)

    # Log file name: {feature}.log or {feature}_thread_{id}.log
    if thread_id is None:
        log_file = verify_dir / f"{feature}.log"
        logger_key = f"verify_{world_run_id}_{feature}"
    else:
        log_file = verify_dir / f"{feature}_thread_{thread_id}.log"
        logger_key = f"verify_{world_run_id}_{feature}_{thread_id}"

    if logger_key in _feature_logger_registry:
        return _feature_logger_registry[logger_key]

    logger = logging.getLogger(logger_key)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

    _feature_logger_registry[logger_key] = logger
    return logger


def format_llm_output_summary(
    messages: List[Dict],
    output: str,
    max_preview_len: int = 200,
    extra: Dict | None = None,
) -> str:
    """Format an LLM output summary for writing to a .log file.

    Args:
        messages: Prompt messages.
        output: LLM output string.
        max_preview_len: Maximum length of the output preview.
        extra: Optional extra metadata (e.g. model name).

    Returns:
        Formatted summary string.

    Example:
        logger.info(format_llm_output_summary(messages, output, extra={"model": "gpt-4"}))
    """
    lines = []

    # Extra metadata (e.g. model name)
    if extra:
        extra_str = ", ".join(f"{k}={v}" for k, v in extra.items())
        lines.append(f"[VERIFY-LLM] Extra: {extra_str}")

    # Prompt info
    msg_count = len(messages)
    roles = [msg.get("role", "unknown") for msg in messages]
    lines.append(f"[VERIFY-LLM] Prompt: {msg_count} messages ({', '.join(roles)})")

    # Output preview
    output_len = len(output)
    if output_len <= max_preview_len:
        preview = output
        truncated = ""
    else:
        preview = output[:max_preview_len]
        truncated = f" (truncated, total {output_len} chars)"

    lines.append(f'[VERIFY-LLM] Output: "{preview}"{truncated}')

    return "\n".join(lines)


def save_feature_generation(
    messages: List[Dict],
    output: str,
    feature: str | None = None,
    thread_id: str | None = None,
    extra: Dict | None = None,
) -> None:
    """Save LLM prompt and output to the verification directory (always enabled, separated by feature).

    Args:
        messages: LLM prompt messages.
        output: LLM output string.
        feature: Feature name (e.g. "solo_activity", "joint_activity"). Defaults to "main".
        thread_id: Thread identifier (optional, used for concurrent runs).
        extra: Optional extra metadata (e.g. model name).

    Saves to: logs/verify/{world_run_id}/generations/{feature}.jsonl
              or logs/verify/{world_run_id}/generations/{feature}_thread_{id}.jsonl
    Also writes a human-readable .md file alongside the .jsonl.

    Note: This function only saves to the generations/ directory.
    To also log a summary to .log, the caller should use:
        logger.info(format_llm_output_summary(messages, output, extra=extra))

    Example:
        save_feature_generation(
            messages=messages,
            output=response,
            feature="solo_activity",
            extra={"model": "gpt-4", "stage": "plan"}
        )
    """
    from datetime import datetime
    from src.config import get_config
    from pathlib import Path

    config = get_config()
    data_dir = config["world"].get("data_dir", "")

    # Extract world_run_id from data_dir
    if data_dir:
        world_run_id = Path(data_dir).name
    else:
        world_run_id = "unknown"

    if feature is None:
        feature = "main"

    # Build directory: logs/verify/{world_run_id}/generations/
    verify_dir = logs_dir / "verify" / world_run_id
    gen_dir = verify_dir / "generations"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # Filename: {feature}.jsonl or {feature}_thread_{id}.jsonl
    if thread_id is None:
        jsonl_path = gen_dir / f"{feature}.jsonl"
        md_path = gen_dir / f"{feature}.md"
    else:
        jsonl_path = gen_dir / f"{feature}_thread_{thread_id}.jsonl"
        md_path = gen_dir / f"{feature}_thread_{thread_id}.md"

    timestamp = datetime.now().isoformat()
    record = {
        "timestamp": timestamp,
        "messages": messages,
        "output": output,
    }
    if extra:
        record["extra"] = extra

    # Append to jsonl
    with jsonl_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Append to human-readable md file
    with md_path.open("a", encoding="utf-8") as f:
        f.write(f"\n# ==== Generation at {timestamp} ====\n\n")
        f.write("## Input Messages\n\n")
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            f.write(f"### [{role}]\n```\n{content}\n```\n\n")
        f.write("## Output\n\n")
        f.write(f"```\n{output}\n```\n\n")
        if extra:
            f.write("## Extra Info\n\n")
            f.write(
                f"```json\n{json.dumps(extra, ensure_ascii=False, indent=2)}\n```\n\n"
            )
        f.write("---\n")


logger = setup_logger("utils", level=logging.INFO, quiet=True)

cache_path = project_root / "llm_cache/.cache.pkl"
cache_sign = True

# Per-run cache isolation: each run uses its own cache directory
_run_cache_dir: Path | None = None


def set_run_cache_dir(run_data_dir: str) -> Path:
    """Set the cache directory for the current run.

    The shared cache is loaded directly from the main llm_cache/ directory.
    The run directory only stores incremental shard files for this run.

    Args:
        run_data_dir: Run data directory name (e.g. "schooldays_02282133").

    Returns:
        Path to the run cache directory.
    """
    global _run_cache_dir
    run_cache = project_root / "llm_cache" / run_data_dir
    run_cache.mkdir(parents=True, exist_ok=True)
    # No pkl copy — shared_cache loads from main llm_cache/ dir directly
    _run_cache_dir = run_cache
    logger.info(f"Set run cache dir: {run_cache}")
    return run_cache


def get_run_cache_dir() -> Path | None:
    """Return the cache directory for the current run."""
    return _run_cache_dir


def _get_cache_base_path(cache_file: Path | str | None = None) -> Path:
    """Return the effective cache base path.

    Args:
        cache_file: Optional path override for the cache file.

    Returns:
        If a run cache dir is set, returns the path under that directory;
        otherwise returns the original cache path.
    """
    if cache_file is not None:
        cache_file = Path(cache_file)
        if _run_cache_dir is not None:
            # Redirect to run directory
            return _run_cache_dir / cache_file.name
        return cache_file

    if _run_cache_dir is not None:
        return _run_cache_dir / ".cache.pkl"
    return cache_path


def _get_thread_cache_file(base_cache_file: str) -> str:
    """Return thread-specific cache shard path for worker threads.

    Naming strategy:
    - Main thread: returns base_cache_file unchanged
    - Worker thread: ALL caches (global and agent) use shards

    Rationale:
    - Thread-local cache (via _tls.cache_map) means different threads have
      independent in-memory dicts
    - Without sharding, different threads writing to the same file will
      overwrite each other's entries (race condition)
    - See features/cache.md "Agent Cache race condition" for detailed analysis

    Examples:
        Main thread + .cache_agent=alice.pkl → .cache_agent=alice.pkl
        Worker 123 + .cache_agent=alice.pkl  → .cache_agent=alice_worker-123.pkl
        Worker 123 + .cache.pkl              → .cache_worker-123.pkl
    """
    import threading

    tid = threading.current_thread().ident
    main_tid = threading.main_thread().ident

    if tid == main_tid:
        return base_cache_file  # Main thread uses original path

    # Worker thread: ALL caches use shards to avoid race conditions
    base = Path(base_cache_file)
    stem = base.stem  # e.g. ".cache" or ".cache_agent=alice"
    shard_stem = f"{stem}_worker-{tid}"
    return str(base.parent / f"{shard_stem}{base.suffix}")


# Thread-local cache state
_tls = threading.local()

# Track cache misses per run of scripts/run_world.py to persist keys for debugging.
# NOTE: Kept for debugging — records the first 5 cache-miss keys per run (see cached() below)
_cache_miss_count: int = 0
_cache_miss_lock = threading.Lock()

# === Shared cache architecture ===
# Three-tier lookup: worker_delta → main_thread_delta → shared_cache (disk)
# - _shared_cache: loaded from disk once per cache_name, READ-ONLY after init
# - _main_thread_delta: written by main thread god calls (before workers start)
# - worker delta: per-thread via _tls, registered in _delta_registry for flush
_shared_cache: dict[str, dict] = {}  # cache_name → dict
_shared_cache_lock = threading.Lock()  # protects _shared_cache init
_main_thread_delta: dict[str, dict] = {}  # cache_name → dict

# Global registry: track all worker thread deltas for flush_all_caches()
_delta_registry_lock = threading.Lock()
_delta_registry: dict[int, dict[str, dict]] = {}  # tid → {cache_name → delta}
_shard_registry: dict[int, dict[str, str]] = {}  # tid → {cache_name → shard_path}

# Flush delta to disk every N misses. Set to 1 (immediate flush) because
# batching is unreliable — a kill/crash loses all unflushed entries.
# The I/O cost per flush is negligible (~10ms) compared to LLM latency.
_FLUSH_EVERY_N = 1


def _get_main_dir_path(cache_name: str) -> Path:
    """Return the path to the cache file in the main llm_cache/ directory (used to load shared_cache)."""
    return project_root / "llm_cache" / cache_name


def _ensure_shared_cache(cache_name: str) -> dict:
    """Ensure the shared cache for cache_name is loaded from disk. Thread-safe."""
    if cache_name in _shared_cache:
        return _shared_cache[cache_name]
    with _shared_cache_lock:
        if cache_name not in _shared_cache:  # double-check
            main_path = _get_main_dir_path(cache_name)
            if main_path.exists():
                loaded = _safe_load_pickle(str(main_path))
                _shared_cache[cache_name] = loaded if loaded is not None else {}
            else:
                _shared_cache[cache_name] = {}
    return _shared_cache[cache_name]


def _get_or_create_delta(cache_name: str, shard_path: str) -> dict:
    """Return the current thread's delta dict, registering it globally on first access."""
    tid = threading.current_thread().ident
    main_tid = threading.main_thread().ident

    if tid == main_tid:
        if cache_name not in _main_thread_delta:
            _main_thread_delta[cache_name] = {}
        return _main_thread_delta[cache_name]

    # Worker thread: use thread-local + register globally
    delta_map = getattr(_tls, "delta_map", None)
    if delta_map is None:
        delta_map = {}
        _tls.delta_map = delta_map

    if cache_name not in delta_map:
        delta = {}
        delta_map[cache_name] = delta
        with _delta_registry_lock:
            _delta_registry.setdefault(tid, {})[cache_name] = delta
            _shard_registry.setdefault(tid, {})[cache_name] = shard_path
    return delta_map[cache_name]


def _flush_delta(cache_name: str, shard_path: str, delta: dict) -> None:
    """Flush the delta dict to a shard file (incremental merge)."""
    if not delta:
        return
    try:
        Path(shard_path).parent.mkdir(parents=True, exist_ok=True)
        existing = _safe_load_pickle(shard_path) if Path(shard_path).exists() else None
        if existing:
            existing.update(delta)
            with open(shard_path, "wb") as f:
                pickle.dump(existing, f)
        else:
            with open(shard_path, "wb") as f:
                pickle.dump(dict(delta), f)
    except Exception:
        logger.error("Failed to flush delta to %s", shard_path)


def _log_to_world_logger(message: str) -> None:
    """Log message to world logger file (not console).

    World logger name format: world_{worldname}_{runid}
    Examples: world_schooldays_01151703, world_smallville_01091552

    This function writes only to the file handler, not console.
    """
    import logging

    # Search for active world logger (name starts with "world_")
    for logger_name in logging.root.manager.loggerDict:
        if logger_name.startswith("world_"):
            world_logger = logging.getLogger(logger_name)
            if world_logger.hasHandlers():
                # Write only to file handlers, skip console handlers
                record = world_logger.makeRecord(
                    world_logger.name, logging.INFO, "(cached)", 0, message, (), None
                )
                for handler in world_logger.handlers:
                    # Only write to FileHandler, skip StreamHandler (console)
                    if isinstance(handler, logging.FileHandler):
                        handler.emit(record)
                break  # Only log to the first active world logger


config = get_config()


def _to_canonical(obj: Any) -> Any:
    """Return a JSON-serializable, order-stable form of obj."""
    # Normalize common containers recursively
    if isinstance(obj, dict):
        return {
            str(k): _to_canonical(v)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(obj, (list, tuple)):
        return [_to_canonical(v) for v in obj]
    if isinstance(obj, set):
        return sorted([_to_canonical(v) for v in obj], key=lambda x: repr(x))
    # Primitive types are stable
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Fallback to string repr (last resort - should be rare)
    return repr(obj)


def _canonical_key(
    func_name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]
) -> tuple:
    """Build a stable cache key tuple for any function.

    For generate_with_fc/_get_response specifically, remove ephemeral ids and
    canonicalize nested JSON so semantically-equivalent requests produce
    identical cache keys.
    """

    # Remove volatile kwargs that should not affect semantics
    # Note: 'cache_file' is used to choose the backing store and must NOT affect the cache key.
    # Note: 'max_tokens'/'max_output_tokens' only affect output length limit, not semantics.
    # Note: 'force_regenerate' is a control flag, not semantic content.
    # Note: 'nth_generation' is internal retry counter, not semantic content.
    volatile = {
        "timeout",
        "cache_file",
        "max_tokens",
        "max_output_tokens",
        "model_type",
        "force_regenerate",
        "nth_generation",
    }
    clean_kwargs = {k: v for k, v in kwargs.items() if k not in volatile}

    def _normalize_arguments_json(val: Any) -> Any:
        try:
            if isinstance(val, (dict, list)):
                return json.dumps(
                    _to_canonical(val),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            if isinstance(val, str):
                parsed = json.loads(val)
                return json.dumps(
                    _to_canonical(parsed),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
        except Exception:
            pass
        return val

    def _normalize_text_for_key(s: str) -> str:
        """Whitespace-stable representation for cache key only (not changing semantics)."""
        try:
            s = s.replace("\r\n", "\n").replace("\r", "\n")
            s = "\n".join([ln.rstrip() for ln in s.split("\n")])
            s = re.sub(r"[ \t]{2,}", " ", s)
            s = re.sub(r"\n{3,}", "\n\n", s)
        except Exception:
            pass
        return s

    def _normalize_messages(msgs: Any) -> Any:
        if not isinstance(msgs, list):
            return msgs
        out: List[Dict[str, Any]] = []
        for m in msgs:
            if not isinstance(m, dict):
                out.append(m)
                continue
            mm: Dict[str, Any] = {}
            for k, v in m.items():
                if k == "tool_call_id":
                    # Drop ephemeral linkage id from tool messages
                    continue
                if k == "tool_calls" and isinstance(v, list):
                    tc_list: List[Dict[str, Any]] = []
                    for tc in v:
                        if not isinstance(tc, dict):
                            tc_list.append(tc)
                            continue
                        tc_new: Dict[str, Any] = {}
                        for tk, tv in tc.items():
                            if tk == "id":
                                # Drop ephemeral id generated by the model
                                continue
                            if tk == "function" and isinstance(tv, dict):
                                fn_new: Dict[str, Any] = {}
                                for fk, fv in tv.items():
                                    if fk == "arguments":
                                        fn_new[fk] = _normalize_arguments_json(fv)
                                    else:
                                        fn_new[fk] = fv
                                tc_new[tk] = fn_new
                            else:
                                tc_new[tk] = tv
                        tc_list.append(tc_new)
                    mm[k] = tc_list
                elif k == "content" and isinstance(v, str):
                    # Remove trailing [file.py:123] noise and normalize whitespace (key only)
                    try:
                        s = re.sub(r"\s*\[[^\n\]]+\.py:\d+\]\s*$", "", v)
                    except Exception:
                        s = v
                    mm[k] = _normalize_text_for_key(s)
                else:
                    mm[k] = v
            out.append(mm)
        return out

    def _normalize_functions(funcs: Any) -> Any:
        if not isinstance(funcs, list):
            return funcs
        try:
            return sorted(
                funcs,
                key=lambda f: (f.get("name", "") if isinstance(f, dict) else ""),
            )
        except Exception:
            return funcs

    # Special handling for LLM calls
    if func_name in {"generate_with_fc", "_get_response"}:
        ck = dict(clean_kwargs)
        if "messages" in ck:
            ck["messages"] = _normalize_messages(ck["messages"])
        if "functions" in ck:
            ck["functions"] = _normalize_functions(ck["functions"])
        canon = {
            "func": func_name,
            "args": _to_canonical(args),
            "kwargs": _to_canonical(ck),
        }
    else:
        canon = {
            "func": func_name,
            "args": _to_canonical(args),
            "kwargs": _to_canonical(clean_kwargs),
        }

    try:
        payload = json.dumps(
            canon, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except Exception:
        payload = str(
            (
                func_name,
                args,
                tuple(sorted(clean_kwargs.items(), key=lambda kv: str(kv[0]))),
            )
        )
    return (func_name, payload)


def _safe_load_pickle(
    path: str, max_retries: int = 3, retry_delay: float = 0.1
) -> dict | None:
    """Safely load a pickle file with retry logic to handle concurrent access.

    Uses 'with open' to ensure proper file handle cleanup, reads entire content
    into memory before unpickling to avoid partial reads during concurrent writes.

    Returns None if loading fails after all retries.
    """
    import time

    for attempt in range(max_retries):
        try:
            with open(path, "rb") as f:
                content = f.read()
            return pickle.loads(content)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
            else:
                logger.debug(
                    f"Failed to load pickle from {path} after {max_retries} attempts: {e}"
                )
    return None


# AGENTOPIA_RIGHT_SIZING_TELEMETRY_START
_right_sizing_telemetry_lock = threading.Lock()


def _right_sizing_tier(model: str) -> str:
    """Map a configured model name to the public right-sizing tier label."""
    name = str(model or "").lower()
    if "social" in name or "350m" in name:
        return "350M"
    if "citizen" in name or "1.2b" in name:
        return "1.2B"
    if "strategy" in name or "2.6b" in name:
        return "2.6B"
    if "cyber" in name or "7b" in name:
        return "specialist"
    return "other"


def _record_right_sizing_request(model: str, latency_ms: float, success: bool, call_kwargs: dict) -> None:
    """Append one privacy-safe LLM call record for the Live World performance panel.

    The record intentionally contains no prompt, response, credential, or citizen text.
    Cache hits are not recorded because they do not consume model inference.
    """
    try:
        runtime = get_project_root() / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        event = {
            "unix": round(time.time(), 3),
            "model": str(model or "unknown"),
            "tier": _right_sizing_tier(model),
            "latency_ms": round(max(0.0, float(latency_ms)), 1),
            "success": bool(success),
            "model_type": str(call_kwargs.get("model_type") or ""),
            "nth_generation": int(call_kwargs.get("nth_generation", 0) or 0),
        }
        path = runtime / "right_sizing_requests.jsonl"
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\\n"
        with _right_sizing_telemetry_lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
    except Exception:
        # Observability must never interrupt the simulation.
        pass
# AGENTOPIA_RIGHT_SIZING_TELEMETRY_END


def cached(func):
    def wrapper(*args, **kwargs):
        force_regenerate = kwargs.pop("force_regenerate", False)
        key = _canonical_key(func.__name__, args, kwargs)

        # Resolve paths
        cp_orig = _get_cache_base_path(kwargs.get("cache_file"))
        shard_path = _get_thread_cache_file(str(cp_orig))
        cache_name = Path(cp_orig).name  # e.g. ".cache.pkl", ".cache_agent=Alice.pkl"

        # Ensure shared cache loaded (from main llm_cache/ dir, once)
        shared = _ensure_shared_cache(cache_name)

        # Get/create delta for current thread
        delta = _get_or_create_delta(cache_name, shard_path)

        # === Three-tier lookup ===
        if not force_regenerate and cache_sign:
            # 1. Own delta (thread-local new entries)
            if key in delta:
                val = delta[key]
                if val is not None and val not in ("", _ERROR_RESPONSE):
                    print("cache hit")
                    _log_to_world_logger("cache hit")
                    return val

            # 2. Main thread delta (god calls made before workers started)
            tid = threading.current_thread().ident
            if tid != threading.main_thread().ident:
                main_delta = _main_thread_delta.get(cache_name)
                if main_delta is not None and key in main_delta:
                    val = main_delta[key]
                    if val is not None and val not in ("", _ERROR_RESPONSE):
                        print("cache hit")
                        _log_to_world_logger("cache hit")
                        return val

            # 3. Shared cache (loaded from disk once)
            if key in shared:
                val = shared[key]
                if val is not None and val not in ("", _ERROR_RESPONSE):
                    print("cache hit")
                    _log_to_world_logger("cache hit")
                    return val

        # Cache miss or force_regenerate
        if force_regenerate:
            print("cache force_regenerate")
            _log_to_world_logger("cache force_regenerate")
        else:
            print("cache miss")
            _log_to_world_logger("cache miss")
            global _cache_miss_count
            if _cache_miss_count < 5:
                with _cache_miss_lock:
                    if _cache_miss_count < 5:
                        _cache_miss_count += 1
                        key_str = f"[SAMPLE CACHE MISS] key:\n{repr(key)}"
                        print(key_str)
                        _log_to_world_logger(key_str)

        telemetry_started = time.monotonic() if func.__name__ == "generate_with_fc" else None
        try:
            result = func(*args, **kwargs)
        except Exception:
            if telemetry_started is not None:
                model = kwargs.get("model") or (args[0] if args else "unknown")
                _record_right_sizing_request(model, (time.monotonic() - telemetry_started) * 1000.0, False, kwargs)
            raise
        if telemetry_started is not None:
            model = kwargs.get("model") or (args[0] if args else "unknown")
            success = result is not None and result not in ("", _ERROR_RESPONSE)
            _record_right_sizing_request(model, (time.monotonic() - telemetry_started) * 1000.0, success, kwargs)
        if result is not None:
            delta[key] = result
            # Batch flush: write delta to shard every _FLUSH_EVERY_N misses
            dirty = getattr(_tls, "dirty_count", None)
            if dirty is None:
                dirty = {}
                _tls.dirty_count = dirty
            dirty[cache_name] = dirty.get(cache_name, 0) + 1
            if dirty[cache_name] >= _FLUSH_EVERY_N:
                _flush_delta(cache_name, shard_path, delta)
                dirty[cache_name] = 0
        return result

    return wrapper


def _is_transient_error(error_str: str) -> bool:
    """Check if error is transient (connection/timeout/server error) and worth retrying."""
    error_lower = error_str.lower()
    return (
        # HTTP 5xx errors
        "500" in error_str
        or "502" in error_str
        or "503" in error_str
        or "internal server error" in error_lower
        # Connection errors
        or "connection" in error_lower  # connect, connection, disconnect
        or "upstream" in error_lower  # upstream connect error
        or "refused" in error_lower  # Connection refused
        or "reset" in error_lower  # connection reset
        # Timeout errors
        or "timeout" in error_lower
        # vLLM model not loaded on some workers (transient 400)
        or "model doesn't exist in cache" in error_lower
        or "timed out" in error_lower
        # Other transient errors
        or "failed to route" in error_lower
        or "ab testing" in error_lower
        or "temporarily" in error_lower
        or "overloaded" in error_lower
        or "rate limit" in error_lower
    )


def num_tokens_from_string(string: str, encoding_name: str = "cl100k_base") -> int:
    """Safe token estimator; falls back when tiktoken is unavailable/offline."""
    try:
        encoding = tiktoken.get_encoding(encoding_name)
        num_tokens = len(encoding.encode(string, disallowed_special=()))
        return num_tokens
    except Exception:
        # offline or tiktoken unavailable; rough estimate ~4 chars per token
        return max(1, len(string) // 4)


def get_response_mock(*, messages=None, prompt=None, **kwargs):
    """Mock LLM: return a short deterministic string based on the prompt.

    Rules:
    - Use the last message content when `messages` is provided; otherwise use `prompt`.
    - Return format: "[Result of <first 50 chars>]" (newlines collapsed).
    """
    text = ""
    try:
        if messages and isinstance(messages, list) and len(messages) > 0:
            text = messages[-1].get("content", "")
        elif isinstance(prompt, str):
            text = prompt
    except Exception:
        text = ""

    snippet = (text or "")[:50].replace("\n", " ")
    return f"[Result of {snippet}]"


# ---------------------------------------------------------------------------
# Closed-source model helpers (no thinking/reasoning)
# ---------------------------------------------------------------------------


def _normalize_openai_chat_msg(msg) -> list:
    """Convert OpenAI chat completion message to normalized output format."""
    content = msg.content or ""
    if msg.tool_calls:
        return [
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": t.id,
                        "type": "function",
                        "function": {
                            "name": t.function.name,
                            "arguments": json.dumps(
                                json.loads(t.function.arguments),
                                ensure_ascii=False,
                            ),
                        },
                    }
                    for t in msg.tool_calls
                ],
            }
        ]
    return [{"role": "assistant", "content": content}]


def _call_openai_chat(model, messages, functions, tool_choice, max_tokens, **kwargs):
    """GPT-5-mini etc. via OpenAI-compatible chat completions endpoint."""
    from openai import OpenAI

    model_config = config["models"][model]
    base_url = model_config["url"].rstrip("/") + "/"
    api_key = model_config["api_key"]
    client = OpenAI(base_url=base_url, api_key=api_key)
    client = client.with_options(timeout=kwargs.pop("timeout", 600))

    actual_model = model_config.get("vllm_model_name", model)

    chat_kwargs = {
        "model": actual_model,
        "messages": messages,
        "max_completion_tokens": int(max_tokens),
    }

    # Reasoning models: set effort level to reduce token consumption
    reasoning_effort = model_config.get("reasoning_effort")
    if reasoning_effort:
        chat_kwargs["reasoning_effort"] = reasoning_effort

    if functions and tool_choice != "none":
        # OpenAI strict mode requires 'required' to list all properties
        patched = copy.deepcopy(functions)
        for f in patched:
            params = f.get("parameters", {})
            props = params.get("properties", {})
            if props:
                params["required"] = list(props.keys())
        chat_kwargs["tools"] = [{"type": "function", "function": t} for t in patched]
        if isinstance(tool_choice, dict):
            chat_kwargs["tool_choice"] = tool_choice

    chat_kwargs = _agentopia_rc2_context_guard_v31(chat_kwargs)
    response = client.chat.completions.create(**chat_kwargs)
    msg = response.choices[0].message
    return _normalize_openai_chat_msg(msg)


def _call_azure_responses(
    model, messages, functions, tool_choice, max_tokens, **kwargs
):
    """GPT-5 via Azure OpenAI Responses API."""
    model_config = config["models"][model]
    client = openai.AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY", model_config["api_key"]),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", model_config["url"]),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", model_config["api_version"]),
        timeout=180,
    )

    reasoning = {"effort": kwargs.pop("effort", "medium")}

    response = client.responses.create(
        model=model,
        input=messages,
        tools=functions,
        tool_choice=tool_choice,
        reasoning=reasoning,
        max_output_tokens=int(max_tokens),
        timeout=kwargs.pop("timeout", 600),
    )
    return response.output


# Provider detection for closed-source models
_CLOSED_SOURCE_PROVIDERS = {
    "gpt-5-mini": "openai",
    "gpt-5": "azure-responses",
}


def _is_closed_source_model(model: str) -> bool:
    """Return True if model is a closed-source model (no thinking/reasoning)."""
    if model in _CLOSED_SOURCE_PROVIDERS:
        return True
    if model.startswith("claude") or model.startswith("gemini"):
        return True
    return False


@cached

# AGENTOPIA_RC2_CONTEXT_GUARD_V31
def _agentopia_rc2_trim_text_v31(text, limit):
    if not isinstance(text, str) or len(text) <= limit:
        return text
    if limit < 1200:
        return text[:limit]
    marker = "\n...[AGENTOPIA CONTEXT COMPACTED FOR 16K WINDOW]...\n"
    usable = max(0, limit - len(marker))
    head = int(usable * 0.62)
    tail = usable - head
    return text[:head] + marker + text[-tail:]


def _agentopia_rc2_context_guard_v31(chat_kwargs):
    # Conservative guard for local 16K llama.cpp models.
    try:
        kw = dict(chat_kwargs)
        messages = list(kw.get("messages") or [])
        if not messages:
            return kw

        extras = 0
        for k in ("tools", "functions", "response_format"):
            if k in kw:
                extras += len(str(kw.get(k)))

        # ~38K English chars generally stays well below 16K tokens and
        # leaves room for schemas and response generation.
        target = max(3000, 12000 - min(extras, 9000))

        copied = []
        total = 0
        for m in messages:
            if isinstance(m, dict):
                mm = dict(m)
                c = mm.get("content")
                if isinstance(c, str):
                    total += len(c)
                copied.append(mm)
            else:
                copied.append(m)

        if total <= target:
            kw["messages"] = copied
            return kw

        # Compact oldest non-system turns first.
        for i in range(1, max(1, len(copied) - 1)):
            if total <= target:
                break
            m = copied[i]
            if not isinstance(m, dict):
                continue
            if str(m.get("role") or "").lower() == "system":
                continue
            c = m.get("content")
            if not isinstance(c, str) or len(c) < 1800:
                continue
            new = _agentopia_rc2_trim_text_v31(c, 900)
            total -= len(c) - len(new)
            m["content"] = new

        # Then compact the longest remaining message(s), preserving head/tail.
        while total > target:
            candidates = []
            for i, m in enumerate(copied):
                if isinstance(m, dict) and isinstance(m.get("content"), str):
                    candidates.append((len(m["content"]), i))
            if not candidates:
                break
            candidates.sort(reverse=True)
            size, i = candidates[0]
            if size <= 2200:
                break
            excess = total - target
            new_limit = max(2200, size - max(excess, 1600))
            old = copied[i]["content"]
            new = _agentopia_rc2_trim_text_v31(old, new_limit)
            if len(new) >= len(old):
                break
            copied[i]["content"] = new
            total -= len(old) - len(new)

        print(
            f"[CONTEXT_GUARD_V32] compacted messages to {total} chars "
            f"(target={target}, schema_chars={extras})",
            flush=True,
        )
        kw["messages"] = copied
        return kw
    except Exception as exc:
        print(f"[CONTEXT_GUARD_V32] fail-open: {exc}", flush=True)
        return chat_kwargs

def generate_with_fc(
    model: str,
    messages: list,
    functions: list = [],
    tool_choice: str = "auto",
    nth_generation=0,
    **kwargs,
):
    """Responses API call with OpenAI function tools.

    - In mock mode, returns a minimal dict with generated content.
    - Otherwise returns the SDK `Response` object from client.responses.create.
    """

    def _check_output(output):
        """Sanity check: last message should be assistant with content (unless tool_calls)."""
        if not output:
            logger.error("[generate_with_fc] output is empty")
            return
        last = output[-1]
        if last.get("role") != "assistant":
            logger.error(
                f"[generate_with_fc] output[-1] role is not assistant, got {last.get('role')}"
            )
        # Only check content if no tool_calls (tool_calls can have empty content)
        # Note: .get("content", "") returns None if key exists with None value
        content = last.get("content") or ""
        if not last.get("tool_calls") and not content.strip():
            logger.error("[generate_with_fc] output[-1] content is empty")

    def _normalize_output(output):
        """Strip leading/trailing whitespace from assistant content to ensure cache consistency.

        LLM outputs may have inconsistent whitespace (e.g., leading \\n\\n),
        causing cache conflicts for semantically identical responses.
        """
        for msg in output:
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str):
                msg["content"] = msg["content"].strip()
        return output

    # Some models (e.g. Qwen) require at least one user message
    model_cfg = config.get("models", {}).get(model, {})
    if model_cfg.get("require_user_message", False) or model.lower().startswith("qwen"):
        has_user = any(m.get("role") == "user" for m in messages)
        if not has_user:
            # Convert the last system message to user
            messages = [
                {**m, "role": "user"}
                if i == len(messages) - 1 and m.get("role") == "system"
                else m
                for i, m in enumerate(messages)
            ]

    # Debug: log the model used on each call
    if nth_generation == 0:
        logger.info(
            f"[LLM_CALL] model={model}, num_messages={len(messages)}, has_functions={len(functions) > 0}"
        )

    response = None
    try:
        # OpenAI-compatible endpoint (vLLM, local servers, etc.)
        # Matches any model configured with a "url" field that isn't a closed-source provider
        if "url" in model_cfg and model not in _CLOSED_SOURCE_PROVIDERS:
            from openai import OpenAI

            # Allow environment variables to override URL and API key
            base_url = os.getenv("OPENAI_BASE_URL", model_cfg["url"])
            api_key = os.getenv("OPENAI_API_KEY", model_cfg["api_key"])
            client = OpenAI(base_url=base_url, api_key=api_key)

            # Set per-request timeout on the client instance
            req_timeout = kwargs.pop("timeout", 90)  # AGENTOPIA_ACTIVITY_RESILIENCE_V1744
            try:
                req_timeout = min(float(req_timeout), 90.0)
            except (TypeError, ValueError):
                req_timeout = 90.0
            client = client.with_options(timeout=req_timeout)

            max_output_tokens = _get_max_tokens_for_model(model, kwargs)

            reasoning = {
                "effort": kwargs.pop(
                    "effort", "medium"
                ),  # low, medium, high: control reasoning token num
            }

            if _USE_CHAT_COMPLETIONS:
                # Normalize tools for OpenAI-compatible servers
                tool_defs = (
                    [{"type": "function", "function": t} for t in functions]
                    if functions
                    else []
                )
                use_tools = bool(tool_defs) and tool_choice != "none"

                requested_max_tokens = int(kwargs.pop("max_tokens", max_output_tokens))
                context_length = model_cfg.get("context_length", 32768)

                extra_body = {"repetition_penalty": 1.05}
                # Models that support thinking mode via chat_template_kwargs
                if model_cfg.get("enable_thinking", False):
                    extra_body["chat_template_kwargs"] = {"enable_thinking": True}

                chat_kwargs = {
                    "model": model_cfg.get("vllm_model_name", model),
                    "messages": messages,
                    "max_tokens": requested_max_tokens,
                    "temperature": config.get("temperature", 0.7),
                    "extra_body": extra_body,
                }
                if use_tools:
                    chat_kwargs["tools"] = tool_defs
                    # Only pass tool_choice when it's an explicit dict targetting a function
                    if isinstance(tool_choice, dict):
                        chat_kwargs["tool_choice"] = tool_choice

                try:
                    chat_kwargs = _agentopia_rc2_context_guard_v31(chat_kwargs)
                    response = client.chat.completions.create(**chat_kwargs)
                except Exception as e:
                    error_str = str(e)
                    # Log connection errors with model info for debugging
                    if "Connection error" in error_str or "disconnected" in error_str:
                        logger.error(
                            f"[LLM] Connection error for model '{model}': {error_str[:200]}"
                        )
                    # Handle max_tokens too large error by parsing actual input tokens
                    # Format 1: "has 16500 input tokens" (vLLM style)
                    # Format 2: "You passed 57345 input tokens" (OpenAI style)
                    if ("max_tokens" in error_str and "too large" in error_str) or (
                        "input tokens" in error_str and "context length" in error_str
                    ):
                        import re

                        # Try multiple patterns
                        match = re.search(r"has (\d+) input tokens", error_str)
                        if not match:
                            match = re.search(r"passed (\d+) input tokens", error_str)
                        if match:
                            actual_input_tokens = int(match.group(1))
                            token_buffer = 500
                            adjusted_max = (
                                context_length - actual_input_tokens - token_buffer
                            )
                            if adjusted_max >= 1024:
                                logger.warning(
                                    "[LLM] max_tokens adjusted: %d -> %d (input=%d, context=%d)",
                                    requested_max_tokens,
                                    adjusted_max,
                                    actual_input_tokens,
                                    context_length,
                                )
                                chat_kwargs["max_tokens"] = adjusted_max
                                chat_kwargs = _agentopia_rc2_context_guard_v31(chat_kwargs)
                                response = client.chat.completions.create(**chat_kwargs)
                            else:
                                raise ValueError(
                                    f"Input too long: {actual_input_tokens} tokens, "
                                    f"only {adjusted_max} tokens left for output"
                                )
                        else:
                            raise
                    # If server 5xx, connection error, or timeout (transient failure), retry with backoff
                    elif _is_transient_error(error_str):
                        import time
                        import random

                        base_delay = 2
                        max_delay = 300  # max wait per attempt: 5 minutes
                        max_total_wait = 3600  # total wait ceiling: 1 hour
                        max_total_wait = min(float(max_total_wait), 45.0)  # v1.7.4.4 transient retry ceiling

                        logger.warning(
                            f"[LLM] Connection/timeout error detected for model '{model}'. "
                            f"Will retry with exponential backoff (max {max_total_wait}s). "
                            f"Error: {error_str[:150]}"
                        )

                        elapsed = 0
                        delay = base_delay
                        attempt = 0

                        while elapsed < max_total_wait:
                            attempt += 1
                            wait_time = min(delay, max_delay)
                            # jitter ±25%
                            jitter = wait_time * 0.25 * (random.random() * 2 - 1)
                            wait_time = wait_time + jitter

                            logger.warning(
                                f"[LLM] Retry #{attempt}: waiting {wait_time:.0f}s "
                                f"(total elapsed {elapsed:.0f}s/{max_total_wait}s)"
                            )
                            time.sleep(wait_time)
                            elapsed += wait_time

                            try:
                                chat_kwargs = _agentopia_rc2_context_guard_v31(chat_kwargs)
                                response = client.chat.completions.create(**chat_kwargs)
                                break
                            except Exception as retry_e:
                                error_str = str(retry_e)
                                if not _is_transient_error(error_str):
                                    # No longer a transient error — let the outer handler deal with it
                                    raise retry_e
                                delay *= 2  # exponential backoff
                        else:
                            # while loop exited normally (timeout) — re-raise the last error
                            raise
                    else:
                        raise

                msg = response.choices[0].message

                # Qwen3 (pre-3.5): use the original stable path
                model_lower = model.lower()
                if (
                    model_lower.startswith("qwen")
                    and "qwen3.5" not in model_lower
                    and "qwen35" not in model_lower
                ):
                    if model.lower().endswith("thinking"):
                        msg.content = "<think>" + msg.content
                    result = [msg.to_dict()]
                    _check_output(result)
                    return _normalize_output(result)

                # Qwen3.5+ and other models: handle reasoning/reasoning_content fields
                reasoning_text = getattr(msg, "reasoning", None) or getattr(
                    msg, "reasoning_content", None
                )

                # Check finish_reason == "length" or output too long: likely repetitive generation
                # Only checked for role model; god model output can legitimately be longer
                finish_reason = response.choices[0].finish_reason
                is_role_model = kwargs.get("model_type") == "role"

                if is_role_model:
                    output_text = (reasoning_text or "") + (msg.content or "")
                    output_tokens = num_tokens_from_string(output_text)
                    # Threshold: max_tokens * 0.75 (accounts for tokenizer differences)
                    max_tokens_threshold = requested_max_tokens * 0.75
                    is_truncated = finish_reason == "length"
                    is_too_long = output_tokens > max_tokens_threshold

                    if is_truncated or is_too_long:
                        reason = "truncated" if is_truncated else "too_long"
                        logger.warning(
                            f"[LLM] Repetitive generation detected: {reason}, "
                            f"output_tokens={output_tokens}, threshold={max_tokens_threshold:.0f}"
                        )
                        raise RuntimeError(f"REPETITIVE_GENERATION: {reason}")

                has_content = msg.content and msg.content.strip()
                has_tool_calls = msg.tool_calls and len(msg.tool_calls) > 0
                if reasoning_text and not has_content and not has_tool_calls:
                    logger.warning(
                        "msg has reasoning but no content/tool_calls — "
                        f"model={model}, nth_generation={nth_generation}, "
                        f"finish_reason={finish_reason}"
                    )

                # Format reasoning (ensure <think> tags) and prepend to content
                content = msg.content or ""
                content = content.strip()

                # Some models may return residual thinking text + </think> tag in content — strip it
                if "</think>" in content:
                    parts = content.split("</think>", 1)
                    residual_thinking = parts[0].strip()
                    content = parts[1].strip()
                    # Merge residual thinking into reasoning_text
                    if residual_thinking:
                        if reasoning_text:
                            reasoning_text = (
                                reasoning_text.rstrip() + "\n" + residual_thinking
                            )
                        else:
                            reasoning_text = residual_thinking
                if reasoning_text:
                    text = reasoning_text.strip()
                    if not text.startswith("<think>"):
                        text = f"<think>\n{text}"
                    if not text.endswith("</think>"):
                        text = f"{text}\n</think>"
                    content = f"{text}\n\n{content}"

                output = []
                if msg.tool_calls:
                    try:
                        output.append(
                            {
                                "role": "assistant",
                                "content": content,
                                "tool_calls": [
                                    {
                                        "id": t.id,
                                        "type": "function",
                                        "function": {
                                            "name": t.function.name,
                                            "arguments": json.dumps(
                                                json.loads(t.function.arguments),
                                                ensure_ascii=False,
                                            ),
                                        },
                                    }
                                    for t in msg.tool_calls
                                ],
                            }
                        )
                    except Exception as e:
                        logger.warning("failed to normalize tool_calls: %s", e)
                else:
                    output.append({"role": "assistant", "content": content})

                _check_output(output)
                return _normalize_output(output)
            else:
                raise NotImplementedError(
                    f"Either _USE_CHAT_COMPLETIONS or _USE_RESPONSES_API must be True"
                )

        elif model in _CLOSED_SOURCE_PROVIDERS:
            # GPT closed-source models: no thinking/reasoning
            max_out = _get_max_tokens_for_model(model, kwargs)
            dispatch = {
                "openai": _call_openai_chat,
                "azure-responses": _call_azure_responses,
            }
            provider = _CLOSED_SOURCE_PROVIDERS[model]
            output = dispatch[provider](
                model, messages, functions, tool_choice, max_out, **kwargs
            )
            _check_output(output)
            return _normalize_output(output)

        elif model.startswith("claude"):
            logger.info(f"[CLAUDE_CALL] Entering Claude API branch for model={model}")
            from anthropic import Anthropic

            # 1. Initialize client
            api_key = os.getenv("ANTHROPIC_API_KEY", model_cfg["api_key"])
            client = Anthropic(api_key=api_key)
            logger.info(f"[CLAUDE_CALL] Anthropic client initialized")

            # 2. Extract and remove system messages
            system_messages = [
                msg["content"] for msg in messages if msg.get("role") == "system"
            ]
            system_prompt = "\n\n".join(system_messages) if system_messages else None
            claude_messages = [msg for msg in messages if msg.get("role") != "system"]

            # 3. Convert tool_calls / tool results format
            claude_messages = _convert_messages_for_claude(claude_messages)

            # If messages are empty after filtering, use system_prompt as a user message
            if not claude_messages and system_prompt:
                claude_messages = [{"role": "user", "content": system_prompt}]
                system_prompt = None

            # 4. Convert tool definitions
            claude_tools = None
            if functions and tool_choice != "none":
                claude_tools = _convert_tools_for_claude(functions)

            # 5. Call Claude API
            max_tokens = _get_max_tokens_for_model(model, kwargs)

            api_kwargs = {
                "model": model_cfg.get("anthropic_model_name", model),
                "max_tokens": max_tokens,
                "messages": claude_messages,
                "temperature": config.get("temperature", 0.7),
            }
            if system_prompt:
                api_kwargs["system"] = system_prompt
            if claude_tools:
                api_kwargs["tools"] = claude_tools

            logger.info(
                f"[CLAUDE_CALL] Calling Claude API with model={api_kwargs['model']}, max_tokens={max_tokens}, num_messages={len(claude_messages)}, has_tools={claude_tools is not None}"
            )
            response = client.messages.create(**api_kwargs)
            logger.info(
                f"[CLAUDE_CALL] Claude API response received, stop_reason={response.stop_reason}"
            )

            # 6. Normalize response to OpenAI format
            normalized = _normalize_claude_response(response)
            logger.info(
                f"[CLAUDE_CALL] Response normalized, returning {len(normalized)} messages"
            )
            _check_output(normalized)
            return _normalize_output(normalized)

        elif model.startswith("gemini"):
            logger.info(f"[GEMINI_CALL] Entering Gemini API branch for model={model}")
            from google import genai
            from google.oauth2 import service_account
            from google.genai import types

            # 1. Load credentials
            credentials_file = model_cfg["credentials_file"]
            # Support relative paths (relative to project root)
            if not os.path.isabs(credentials_file):
                credentials_file = str(project_root / credentials_file)

            credentials = service_account.Credentials.from_service_account_file(
                filename=credentials_file,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )

            client = genai.Client(
                vertexai=True,
                project=model_cfg["project"],
                location=model_cfg["location"],
                credentials=credentials,
            )

            # 2. Convert message format
            # Gemini only accepts user/model roles and requires alternating turns
            sys_inst = []
            content_list = []
            for m in messages:
                role, text = m["role"], m.get("content", "")
                if role == "system":
                    sys_inst.append(text)
                    continue
                # tool responses go under the user role
                if role == "tool":
                    gemini_role = "user"
                    # Wrap tool result so the model can understand it
                    tool_call_id = m.get("tool_call_id", "unknown")
                    text = f"[Tool Result for {tool_call_id}]: {text}"
                elif role in ["assistant", "model"]:
                    gemini_role = "model"
                else:
                    gemini_role = "user"

                # Gemini requires alternating roles — merge consecutive same-role messages
                if content_list and content_list[-1].role == gemini_role:
                    # Append to the previous message
                    content_list[-1].parts.append(types.Part.from_text(text=text))
                else:
                    content_list.append(
                        types.Content(
                            role=gemini_role,
                            parts=[types.Part.from_text(text=text)],
                        )
                    )

            system_instruction = "\n".join(sys_inst) if sys_inst else None

            # Gemini requires at least one user/model message
            if not content_list:
                # If only a system message exists, convert it to a user message
                if system_instruction:
                    content_list.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=system_instruction)],
                        )
                    )
                    system_instruction = None

            # 3. Convert functions to Gemini tool format
            gemini_tools = None
            if functions and tool_choice != "none":
                gemini_func_decls = []
                for func in functions:
                    # Handle both nested and flat formats
                    func_def = func.get("function", func)
                    gemini_func_decls.append(
                        types.FunctionDeclaration(
                            name=func_def["name"],
                            description=func_def.get("description", ""),
                            parameters=func_def.get("parameters", {}),
                        )
                    )
                gemini_tools = [types.Tool(function_declarations=gemini_func_decls)]

            # 4. Build config
            max_output_tokens = _get_max_tokens_for_model(model, kwargs)
            generate_config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=kwargs.get("temperature", config.get("temperature", 0.7)),
                top_p=kwargs.get("top_p", 0.9),
                max_output_tokens=int(max_output_tokens),
                tools=gemini_tools,
            )

            logger.info(
                f"[GEMINI_CALL] Calling Gemini API with model={model}, num_contents={len(content_list)}, has_tools={gemini_tools is not None}"
            )
            response = client.models.generate_content(
                model=model, contents=content_list, config=generate_config
            )
            logger.info(f"[GEMINI_CALL] Gemini API response received")

            # 5. Normalize response to OpenAI format
            output = []
            text_content = ""
            tool_calls = []

            # Gemini may return empty candidates / content / parts
            candidates = response.candidates or []
            if not candidates:
                raise RuntimeError(
                    f"Gemini returned empty candidates for model={model}"
                )
            candidate = candidates[0]
            parts = []
            if candidate.content and candidate.content.parts:
                parts = candidate.content.parts

            for part in parts:
                if hasattr(part, "text") and part.text:
                    text_content += part.text
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        {
                            "id": f"call_{fc.name}_{len(tool_calls)}",
                            "type": "function",
                            "function": {
                                "name": fc.name,
                                "arguments": json.dumps(
                                    dict(fc.args), ensure_ascii=False
                                ),
                            },
                        }
                    )

            if tool_calls:
                output.append(
                    {
                        "role": "assistant",
                        "content": text_content or "",
                        "tool_calls": tool_calls,
                    }
                )
            else:
                output.append({"role": "assistant", "content": text_content})

            # Check for abnormal Gemini finish_reason
            finish_reason = getattr(candidate, "finish_reason", None)
            finish_reason_str = str(finish_reason) if finish_reason else ""
            is_normal_stop = finish_reason_str in ("STOP", "FinishReason.STOP", "1")

            if not is_normal_stop:
                if text_content.strip():
                    # Has text content: discard malformed function call, keep text only
                    logger.warning(
                        f"[GEMINI] {finish_reason_str} but has text "
                        f"(len={len(text_content)}), using text only"
                    )
                    output = [{"role": "assistant", "content": text_content}]
                    tool_calls = []
                else:
                    # No valid content at all: raise so the caller can retry
                    raise RuntimeError(
                        f"Gemini returned {finish_reason_str} with no text content"
                    )

            logger.info(
                f"[GEMINI_CALL] Response normalized, returning {len(output)} messages"
            )
            _check_output(output)
            return _normalize_output(output)

        else:
            raise ValueError(f"Model {model} does not support functions yet")

    except Exception as e:
        import traceback

        logger.error(f"Error in _generate_with_fc: {str(e)} from model {model}")
        traceback.print_exc()

        try:
            if response is not None:
                logger.error(f"Partial/full response: {response}")
            total_tokens = sum(
                num_tokens_from_string(msg.get("content", ""))
                for msg in messages
                if isinstance(msg, dict)
            )
            logger.error(f"Total input tokens: {total_tokens}")
        except:
            pass  # visualization failure should not affect the main error report

        error_str = str(e)
        fallback_model = config.get("fallback_model")

        # Input too long: skip retries and go straight to fallback
        is_input_too_long = (
            "Input too long" in error_str or "context length" in error_str
        )
        if is_input_too_long:
            logger.info(f"Input too long for {model}, skip retry")
            nth_generation = _MAX_GENERATION  # skip retries, jump straight to fallback branch

        # Repetitive generation: retry at most 2 times — same prompt will likely truncate again
        _MAX_REPETITIVE_RETRY = 1
        if (
            "REPETITIVE_GENERATION" in error_str
            and nth_generation >= _MAX_REPETITIVE_RETRY
        ):
            logger.info(
                f"Repetitive generation after {nth_generation} retries, skip to fallback"
            )
            nth_generation = _MAX_GENERATION

        if nth_generation < _MAX_GENERATION:
            return generate_with_fc(
                model=model,
                messages=messages,
                functions=functions,
                tool_choice=tool_choice,
                nth_generation=nth_generation + 1,
                **kwargs,
            )
        else:
            # Max retry reached, try fallback
            if fallback_model and model != fallback_model:
                logger.info(
                    f"Max retry reached with model {model}, switching to {fallback_model}"
                )
                return generate_with_fc(
                    model=fallback_model,
                    messages=messages,
                    functions=functions,
                    tool_choice=tool_choice,
                    nth_generation=0,
                    **kwargs,
                )
            else:
                return _ERROR_RESPONSE


def remove_reasoning_content(messages, model: str = ""):
    if not model:
        # Backward compat: if no model passed, try config (may be str or list)
        role_model = config["role_model"]
        model = role_model if isinstance(role_model, str) else role_model[0]
    if _USE_CHAT_COMPLETIONS:
        if model.startswith("gpt"):
            messages = [msg for msg in messages if not "<think>" in msg["content"]]
        elif model.startswith("qwen"):
            for m in messages:
                m["content"] = m["content"].split("</think>")[-1]
    elif _USE_RESPONSES_API:
        raise NotImplementedError("Responses API is not supported yet")
    else:
        raise NotImplementedError(
            f"Either _USE_CHAT_COMPLETIONS or _USE_RESPONSES_API must be True"
        )

    return messages


def clip_str(s: str, max_len: int = 500) -> str:
    if isinstance(s, str) and len(s) > max_len:
        omit_words = len(s[max_len:])
        return s[:max_len] + f" ... ({omit_words} more chars omitted)"
    else:
        return s


def clip_function_context(messages: List[dict]) -> List[dict]:
    """Condense function-call arguments and tool responses.

    Rules:
    - role=="tool" messages: truncate content to 200 chars, append "..." if exceeded.
    - assistant tool_calls[*].function.arguments:
      * If dict/list: recursively truncate any string value to 200 + "...".
      * If JSON string: json.loads -> trim recursively -> json.dumps with ensure_ascii=False.
      * If plain string (non-JSON): truncate to 200 + "...".
    Returns a deep-copied list without mutating the original input.
    """
    MAX_LEN = 800
    if config["world"].get("language") in ["zh", "cn"]:
        MAX_LEN = MAX_LEN // 4

    def _trim_str(s: str) -> str:
        if isinstance(s, str) and len(s) > MAX_LEN:
            if config["world"].get("language") in ["zh", "cn"]:
                omit_words = len(s[MAX_LEN:])
            else:
                omit_words = len(s[MAX_LEN:].split(" "))

            return s[:MAX_LEN] + f" ... ({omit_words} more words omitted)"
        else:
            return s

    def _trim_values(obj):
        if isinstance(obj, dict):
            return {k: _trim_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_trim_values(v) for v in obj]
        if isinstance(obj, str):
            return _trim_str(obj)
        return obj

    out: List[dict] = []
    for m in messages:
        item = copy.deepcopy(m)

        # Truncate tool response content
        if item.get("role") == "tool":
            content = item.get("content", "")
            item["content"] = _trim_str(content)

        # Truncate function call arguments in assistant tool_calls
        tool_calls = item.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                func = tc.get("function")
                args = func.get("arguments") if isinstance(func, dict) else None
                if func is None:
                    continue

                # dict/list: trim recursively
                parsed = json.loads(args)
                trimmed = _trim_values(parsed)
                func["arguments"] = json.dumps(trimmed, ensure_ascii=False)

        out.append(item)

    return out


def is_gen_finished(response):
    if _USE_CHAT_COMPLETIONS:
        return not any(item.get("tool_calls") is not None for item in response)
    elif _USE_RESPONSES_API:
        return any(item.type == "message" for item in response)
    else:
        raise NotImplementedError(
            f"Either _USE_CHAT_COMPLETIONS or _USE_RESPONSES_API must be True"
        )


def _get_response(model: str, messages, max_tokens=None, **kwargs):
    # nth_generation inside generate_with_fc: used for API exception retries
    out = generate_with_fc(
        model=model,
        messages=messages,
        functions=[],
        tool_choice="none",
        **kwargs,
    )

    # Collapse to text across possible return shapes
    text = out[-1]["content"].split("</think>")[-1].strip()
    logger.info(f"Response: {text}")
    return text


def lang_detect(text):
    import re

    def count_chinese_characters(text):
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        return len(chinese_chars)

    if count_chinese_characters(text) > len(text) * 0.05:
        lang = "zh"
    else:
        lang = "en"
    return lang


USER = "<USER>"


def remove_inner_thoughts(dialogue: str) -> str:
    cleaned_dialogue = re.sub(r"\[.*?\]", "", dialogue)

    cleaned_dialogue = "\n".join(line.strip() for line in cleaned_dialogue.split("\n"))

    cleaned_dialogue = re.sub(r"\n+", "\n", cleaned_dialogue)

    return cleaned_dialogue.strip()


def add_speaker_and_turn(content: str, speaker: str, turn: int) -> str:
    """Ensure the response starts with canonical "[turn: N, person: NAME]".

    - If a header exists (case-insensitive, flexible spaces), rewrite it into the
      canonical form and correct the turn number if needed. Person text is kept
      as-is except trimming surrounding spaces.
    - If no header is present, prepend one using the provided ``speaker`` and ``turn``.
    - Removes any duplicate turn headers that LLM may have generated at the beginning.
    """
    # We only care about the very beginning. Keep logic minimal and explicit.
    if not isinstance(content, str):
        # Be strict per project policy – don't hide bad inputs.
        raise TypeError("content must be str")

    # Accept case-insensitive keywords and flexible inner whitespace.
    # Two patterns: with "person:" and without (LLM sometimes omits it)
    header_with_person = re.compile(
        r"^\[\s*turn\s*:\s*(\d+)\s*,\s*person\s*:\s*([^\]]+?)\s*\]",
        re.MULTILINE | re.IGNORECASE,
    )
    header_without_person = re.compile(
        r"^\[\s*turn\s*:\s*(\d+)\s*,\s*([^\]]+?)\s*\]",
        re.MULTILINE | re.IGNORECASE,
    )

    # Strip all leading turn headers (LLM sometimes generates duplicates)
    body = content
    while True:
        body = body.lstrip()
        m = header_with_person.match(body) or header_without_person.match(body)
        if m:
            body = body[m.end() :]
        else:
            break

    # Prepend canonical header
    return f"[turn: {turn}, person: {speaker}]\n" + body


def load_json(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def get_character_prompt(
    book_name,
    character,
    character_profile,
    background,
    scenario,
    motivation,
    thoughtless=False,
    other_character_profiles=None,
    exclude_plot_summary=False,
    fixed_template=False,
    add_output_example=False,
    add_rag=False,
):
    if thoughtless:
        output_format = "Your output should include **speech** and **action**. Use (your action) for actions, which others can see."
    else:
        output_format = "Your output should include **thought**, **speech**, and **action**. Use [your thought] for thoughts, which others can't see. Use (your action) for actions, which others can see."

        if add_output_example:
            output_format = "Your output should include **thought**, **speech**, and **action**. Use [your thought] for thoughts, which others can't see, e.g. [I'm terrified, but I must appear strong.]. Use (your action) for actions, which others can see, such as (watches silently, trying to control her fear and anger)."

    if other_character_profiles:
        assert isinstance(other_character_profiles, Dict)
        other_character_profiles_str = ""

        decorator = random.choice(
            ["*" * 30 + "\n\n", "*" * 20 + "\n\n", "\n\n", "\n", ""]
        )
        for other_character, profile in other_character_profiles.items():
            if other_character != character:
                other_character_profiles_str += (
                    f"{decorator}{other_character}: {profile}\n\n"
                )
    else:
        other_character_profiles_str = ""

    if fixed_template:
        if motivation:
            motivation = f"===Your Inner Thoughts===\n{motivation}\n\n"
        if other_character_profiles_str:
            other_character_profiles_str = f"===Information about the other Characters===\n{other_character_profiles_str}\n\n"

        system_prompt = f"You are {character} from {book_name}.\n\n==={character}'s Profile===\n{character_profile}\n\n===Current Scenario===\n{scenario}\n\n{other_character_profiles_str}{motivation}\n\n"

        if add_rag:
            system_prompt += (
                "===Relevant Background Information==={retrieved_knowledge}\n\n"
            )

        system_prompt += f"===Requirements===\n{output_format}\n\n"

        return system_prompt

    styles = ["natural"] * 40 + ["="] * 30 + ["#"] * 20 + ["*"] * 10

    templates = {
        "begin": [
            f"You are {character}.",
            f"Play the role of {character}.",
            f"Imagine you are {character}.",
            f"Think, speak, and act like {character}.",
            f"Step into the shoes of {character}.",
            f"Immerse yourself in the character of {character}.",
            f"You are roleplaying as {character}.",
            f"You will be portraying {character}.",
            f"Roleplay as {character}.",
            f"Your role is to be {character}.",
            f"You are {character} from {book_name}.",
            f"Play the role of {character} from {book_name}.",
            f"Imagine you are {character} from {book_name}.",
            f"Think, speak, and act like {character} from {book_name}.",
            f"Step into the shoes of {character} from {book_name}.",
            f"Immerse yourself in the character of {character} from {book_name}.",
            f"You are roleplaying as {character} from {book_name}.",
            f"You will be portraying {character} from {book_name}.",
            f"Roleplay as {character} from {book_name}.",
            f"Your role is to be {character} from {book_name}.",
        ],
        "natural": {
            "character_profile": [
                f"The profile of {character} is as follows:\n{character_profile}",
                f"Here is the profile of {character}:\n{character_profile}",
                f"Your profile is: \n{character_profile}",
                f"Here is some information about {character}:\n{character_profile}",
                f"The background of {character} is as follows:\n{character_profile}",
            ],
            "current_scenario": [
                f"The current scenario is:\n{scenario}",
                f"Current scenario:\n{scenario}",
                f"The situation you are in is:\n{scenario}",
                f"Here is the situation you are in:\n{scenario}",
            ],
            "current_scenario_with_plot_summary": [
                f"The current scenario and its background are:\nBackground: {background}\nCurrently: {scenario}",
                f"Current scenario and the background:\nScenario: {scenario}\nMore Background: {background}",
                f"The situation you are in is:\nStory arc summary: {background}\nCurrent scenario: {scenario}",
                f"Here is the situation you are in:\nSummary of relevant plots: {background}\nScenario: {scenario}",
            ],
            "other_characters_profile": [
                f"Here is the your knowledge about the other characters:\n{other_character_profiles_str}",
                f"Information about other characters:\n{other_character_profiles_str}",
                f"The background of other characters is as follows:\n{other_character_profiles_str}",
            ],
            "thought": [
                f"Your thoughts are:\n{motivation}",
                f"Your thoughts in this situation are:\n{motivation}",
                f"Your inner thoughts are:\n{motivation}",
                f"Your inner monologue is:\n{motivation}",
                f"Your inner thoughts in the scenario are:\n{motivation}",
            ],
            "requirements": [output_format, "" if thoughtless else output_format],
        },
        "=": {
            "decorator": ["==={}===", "=={}==", "={}="],
        },
        "#": {
            "decorator": ["#{}", "# {}", "## {}", "### {}"],
        },
        "*": {
            "decorator": ["**{}**", "*{}*", "***{}***"],
        },
        "pieces": {
            "character_profile": [
                "Character Profile",
                f"The profile of {character}",
                f"{character}'s profile",
            ],
            "current_scenario": [
                "Current Scenario",
                "The situation you are in",
                "Scenario",
            ],
            "plot_summary": [
                "Summary of Relevant Plots",
                "Background",
                "Story Arc",
                "Plot Summary",
            ],
            "thought": [
                f"{character}'s Thought",
                "Your thoughts",
                "Your inner thoughts",
                "Your inner monologue",
            ],
            "other_characters_profile": [
                f"Information about other characters",
                f"The background of other characters",
                f"Other characters' profiles",
            ],
            "requirements": ["Requirements", "Instructions for roleplaying"],
        },
    }

    # Randomly select a style
    current_style = random.choice(styles)

    # Start with a random beginning template
    system_prompt = random.choice(templates["begin"]) + "\n\n"

    # Add decorated sections based on style
    if current_style == "natural":
        # Natural style without decorators
        system_prompt += (
            random.choice(templates["natural"]["character_profile"]) + "\n\n"
        )

        if exclude_plot_summary or random.random() < 0.5:
            system_prompt += (
                random.choice(templates["natural"]["current_scenario"]) + "\n\n"
            )
        else:
            # use Plot Summary in 50% cases
            system_prompt += (
                random.choice(
                    templates["natural"]["current_scenario_with_plot_summary"]
                )
                + "\n\n"
            )

        if other_character_profiles_str:
            system_prompt += (
                random.choice(templates["natural"]["other_characters_profile"]) + "\n\n"
            )

        if motivation:
            system_prompt += random.choice(templates["natural"]["thought"]) + "\n\n"

        if add_rag:
            system_prompt += (
                "Relevant Background Information: \n{retrieved_knowledge}\n\n"
            )

        system_prompt += random.choice(templates["natural"]["requirements"]) + "\n\n"
    else:
        # Styled with decorators
        decorator = random.choice(templates[current_style]["decorator"])

        # Character profile section
        section_title = random.choice(templates["pieces"]["character_profile"])
        system_prompt += decorator.format(section_title) + "\n"
        system_prompt += character_profile + "\n\n"

        if not exclude_plot_summary and random.random() < 0.5:
            # use Plot Summary in 50% cases
            # Plot summary section
            section_title = random.choice(templates["pieces"]["plot_summary"])
            system_prompt += decorator.format(section_title) + "\n"
            system_prompt += background + "\n\n"

        # Current scenario section
        section_title = random.choice(templates["pieces"]["current_scenario"])
        system_prompt += decorator.format(section_title) + "\n"
        system_prompt += f"{scenario}\n\n"

        if other_character_profiles_str:
            section_title = random.choice(
                templates["pieces"]["other_characters_profile"]
            )
            system_prompt += decorator.format(section_title) + "\n"
            system_prompt += other_character_profiles_str + "\n\n"

        # Thought section (if not empty)
        if motivation:
            section_title = random.choice(templates["pieces"]["thought"])
            system_prompt += decorator.format(section_title) + "\n"
            system_prompt += motivation + "\n\n"

        if add_rag:
            section_title = "Relevant Background Information"
            system_prompt += decorator.format(section_title) + "\n"
            system_prompt += "{retrieved_knowledge}" + "\n\n"

        # Requirements section (if not empty)
        requirements = random.choice(templates["natural"]["requirements"])
        if requirements:
            section_title = random.choice(templates["pieces"]["requirements"])
            system_prompt += decorator.format(section_title) + "\n"
            system_prompt += requirements + "\n\n"

    return system_prompt


def get_environment_prompt(major_characters, scenario):
    ENVIRONMENT = "Environment"
    major_characters = [c for c in major_characters if c != ENVIRONMENT]

    model_roles = [
        "an environment model",
        "a world model",
        "a world simulator",
        "an environment simulator",
    ]

    prompt = f"""You are {random.choice(model_roles)} for a role-playing game. Your task is to provide the environmental feedback: Based on the characters' interactions, dialogues, and actions, describe the resulting changes in the environment. This includes:
   - Physical changes in the setting
   - Reactions of background characters or crowds
   - Ambient sounds, weather changes, or atmospheric shifts
   - Any other relevant environmental details

    Your descriptions should be vivid and help set the scene, but avoid dictating the actions or dialogue of the main characters (including {major_characters}).

    Important notes:
    - You may include actions and reactions of minor characters or crowds, as long as they're not main characters (including {major_characters}).
    - Keep your environmental descriptions concise but impactful, typically 1-3 sentences.
    - Respond to subtle cues in the characters' interactions to create a dynamic, reactive environment.
    - Your output should match the tone, setting, and cultural context of the scenario.

    ===The scenario is as follows===
    {scenario}"""

    return prompt


def get_nsp_prompt(all_characters, scenario):
    ENVIRONMENT = "Environment"

    prompt = f"""Your task is to predict the next speaker for a role-playing game. That is, you need to determine which character (or the {ENVIRONMENT}) might act next based on their previous interactions. The {ENVIRONMENT} is a special role that provides the environmental feedback. Choose a name from this list: {all_characters}. If it's unclear who should act next, output "random". If you believe the scene or conversation should conclude, output "<END CHAT>".

    ===The scenario is as follows===
    {scenario}"""

    return prompt


from typing import Dict


def print_conversation_to_file(conversation_data: Dict, file_path: str):
    """
    Write the scenario, actor prompt, user prompt, and the formatted conversation to a file.
    :param conversation_data: The dictionary containing scene details, actor prompt, user prompt, and conversation entries.
    :param file_path: The path to the file where the output will be written.
    """
    # Extract components from the conversation data
    scene = conversation_data["scene"]
    actor_prompt = conversation_data.get("actor_prompt", "N/A")
    user_prompt = conversation_data.get("user_prompt", "N/A")
    conversation = conversation_data["conversation"]

    with open(file_path, "a", encoding="utf-8") as file:
        file.write("\n=== Scene Description ===\n")
        file.write(f"Scenario: {scene['scenario']}\n")

        file.write("\n=== Actor Prompt ===\n")
        file.write(f"{actor_prompt}\n")

        file.write("\n=== User Prompt ===\n")
        file.write(f"{user_prompt}\n")

        file.write("\n=== Conversation ===\n")
        for turn in conversation:
            from_ = turn["from"]
            file.write(f"\n=== {from_} ===\n")
            message = turn["message"]
            file.write(f"{message}\n\n")

    return


def parse_discard_list(
    response: str,
    possession_names: List[str],
    min_discard: int,
) -> tuple[List[str], List[str], List[str]]:
    """Parse LLM response for discard list, validate and supplement if needed.

    Args:
        response: LLM output (may contain code block)
        possession_names: List of valid item names
        min_discard: Minimum number of items to discard

    Returns:
        (valid_discard_names, invalid_names, randomly_added)
    """
    import hashlib
    import random

    # Extract from code block if present
    if "```" in response:
        match = re.search(r"```\n?(.*?)\n?```", response, re.DOTALL)
        if match:
            response = match.group(1)

    # Parse line by line
    parsed_names = [
        line.strip() for line in response.strip().split("\n") if line.strip()
    ]

    # Split into valid and invalid
    valid_discard_names = [name for name in parsed_names if name in possession_names]
    invalid_names = [name for name in parsed_names if name not in possession_names]

    # Supplement if shortage
    randomly_added: List[str] = []
    shortage = min_discard - len(valid_discard_names)
    if shortage > 0:
        remaining = [
            name for name in possession_names if name not in valid_discard_names
        ]
        if len(remaining) >= shortage:
            # Deterministic random seed
            payload = "|".join(sorted(possession_names))
            h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
            random.seed(int(h, 16))
            randomly_added = random.sample(remaining, shortage)
            valid_discard_names.extend(randomly_added)

    return valid_discard_names, invalid_names, randomly_added


def extract_json(text, **kwargs):
    def _fix_json(json_response):
        prompt = f"""I will provide you with a JSON string that contains errors, making it unparseable by `json.loads`. The most common issue is the presence of unescaped double quotes inside strings. Your task is to output the corrected JSON string. The JSON string to be corrected is:
    {json_response}
    """

        response = _get_response(
            model=kwargs["model"], messages=[{"role": "user", "content": prompt}]
        )

        logger.info(f"fixed json: {response}")

        return response

    def _extract_json(text):
        # Use regular expressions to find all content within curly braces
        orig_text = text

        text = re.sub(
            r'"([^"\\]*(\\.[^"\\]*)*)"', lambda m: m.group().replace("\n", r"\\n"), text
        )

        # json_objects = re.findall(r'(\{[^{}]*\}|\[[^\[\]]*\])', text, re.DOTALL)

        def parse_json_safely(text):
            try:
                result = json.loads(text)
                return result
            except json.JSONDecodeError:
                results = []
                start = 0
                while start < len(text):
                    try:
                        obj, end = json.JSONDecoder().raw_decode(text[start:])
                        results.append(obj)
                        start += end
                    except json.JSONDecodeError:
                        start += 1

                if results:
                    longest_json = max(results, key=lambda x: len(json.dumps(x)))
                    return longest_json
                else:
                    return None

        extracted_json = parse_json_safely(text)

        if extracted_json:
            return extracted_json
        else:
            logger.error("Error parsing response: %s", orig_text)
            return None

    res = _extract_json(text)

    # Only return dict; other types are treated as parse failure — attempt repair
    if isinstance(res, dict):
        return res
    else:
        fixed_res = _extract_json(_fix_json(text))
        # Only return dict; other types are treated as failure
        if isinstance(fixed_res, dict):
            return fixed_res
        return None


def get_response_with_retry(post_processing_funcs=[], **kwargs):
    """
    Get and process a response from an LLM with retries and error handling.

    This function handles:
    1. Getting responses from the LLM with retries
    2. Processing responses through a pipeline of post-processing functions
    3. Fallback to gemini-3-flash-preview if max_retry exceeded
    4. Final error handling

    Args:
        post_processing_funcs (list): List of functions to process the LLM response, defaults to [extract_json]
        **kwargs: Additional arguments passed to _get_response(), including:
            - messages: List of message dicts for the LLM
            - model: Name of LLM model to use
            - max_retry: Max number of retry attempts (default 5)

    Returns:
        dict: Processed JSON response from the LLM, or error dict if parsing fails
    """
    outer_retry_index = 0
    has_switched_to_fallback_model = False

    while True:
        # When retrying (outer_retry_index >= 1), force regenerate to avoid hitting
        # the previous failed response in cache. The new result will overwrite the
        # cache entry, so future runs will hit the successful response directly.
        response = _get_response(
            **kwargs,
            force_regenerate=outer_retry_index > 0,
        )

        for post_processing_func in post_processing_funcs:
            response = post_processing_func(
                response, nth_generation=outer_retry_index, **kwargs
            )

        if response:
            # pass all postprocessing functions
            return response
        else:
            outer_retry_index += 1
            if outer_retry_index > kwargs.get("max_retry", _MAX_GENERATION):
                current_model = kwargs.get("model")
                fallback_model = config.get("fallback_model")
                # If fallback model hasn't been tried yet and current model isn't it
                if (
                    not has_switched_to_fallback_model
                    and fallback_model
                    and current_model != fallback_model
                ):
                    logger.info(
                        f"Max retry reached with model {current_model}, switching to {fallback_model}"
                    )
                    kwargs["model"] = fallback_model
                    outer_retry_index = max(
                        0, outer_retry_index - 5
                    )  # give the fallback model 3 attempts
                    has_switched_to_fallback_model = True
                    continue
                else:
                    # Fallback model already tried or current model is the fallback — return error
                    return _ERROR_RESPONSE


def get_response(**kwargs):
    # Respect global mock switch
    return get_response_with_retry([], **kwargs)


def get_response_json(**kwargs):
    return get_response_with_retry([extract_json], **kwargs)


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def save_json(data: List[Dict], file_path: str):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ==================== Cache Flush & Shard Merge Functions ====================


def flush_all_caches() -> None:
    """Flush all thread deltas to disk. Call at run end, before merging."""
    # 1. Flush main thread deltas (god calls only write to .cache.pkl)
    for cache_name, delta in _main_thread_delta.items():
        if not delta:
            continue
        if _run_cache_dir is not None:
            shard_path = str(_run_cache_dir / cache_name)
        else:
            shard_path = str(project_root / "llm_cache" / cache_name)
        _flush_delta(cache_name, shard_path, delta)

    # 2. Flush all worker deltas (from global registry)
    with _delta_registry_lock:
        for tid, deltas in _delta_registry.items():
            for cache_name, delta in deltas.items():
                if delta:
                    shard_path = _shard_registry[tid][cache_name]
                    _flush_delta(cache_name, shard_path, delta)

    main_count = sum(1 for d in _main_thread_delta.values() if d)
    worker_count = len(_delta_registry)
    logger.info(
        f"Flushed all caches: {main_count} main deltas, {worker_count} worker threads"
    )


def _merge_worker_caches(base_cache_file: str) -> bool:
    """Merge all worker shard files (*_worker-*.pkl) into base cache file.

    Args:
        base_cache_file: Path to main cache file (e.g. "llm_cache/.cache.pkl")

    Returns:
        True if merge succeeded, False otherwise.

    Side effects:
        - Deletes shard files after successful merge
        - Logs warnings on key conflicts
    """
    base = Path(base_cache_file)
    if not base.parent.exists():
        return True

    cache_dir = base.parent
    pattern = f"{base.stem}_worker-*{base.suffix}"
    # Sort by creation time (earliest first) to preserve first-cached values
    shard_files = sorted(cache_dir.glob(pattern), key=lambda p: p.stat().st_mtime)

    if not shard_files:
        # Show current cache state
        if base.exists():
            try:
                with open(base, "rb") as f:
                    cache = pickle.load(f)
                print(f"  {len(cache)} entries, no shards to merge")
            except Exception as e:
                print(f"  Failed to read: {e}")
        else:
            print(f"  File does not exist")
        return True

    # 1. Load main cache
    main_cache = {}
    key_source: dict[str, str] = {}  # Track which file each key came from
    base_count = 0
    if base.exists():
        try:
            with open(base, "rb") as f:
                main_cache = pickle.load(f)
            base_count = len(main_cache)
            # All existing keys come from base file
            for key in main_cache:
                key_source[key] = base.name
        except Exception as e:
            logger.error(f"Failed to load main cache {base}: {e}")
            return False

    print(f"  Base: {base_count} entries, found {len(shard_files)} shards to merge")

    # 2. Merge each shard
    merged_count = 0
    deleted_shards = []
    total_conflicts = 0
    for shard_file in shard_files:
        try:
            with open(shard_file, "rb") as f:
                shard_cache = pickle.load(f)

            before = len(main_cache)

            # Only add keys that don't already exist (preserve first-cached values)
            new_keys = 0
            skipped_keys = 0
            conflict_keys = []
            for key, value in shard_cache.items():
                if key not in main_cache:
                    main_cache[key] = value
                    key_source[key] = shard_file.name
                    new_keys += 1
                else:
                    skipped_keys += 1
                    # Check if values differ
                    if main_cache[key] != value:
                        conflict_keys.append(
                            (key, main_cache[key], value, key_source[key])
                        )

            if skipped_keys > 0:
                logger.info(
                    f"{shard_file.name}: {skipped_keys} duplicate keys skipped (preserved earlier values)"
                )

            # Print conflicts with prominent formatting
            if conflict_keys:
                total_conflicts += len(conflict_keys)
                print(f"\n{'=' * 60}")
                print(
                    f"⚠️  CONFLICT DETECTED in {shard_file.name}: {len(conflict_keys)} keys have different values"
                )
                print(f"{'=' * 60}")
                for key, existing_val, new_val, existing_source in conflict_keys:
                    print(
                        f"\n🔑 Key: {key[:200]}{'...' if len(str(key)) > 200 else ''}"
                    )
                    print(
                        f"  ├─ Existing value (from {existing_source}): {str(existing_val)[:500]}{'...' if len(str(existing_val)) > 500 else ''}"
                    )
                    print(
                        f"  └─ New value (from {shard_file.name}): {str(new_val)[:500]}{'...' if len(str(new_val)) > 500 else ''}"
                    )
                print(f"{'=' * 60}\n")

            print(
                f"    + {shard_file.name}: {len(shard_cache)} entries (+{new_keys} new, {skipped_keys} skipped)"
            )

            shard_file.unlink()  # Delete shard after successful merge
            deleted_shards.append(shard_file.name)
            merged_count += 1
        except Exception as e:
            logger.error(f"Failed to merge {shard_file}: {e}")

    # 3. Write merged cache
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        with open(base, "wb") as f:
            pickle.dump(main_cache, f)
        print(
            f"  Result: {base_count} -> {len(main_cache)} entries, {len(deleted_shards)} shards deleted"
        )

        if total_conflicts == 0:
            print("  ✅ No cache conflicts detected")

        return merged_count == len(shard_files)
    except Exception as e:
        logger.error(f"Failed to write merged cache {base}: {e}")
        return False


def merge_all_worker_caches() -> None:
    """Merge worker shards for ALL cache files in llm_cache/ directory.

    Scans for main cache files (*.pkl without '_worker-' in name) and merges
    their corresponding worker shards.
    """
    cache_dir = project_root / "llm_cache"
    if not cache_dir.exists():
        print("[info] llm_cache/ directory not found, skipping merge")
        return

    # Find all main cache files (exclude shards with _worker- in stem)
    all_pkl_files = list(cache_dir.glob(".cache*.pkl"))
    main_caches = [f for f in all_pkl_files if "_worker-" not in f.stem]

    if not main_caches:
        print("[info] No main cache files found in llm_cache/")
        return

    print(f"\nMerging cache shards in {cache_dir}/")
    print(f"Found {len(main_caches)} cache files\n")

    for i, main_cache in enumerate(main_caches, 1):
        print(f"[{i}/{len(main_caches)}] {main_cache.name}:")
        _merge_worker_caches(str(main_cache))

    print(f"\nDone.")


def _merge_cache_file(src: Path, dst: Path) -> tuple[int, int]:
    """Merge src cache into dst cache.

    Conflict resolution: dst (earlier) wins over src (later).
    This ensures main cache content is preserved, and earlier runs
    take precedence over later runs.

    Args:
        src: Source cache file (later run, lower priority)
        dst: Destination cache file (main/earlier run, higher priority)

    Returns:
        Tuple of (added_count, skipped_count)
    """
    if not src.exists():
        return 0, 0

    src_cache = _safe_load_pickle(str(src)) or {}
    dst_cache = (_safe_load_pickle(str(dst)) or {}) if dst.exists() else {}

    added = 0
    skipped = 0
    for k, v in src_cache.items():
        if k not in dst_cache:
            dst_cache[k] = v
            added += 1
        else:
            # Conflict: dst (earlier) wins, skip src value
            skipped += 1

    if added > 0:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "wb") as f:
            pickle.dump(dst_cache, f)

    return added, skipped


def merge_run_cache(run_data_dir: str, delete_after: bool = True) -> bool:
    """Merge a run's cache back to main cache.

    Args:
        run_data_dir: Run data directory name (e.g. "schooldays_02282133")
        delete_after: Delete run cache directory after merge

    Returns:
        True if merge succeeded
    """
    import shutil

    run_cache_dir = project_root / "llm_cache" / run_data_dir
    if not run_cache_dir.exists():
        print(f"  Run cache dir not found: {run_cache_dir}")
        return False

    # 1. First merge worker shards within the run directory (including agent shards).
    # Derive base filenames from shard names rather than scanning base files,
    # because agent caches may only have shards and no base file (agents always run in workers).
    base_files_to_merge: set[str] = set()
    for pkl_file in run_cache_dir.glob(".cache*.pkl"):
        if "_worker-" in pkl_file.name:
            # .cache_agent=X_worker-123.pkl  →  .cache_agent=X.pkl
            # .cache_worker-123.pkl          →  .cache.pkl
            stem = pkl_file.stem  # e.g. ".cache_agent=X_worker-123"
            base_stem = stem.rsplit("_worker-", 1)[0]  # e.g. ".cache_agent=X"
            base_name = f"{base_stem}{pkl_file.suffix}"  # e.g. ".cache_agent=X.pkl"
            base_files_to_merge.add(base_name)
        else:
            # Non-shard files also need merging (they may have shards)
            base_files_to_merge.add(pkl_file.name)

    for base_name in sorted(base_files_to_merge):
        base_path = run_cache_dir / base_name
        _merge_worker_caches(str(base_path))

    # 2. Merge run cache into main cache (main cache wins on conflict)
    main_cache_dir = project_root / "llm_cache"
    total_added = 0
    total_skipped = 0
    merged_files = []

    for pkl_file in run_cache_dir.glob(".cache*.pkl"):
        if "_worker-" in pkl_file.name:
            continue  # skip already-processed shards

        main_pkl = main_cache_dir / pkl_file.name
        added, skipped = _merge_cache_file(pkl_file, main_pkl)
        total_added += added
        total_skipped += skipped
        merged_files.append((pkl_file.name, added, skipped))

    for fname, added, skipped in merged_files:
        conflict_info = f", {skipped} conflicts (main wins)" if skipped > 0 else ""
        print(f"    {fname}: +{added} new{conflict_info}")

    # 3. Delete run cache directory
    if delete_after:
        shutil.rmtree(run_cache_dir)
        print(f"  Deleted run cache dir: {run_cache_dir.name}")

    return True


def merge_all_run_caches(delete_after: bool = True, prefix: str = "") -> int:
    """Scan and merge all run cache directories into the main cache.

    Merge order: sorted by directory name (which includes runid timestamp).
    Earlier runs (smaller runid) are merged first, so they take precedence
    over later runs on conflict.

    Args:
        delete_after: Delete run cache directory after merge.
        prefix: Only merge directories whose name starts with this prefix.

    Returns:
        Number of run directories merged.
    """
    main_cache_dir = project_root / "llm_cache"
    if not main_cache_dir.exists():
        print("[info] llm_cache/ directory not found, skipping run cache merge")
        return 0

    merged_count = 0

    # Scan all run cache directories sorted by name (runid is a timestamp, so lexicographic = chronological).
    # Earlier-merged runs take precedence (main cache wins over later runs).
    for run_dir in sorted(main_cache_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        # Skip non-run directories (e.g. .git, __pycache__)
        if run_dir.name.startswith(".") or run_dir.name.startswith("_"):
            continue
        # prefix filter
        if prefix and not run_dir.name.startswith(prefix):
            continue
        # Check for .cache*.pkl files
        if not list(run_dir.glob(".cache*.pkl")):
            continue

        print(f"\n[Run Cache] {run_dir.name}:")
        if merge_run_cache(run_dir.name, delete_after):
            merged_count += 1

    return merged_count


def read_json(file_path: str) -> List[Dict]:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def tokenize_words(text):
    import regex

    pattern = r"\b\w+\b|[\u4e00-\u9fff]|[\u3040-\u309F\u30A0-\u30FF]|\d|[\p{P}\p{S}]"
    tokens = regex.findall(pattern, text)

    tokens_expanded = []
    for token in tokens:
        if re.match(r"[\u4e00-\u9fff]|[\u3040-\u309F\u30A0-\u30FF]", token):
            tokens_expanded.extend(list(token))
        else:
            tokens_expanded.append(token)
    return tokens_expanded


def fix_repeation(response):
    """
    Fix repetitive text patterns in the response by detecting and removing repetitions.

    This function handles three types of repetition detection:
    1. Long letter substrings (100+ characters)
    2. Consecutive repetitions of token sequences
    3. Non-consecutive repetitions of token sequences

    Args:
        response (str): The text response to check for repetitions

    Returns:
        str: The fixed text with repetitions removed if repetitions were found
        False: If no repetitions were detected
    """

    def detect_repetitions(tokens, min_length=5, max_length=30, threshold=0.1):
        """Check for consecutive repetitions of token sequences"""
        total_length = len(tokens)
        repetitions = 0

        # Try different lengths of subsequences
        for length in range(min_length, min(max_length + 1, total_length + 1)):
            for i in range(total_length - length + 1):
                substr = tokens[i : i + length]

                # Check if this subsequence repeats consecutively up to 4 times
                is_repeated = True
                for repeat_idx in range(1, 5):
                    check_pos = i + (repeat_idx * length)

                    if tokens[check_pos : check_pos + length] != substr:
                        is_repeated = False
                        break

                if is_repeated:
                    return tokens[: i + length]  # Return text up to first repetition

        return False

    def detect_repetitions2(tokens, min_length=15, max_length=30, threshold=0.1):
        """Check for non-consecutive repetitions of token sequences"""
        total_length = len(tokens)
        repetitions = 0

        first_repeat_idx = 999999999999999
        first_start_idx = {}

        # Try different lengths of subsequences
        for length in range(min_length, min(max_length + 1, total_length + 1)):
            substr_count = {}

            for i in range(total_length - length + 1):
                substr = tuple(tokens[i : i + length])
                if substr_count.get(substr, 0) > 0:
                    # Found a repeat - check if it's far enough from first occurrence
                    if i - first_start_idx[substr] >= length:
                        first_repeat_idx = min(first_repeat_idx, i)
                else:
                    first_start_idx[substr] = i

                substr_count[substr] = substr_count.get(substr, 0) + 1

            repetitions += sum(count > 1 for count in substr_count.values())

        repetition_rate = repetitions / total_length if total_length else 0

        if first_repeat_idx < 999999999999999:
            return tokens[:first_repeat_idx]  # Return text up to first repetition
        else:
            return False

    def concatenate_tokens(tokens):
        """Reconstruct text from tokens with proper spacing and punctuation"""
        text = ""
        last_type = None

        for token in tokens:
            # Determine token type (CJK, punctuation, or other)
            current_type = (
                "CJK"
                if re.match(r"[\u4e00-\u9fff]|[\u3040-\u309F\u30A0-\u30FF]", token)
                else "Other"
            )
            import string

            if token in string.punctuation:
                current_type = "P"

            # Add space between certain token types
            if last_type in ["Other", "P"] and current_type == "Other":
                text += " " + token
            else:
                text += token

            last_type = current_type

        # Add appropriate ending punctuation based on last character
        if re.match(r"[a-zA-Z0-9]+$", text[-1]):
            text += "."
        if re.match(r"[\u4e00-\u9fff]+$", text[-1]):
            text += "。"
        if re.match(r"[\u3040-\u309F\u30A0-\u30FF]+$", text[-1]):
            text += "。"

        return text

    def find_long_letter_substrings(s):
        """Find substrings of letters that are 100+ characters long"""
        pattern = r"[a-zA-Z]{100,}"
        matches = re.findall(pattern, s)
        return matches

    repeat_sign = False

    # First check for very long letter sequences
    _ = find_long_letter_substrings(response)
    if _:
        for substr in _:
            response = response.replace(substr, substr[:20])
        repeat_sign = True

    # Then check for token sequence repetitions
    tokens = tokenize_words(response)
    _ = detect_repetitions(tokens)
    if _ == False:  # If no consecutive repetitions found
        _ = detect_repetitions2(tokens)  # Check for non-consecutive repetitions

    if _:
        response = concatenate_tokens(_)
        repeat_sign = True

    if repeat_sign:
        return response  # Return fixed text if repetitions were found
    else:
        return False  # Return False if no repetitions detected


from collections import Counter
import math


def validate_persona_format(persona_data):
    """
    Validate and fix persona format, ensuring MBTI dimensions are always >=50.
    Converts <50 values to their opposite dimension with (100-value).

    Args:
        persona_data (dict): The persona data to validate

    Returns:
        dict: The corrected persona data
    """

    def fix_mbti_dimensions(quantitative):
        """Fix MBTI dimensions to ensure they are always >=50"""
        mbti_pairs = [
            ("extraversion", "introversion"),
            ("introversion", "extraversion"),
            ("sensing", "intuition"),
            ("intuition", "sensing"),
            ("thinking", "feeling"),
            ("feeling", "thinking"),
            ("judging", "perceiving"),
            ("perceiving", "judging"),
        ]

        for dim1, dim2 in mbti_pairs:
            if dim1 in quantitative:
                value = quantitative[dim1]
                if value < 50:
                    # Remove the current dimension and add its opposite
                    del quantitative[dim1]
                    quantitative[dim2] = 100 - value
                    logger.info(f"Converted {dim1}={value} to {dim2}={100 - value}")

        return quantitative

    try:
        # Process each profile entry
        if "profile" in persona_data:
            for profile_entry in persona_data["profile"]:
                if (
                    "longterm" in profile_entry
                    and "objective" in profile_entry["longterm"]
                ):
                    objective = profile_entry["longterm"]["objective"]
                    if (
                        "personality_traits" in objective
                        and "quantitative" in objective["personality_traits"]
                    ):
                        objective["personality_traits"]["quantitative"] = (
                            fix_mbti_dimensions(
                                objective["personality_traits"]["quantitative"]
                            )
                        )

        logger.info("Persona format validation completed")
        return persona_data

    except Exception as e:
        logger.error(f"Error validating persona format: {e}")
        return persona_data


def load_and_validate_persona(file_path):
    """
    Load a persona file and validate its format.

    Args:
        file_path (str): Path to the persona JSON file

    Returns:
        dict: The validated persona data
    """
    try:
        persona_data = load_json(file_path)
        return validate_persona_format(persona_data)
    except Exception as e:
        logger.error(f"Error loading persona from {file_path}: {e}")
        return None


def save_validated_persona(persona_data, file_path):
    """
    Validate and save persona data to a file.

    Args:
        persona_data (dict): The persona data to validate and save
        file_path (str): Path where to save the validated persona
    """
    try:
        validated_data = validate_persona_format(persona_data)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(validated_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Validated persona saved to {file_path}")
    except Exception as e:
        logger.error(f"Error saving validated persona to {file_path}: {e}")


def normalize_mbti_dimensions(mbti_dict):
    """
    Normalize MBTI dimensions during simulation runtime to ensure all values are >=50.
    This function is called when persona MBTI values change during simulation.

    Example:
        If extraversion changes from 70 to 40 during simulation,
        this function will convert it to introversion=60

    Args:
        mbti_dict (dict): Dictionary containing MBTI dimensions and their values

    Returns:
        dict: Normalized MBTI dictionary with all values >=50
    """

    # Define MBTI dimension pairs
    mbti_pairs = {
        "extraversion": "introversion",
        "introversion": "extraversion",
        "sensing": "intuition",
        "intuition": "sensing",
        "thinking": "feeling",
        "feeling": "thinking",
        "judging": "perceiving",
        "perceiving": "judging",
    }

    normalized_dict = mbti_dict.copy()
    changes_made = []

    # Check each dimension in the input
    for dimension, value in list(mbti_dict.items()):
        if dimension in mbti_pairs and value < 50:
            opposite_dimension = mbti_pairs[dimension]
            new_value = 100 - value

            # Remove the <50 dimension and add its opposite
            del normalized_dict[dimension]
            normalized_dict[opposite_dimension] = new_value

            changes_made.append(
                f"{dimension}={value} → {opposite_dimension}={new_value}"
            )
            logger.info(
                f"Simulation MBTI normalization: {dimension}={value} → {opposite_dimension}={new_value}"
            )

    if changes_made:
        logger.info(f"MBTI normalization applied: {', '.join(changes_made)}")

    return normalized_dict


def update_persona_mbti_in_simulation(persona_data, new_mbti_values):
    """
    Update persona MBTI values during simulation with automatic normalization.
    This function should be called whenever the simulation updates a character's personality.

    Args:
        persona_data (dict): The current persona data
        new_mbti_values (dict): New MBTI values from simulation (may contain <50 values)

    Returns:
        dict: Updated persona data with normalized MBTI values
    """
    try:
        # Normalize the new MBTI values
        normalized_mbti = normalize_mbti_dimensions(new_mbti_values)

        # Update the persona data with normalized values
        if "profile" in persona_data:
            for profile_entry in persona_data["profile"]:
                if (
                    "longterm" in profile_entry
                    and "objective" in profile_entry["longterm"]
                ):
                    objective = profile_entry["longterm"]["objective"]
                    if (
                        "personality_traits" in objective
                        and "quantitative" in objective["personality_traits"]
                    ):
                        # Update with normalized MBTI values
                        objective["personality_traits"]["quantitative"].update(
                            normalized_mbti
                        )

        logger.info(f"Updated persona MBTI values in simulation: {normalized_mbti}")
        return persona_data

    except Exception as e:
        logger.error(f"Error updating persona MBTI in simulation: {e}")
        return persona_data


def extract_role_action_blocks(text: str) -> List[str]:
    """Extract all <role_action>...</role_action> blocks from text.

    Supports:
    - Whitespace in tags: < role_action>, <role_action >, < /role_action>, etc.
    - Case-insensitive matching: <ROLE_ACTION>, <Role_Action>, etc.

    Args:
        text: Input text containing role_action blocks

    Returns:
        List of block contents (without the tags)
    """
    import re

    return re.findall(
        r"<\s*role_action\s*>(.*?)<\s*/\s*role_action\s*>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )


def parse_kv_args(s: str) -> Dict[str, object]:
    """Parse a function-like "key=value, ..." argument string into a dict.

    Accepts one of:
    - A JSON object string: "{"a": 1, "b": [1,2]}"
    - A comma-separated list of key=value pairs. Values can be JSON or Python
      literals (e.g., lists/dicts with single quotes), or quoted/raw strings.
    """
    import ast

    def _strip_quotes(x: str) -> str:
        if len(x) >= 2 and (
            (x[0] == '"' and x[-1] == '"') or (x[0] == "'" and x[-1] == "'")
        ):
            return x[1:-1]
        return x

    def _looks_like_literal(x: str) -> bool:
        # Heuristic gate to avoid throwing arbitrary text into literal_eval
        x_strip = x.strip()
        if not x_strip:
            return False
        starts = ("[", "{", "(", '"', "'", "-", "+") + tuple(str(d) for d in range(10))
        if x_strip.startswith(starts):
            return True
        lowered = x_strip.lower()
        return lowered in {"true", "false", "null", "none"}

    def _parse_value(val_s: str) -> object:
        # 1) Try strict JSON
        try:
            return json.loads(val_s)
        except Exception:
            pass
        # 2) Try Python literal for common LLM outputs (e.g., ['a','b'], True, None)
        if _looks_like_literal(val_s):
            try:
                return ast.literal_eval(val_s)
            except Exception:
                # fall through to 3
                pass
        # 3) Remove matching outer quotes; else keep raw string
        return _strip_quotes(val_s)

    def _split_top_level_commas(text: str) -> List[str]:
        # Split on commas not inside quotes or brackets; enforce bracket pairing
        parts: List[str] = []
        buf: List[str] = []
        stack: List[str] = []  # holds expected closing brackets
        in_str = False
        str_ch = ""
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if in_str:
                buf.append(ch)
                if ch == str_ch:
                    # closing quote only if not escaped by an odd number of backslashes
                    bs = 0
                    j = i - 1
                    while j >= 0 and text[j] == "\\":
                        bs += 1
                        j -= 1
                    if bs % 2 == 0:
                        in_str = False
                i += 1
                continue
            if ch in ('"', "'"):
                in_str = True
                str_ch = ch
                buf.append(ch)
            elif ch in "[{(":
                buf.append(ch)
                stack.append({"[": "]", "{": "}", "(": ")"}[ch])
            elif ch in "]})":
                if not stack or ch != stack[-1]:
                    raise ValueError("unbalanced or mismatched brackets in args")
                stack.pop()
                buf.append(ch)
            elif ch == "," and not stack:
                parts.append("".join(buf).strip())
                buf = []
            else:
                buf.append(ch)
            i += 1
        if in_str:
            raise ValueError("unclosed string literal in args")
        if stack:
            raise ValueError("unbalanced brackets in args")
        if buf:
            parts.append("".join(buf).strip())
        return parts

    s = s.strip()
    if not s:
        return {}
    # Fast-path: JSON object
    if s.startswith("{") and s.endswith("}"):
        try:
            return json.loads(s)
        except Exception as e:
            raise ValueError(f"bad JSON args: {e}")

    parts = _split_top_level_commas(s)
    out: Dict[str, object] = {}
    for part in parts:
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"expected key=value, got: {part}")
        k, v = part.split("=", 1)
        key_raw = k.strip()
        # remove wrapping quotes from key if any
        key = (
            key_raw[1:-1]
            if len(key_raw) >= 2
            and (
                (key_raw[0] == '"' and key_raw[-1] == '"')
                or (key_raw[0] == "'" and key_raw[-1] == "'")
            )
            else key_raw
        )
        val_s = v.strip()
        out[key] = _parse_value(val_s)
    return out


if __name__ == "__main__":
    # Minimal CLI to run quick, local tests for utils.
    # Adds a functions call example for chat_completion_with_functions and keeps the
    # existing basic completion path. Use --mock to avoid network calls.
    import argparse

    parser = argparse.ArgumentParser(description="utils test harness")
    parser.add_argument(
        "--mock", action="store_true", help="enable mock mode to avoid real LLM calls"
    )
    parser.add_argument(
        "--test",
        choices=["basic", "functions", "both"],
        default="functions",
        help="which test to run",
    )
    parser.add_argument("--model", default="Qwen3.5-397B-A17B", help="model name")
    args = parser.parse_args()

    if args.mock:
        set_mock_mode(True)

    model = args.model

    if args.test in ("functions", "both"):
        # Simple arithmetic function definition; we do not execute the function here, we
        # only test the model's function-calling output schema.
        functions = [
            {
                "type": "function",
                "name": "add",
                "description": "Add two integers a and b and return the sum.",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
            {
                "type": "function",
                "name": "multiply",
                "description": "Multiply two integers a and b and return the product.",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                    "required": ["a", "b"],
                },
            },
        ]

        messages = [
            {
                "role": "system",
                "content": "You are a math assistant that uses tools when helpful.",
            },
            {
                "role": "user",
                "content": "What is 2+2? If you can, call the add tool with a=2 and b=2. What is 4*4? If you can, call the multiply tool with a=4 and b=4. ",
            },
        ]

        print("=== _generate_with_fc ===")
        res = generate_with_fc(model, messages, functions)
        print("content:", res.get("content") if isinstance(res, dict) else res)
        print("function_calls:", res.get("function_calls"))


def _convert_messages_for_claude(messages: list) -> list:
    """Convert OpenAI message format to Claude format.

    Handles:
    - tool_calls (assistant) → tool_use blocks
    - tool role → tool_result blocks
    """
    claude_messages = []

    for msg in messages:
        role = msg.get("role")

        if role in ["user", "assistant"]:
            # Handle assistant tool_calls
            if role == "assistant" and msg.get("tool_calls"):
                content = []
                # If there is text content, add a text block first
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                # Convert tool_calls to tool_use blocks
                for tc in msg["tool_calls"]:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["function"]["name"],
                            "input": json.loads(tc["function"]["arguments"]),
                        }
                    )
                claude_messages.append({"role": "assistant", "content": content})
            else:
                # Plain message
                claude_messages.append(
                    {"role": role, "content": msg.get("content", "")}
                )

        elif role == "tool":
            # OpenAI tool response → Claude tool_result
            # Claude requires tool_result to be inside a user turn
            tool_result = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id"),
                "content": msg.get("content", ""),
            }
            # Append to the previous user message if possible; otherwise create a new one
            if claude_messages and claude_messages[-1]["role"] == "user":
                if isinstance(claude_messages[-1]["content"], str):
                    claude_messages[-1]["content"] = [
                        {"type": "text", "text": claude_messages[-1]["content"]}
                    ]
                claude_messages[-1]["content"].append(tool_result)
            else:
                claude_messages.append({"role": "user", "content": [tool_result]})

    return claude_messages


def _convert_tools_for_claude(functions: list) -> list:
    """Convert OpenAI function schema to Claude tool schema.

    Handles two OpenAI formats:
    1. Nested:  {"type": "function", "function": {"name": "x", "parameters": {...}}}
    2. Flat:    {"type": "function", "name": "x", "parameters": {...}}

    Claude format: {"name": "x", "description": "...", "input_schema": {...}}
    """
    claude_tools = []

    for func in functions:
        # Handle nested format (has a function sub-object)
        if "function" in func:
            func_def = func["function"]
        # Handle flat format (type="function" with name/parameters at the same level)
        elif func.get("type") == "function" and "name" in func:
            func_def = func
        # Handle format with no type field
        else:
            func_def = func

        # Build Claude tool definition
        claude_tool = {
            "name": func_def["name"],
            "description": func_def.get("description", ""),
            "input_schema": func_def.get("parameters", {}),
        }

        # Remove fields unsupported by Claude (deep copy to avoid mutating the original)
        import copy

        claude_tool["input_schema"] = copy.deepcopy(claude_tool["input_schema"])
        if "additionalProperties" in claude_tool["input_schema"]:
            del claude_tool["input_schema"]["additionalProperties"]

        claude_tools.append(claude_tool)

    return claude_tools


def _normalize_claude_response(response) -> list:
    """Normalize a Claude API response to OpenAI format.

    Returns: [{"role": "assistant", "content": "...", "tool_calls": [...]}]
    """
    output = []

    # Extract text and tool calls
    text_content = ""
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            text_content += block.text
        elif block.type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=False),
                    },
                }
            )

    # Build normalized message
    if tool_calls:
        output.append(
            {
                "role": "assistant",
                "content": text_content or "",
                "tool_calls": tool_calls,
            }
        )
    else:
        output.append({"role": "assistant", "content": text_content})

    return output


def calculate_material_from_cost(cost: int) -> int:
    """Calculate material fulfillment gain from consumption cost.

    Formula (diminishing returns):
    - 0-100: every 20 → +1 material (max +5)
    - 100-300: first 100 → +5, then every 40 → +1 (max +10)
    - 300+: capped at +10 material

    Examples:
    - 60 → +3
    - 180 → +7 (5 + 2)
    - 300 → +10 (capped)
    - 1000 → +10 (capped)
    """
    if cost <= 0:
        return 0
    if cost <= 100:
        return min(cost // 20, 5)
    if cost <= 300:
        base = 5
        extra = (cost - 100) // 40
        return min(base + extra, 10)
    return 10  # capped


def pool_size(n: int, divisor: int = 1) -> int:
    """Cap worker count by config's max_concurrency, min 1.

    Args:
        n: Number of tasks to run
        divisor: Divide max_concurrency by this (for nested parallelism).
                 E.g., if 3 outer activities run in parallel, each uses
                 ceil(max_concurrency / 3) workers internally.
    """
    cfg = get_config()
    max_concurrency = int(cfg["max_concurrency"])
    effective_max = max(1, -(-max_concurrency // divisor))  # ceiling division
    return max(1, min(n, effective_max))



# AGENTOPIA_DURABLE_MODEL_GATE_V3
# Bound in-flight per-model top-level LLM calls; never change world concurrency.
# The internal function invokes generate_with_fc recursively during retries:
# bypass reentrant admissions to avoid a self-deadlock.
import functools as _agentopia_gate_functools
import threading as _agentopia_gate_threading
import time as _agentopia_gate_time
_agentopia_gate_limits = {"liquid-social": 32, "liquid-citizen": 32,
                         "liquid-strategy": 6, "cyber-specialist": 6}
_agentopia_gate_locks = {k: _agentopia_gate_threading.BoundedSemaphore(v)
                        for k, v in _agentopia_gate_limits.items()}
_agentopia_gate_local = _agentopia_gate_threading.local()
_agentopia_gate_original_generate_with_fc = generate_with_fc

@_agentopia_gate_functools.wraps(_agentopia_gate_original_generate_with_fc)
def generate_with_fc(*args, **kwargs):
    if getattr(_agentopia_gate_local, "depth", 0):
        return _agentopia_gate_original_generate_with_fc(*args, **kwargs)
    model = kwargs.get("model", args[0] if args else None)
    lock = _agentopia_gate_locks.get(model)
    if lock is None:
        return _agentopia_gate_original_generate_with_fc(*args, **kwargs)
    started = _agentopia_gate_time.monotonic()
    lock.acquire()
    waited = _agentopia_gate_time.monotonic() - started
    _agentopia_gate_local.depth = 1
    try:
        if waited > 5:
            try:
                logger.warning("[DURABLE_GATE] model=%s wait_seconds=%.2f", model, waited)
            except Exception:
                pass
        return _agentopia_gate_original_generate_with_fc(*args, **kwargs)
    finally:
        _agentopia_gate_local.depth = 0
        lock.release()
# AGENTOPIA_DURABLE_MODEL_GATE_V3_END
