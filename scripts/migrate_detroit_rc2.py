#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
PUBLIC_ROOT = SCRIPT.parents[1]
DEFAULT_LIVE = Path(os.environ.get("AGENTOPIA_LIVE", str(Path.home() / "AI" / "Agentopia"))).expanduser()
LABEL = "com.agentopia.detroit.persistent"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

CODE_DIRS = ("src", "scripts")
TOP_FILES = (
    "VERSION",
    "AGENTOPIA-DETROIT-STATUS.command",
    "OPEN-AGENTOPIA-DETROIT.command",
    "PAUSE-AGENTOPIA-DETROIT.command",
    "AGENTOPIA-FULL-SYSTEM-CHECK.command",
)
PROCESS_PATTERNS = (
    "scripts/start_detroit_persistent_service.sh",
    "scripts/agentopia_watchdog.sh",
    "scripts/run_detroit_persistent.py",
    "[Pp]ython.*scripts/run_world.py.*detroit_persistent",
    "scripts/detroit_twin_daemon.py",
    "scripts/detroit_cognition_daemon.py",
    "scripts/detroit_humanity_daemon.py",
    "scripts/detroit_world_context_daemon.py",
    "scripts/agentopia_city_pulse.py",
    "scripts/start_detroit_cyber_async.sh",
    "scripts/open_agentopia_flight_recorder_console.sh",
    "live_world/server.py",
)
REQUIRED_RC2 = (
    "scripts/detroit_state_store.py",
    "scripts/detroit_relevance_activation.py",
    "scripts/detroit_civilization_invariants.py",
    "scripts/stress_detroit_civilization.py",
    "scripts/detroit_growth_manager.py",
    "scripts/run_detroit_persistent.py",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    cp = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if capture and cp.stdout:
        print(cp.stdout.rstrip())
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}")
    return cp


def python_for(live: Path) -> Path:
    candidate = live / ".venv" / "bin" / "python"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return candidate
    py = shutil.which("python3")
    if not py:
        raise RuntimeError("python3 not found and live .venv/bin/python is missing")
    return Path(py)


def health(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= int(r.status) < 300
    except Exception:
        return False


def world_snapshot(live: Path) -> dict[str, Any]:
    world = live / "data" / "detroit_persistent"
    cp = read_json(world / "checkpoint.json", {})
    persona = world / "persona"
    people = read_json(world / "humanity" / "people.json", {})
    meta = read_json(world / "persistent_world.json", {})
    return {
        "checkpoint": cp,
        "persona_dirs": len([p for p in persona.iterdir() if p.is_dir()]) if persona.exists() else 0,
        "civic_people_records": len(people) if isinstance(people, dict) else 0,
        "boot_count": int(meta.get("boot_count", 0)) if isinstance(meta, dict) else 0,
        "captured_at": now(),
    }


def git_pull_public(public: Path) -> None:
    if not (public / ".git").exists():
        raise RuntimeError(f"public source is not a git checkout: {public}")
    status = run(["git", "status", "--porcelain"], cwd=public).stdout.strip()
    if status:
        raise RuntimeError(
            "public checkout has uncommitted changes; migration refuses to pull over them:\n" + status
        )
    branch = run(["git", "branch", "--show-current"], cwd=public).stdout.strip()
    if branch != "main":
        run(["git", "switch", "main"], cwd=public)
    run(["git", "pull", "--ff-only", "origin", "main"], cwd=public)
    version = (public / "VERSION").read_text(encoding="utf-8").strip()
    if version != "1.8.0-RC2":
        raise RuntimeError(f"expected public VERSION 1.8.0-RC2, found {version!r}")
    for rel in REQUIRED_RC2:
        if not (public / rel).exists():
            raise RuntimeError(f"public RC2 file missing: {rel}")


def pids_for(pattern: str) -> list[int]:
    cp = subprocess.run(["pgrep", "-f", pattern], text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if cp.returncode not in (0, 1):
        return []
    out: list[int] = []
    for line in cp.stdout.splitlines():
        try:
            pid = int(line.strip())
        except Exception:
            continue
        if pid != os.getpid():
            out.append(pid)
    return out


def _remaining_agentopia_pids() -> list[int]:
    remaining: set[int] = set()
    for pattern in PROCESS_PATTERNS:
        remaining.update(pids_for(pattern))
    return sorted(pid for pid in remaining if pid != os.getpid())


def _process_diagnostics(pids: list[int]) -> str:
    if not pids:
        return ""
    cp = subprocess.run(
        ["ps", "-o", "pid=,ppid=,etime=,command=", "-p", ",".join(str(x) for x in pids)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return (cp.stdout or "").strip()


def _tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return f"[missing] {path}"
    try:
        data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return f"[unreadable] {path}: {exc}"
    return "\n".join(data[-lines:])


def startup_diagnostics(live: Path) -> str:
    sections: list[str] = []
    pids = _remaining_agentopia_pids()
    sections.append("=== PROCESS SNAPSHOT ===")
    sections.append(_process_diagnostics(pids) or "(no matched Agentopia processes)")

    if shutil.which("launchctl"):
        domain = f"gui/{os.getuid()}"
        cp = subprocess.run(
            ["launchctl", "print", f"{domain}/{LABEL}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        sections.append("\n=== LAUNCHD SERVICE ===")
        sections.append((cp.stdout or "").strip() or f"launchctl print exit={cp.returncode}")

    for rel in (
        "logs/live-world-persistent.log",
        "logs/model-pool-bootstrap.log",
        "logs/detroit-backend.log",
        "logs/detroit-manual-start.log",
        "logs/agentopia-city-pulse.log",
        "logs/detroit-digital-twin.log",
        "logs/detroit-cognition.log",
        "logs/detroit-humanity.log",
        "logs/detroit-world-context.log",
        "logs/cyber-async-bootstrap.log",
    ):
        path = live / rel
        sections.append(f"\n=== TAIL {rel} ===")
        sections.append(_tail(path, 80))

    return "\n".join(sections)


def stop_live(live: Path, timeout_seconds: float = 20.0) -> None:
    print("\n=== PAUSING LIVE DETROIT ===")
    domain = f"gui/{os.getuid()}"

    # Stop the supervisor first so it cannot recreate children while we drain.
    if shutil.which("launchctl"):
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if PLIST.exists():
            subprocess.run(
                ["launchctl", "bootout", domain, str(PLIST)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    targeted = _remaining_agentopia_pids()
    if targeted:
        print("Stopping Agentopia processes:", ", ".join(str(x) for x in targeted))
    for pid in targeted:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"WARNING: permission denied sending SIGTERM to PID {pid}")

    deadline = time.monotonic() + max(5.0, timeout_seconds * 0.65)
    remaining: list[int] = []
    while time.monotonic() < deadline:
        remaining = _remaining_agentopia_pids()
        if not remaining:
            break
        time.sleep(0.5)

    # Agentopia-owned processes that ignore TERM are safe to force-stop here.
    # We never use a broad killall/pkill pattern outside the explicit list above.
    if remaining:
        print("TERM grace expired; force-stopping remaining Agentopia PIDs:", ", ".join(str(x) for x in remaining))
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                print(f"WARNING: permission denied sending SIGKILL to PID {pid}")

        kill_deadline = time.monotonic() + max(3.0, timeout_seconds * 0.35)
        while time.monotonic() < kill_deadline:
            remaining = _remaining_agentopia_pids()
            if not remaining:
                break
            time.sleep(0.4)

    if remaining:
        diag = _process_diagnostics(remaining)
        if diag:
            print("\nSurviving Agentopia process diagnostics:\n" + diag)
        raise RuntimeError(
            "live Agentopia processes still survived the guarded stop; "
            "migration aborted before backup/code/state writes"
        )

    stopper = live / "scripts" / "stop_detroit_llama.sh"
    if stopper.exists():
        subprocess.run(
            [str(stopper)],
            cwd=str(live),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )

    print("Live Detroit paused cleanly; supervisor and child processes are stopped.")


def copytree_clean(source: Path, dest: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        dest,
        symlinks=True,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
    )


def backup_live(live: Path, before: dict[str, Any]) -> Path:
    print("\n=== BACKUP ===")
    root = live / "backups" / "rc2-migration" / stamp()
    root.mkdir(parents=True, exist_ok=False)

    world = live / "data" / "detroit_persistent"
    copytree_clean(world, root / "detroit_persistent")

    for dirname in CODE_DIRS:
        src = live / dirname
        if src.exists():
            copytree_clean(src, root / "code-before" / dirname)

    for filename in TOP_FILES:
        src = live / filename
        if src.exists() and src.is_file():
            dst = root / "code-before" / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    manifest = {
        "created_at": now(),
        "live_root": str(live),
        "source_public_root": str(PUBLIC_ROOT),
        "before": before,
        "purpose": "Agentopia Detroit v1.8.0-RC2 guarded migration",
    }
    write_json(root / "manifest.json", manifest)
    print(f"Backup complete: {root}")
    return root


def sync_code(public: Path, live: Path) -> None:
    print("\n=== SYNCING RC2 CODE INTO LIVE TREE ===")
    for dirname in CODE_DIRS:
        src = public / dirname
        dst = live / dirname
        if not src.exists():
            raise RuntimeError(f"public code directory missing: {src}")
        copytree_clean(src, dst)

    for filename in TOP_FILES:
        src = public / filename
        if not src.exists():
            continue
        dst = live / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    for rel in REQUIRED_RC2:
        if not (live / rel).exists():
            raise RuntimeError(f"live RC2 file missing after sync: {rel}")

    live_version = (live / "VERSION").read_text(encoding="utf-8").strip()
    if live_version != "1.8.0-RC2":
        raise RuntimeError(f"live VERSION mismatch after sync: {live_version!r}")

    print("Code sync complete. Persistent world data was not overwritten.")


def compile_rc2(live: Path, py: Path) -> None:
    print("\n=== PYTHON COMPILE GATE ===")
    paths = [
        "scripts/run_detroit_persistent.py",
        "scripts/detroit_growth_manager.py",
        "scripts/detroit_state_store.py",
        "scripts/detroit_relevance_activation.py",
        "scripts/detroit_civilization_invariants.py",
        "scripts/stress_detroit_civilization.py",
        "scripts/audit_detroit_growth.py",
        "src/world/world.py",
        "src/world/god.py",
        "src/world/simulation_speed.py",
        "src/world/locations.py",
        "src/world/mapgen.py",
    ]
    run([str(py), "-m", "py_compile", *paths], cwd=live)


def migrate_index_and_validate(live: Path, py: Path, before: dict[str, Any]) -> dict[str, Any]:
    print("\n=== BUILDING INDEXED CIVILIZATION STATE ===")
    run([str(py), "scripts/detroit_state_store.py", "sync"], cwd=live)

    print("\n=== CIVILIZATION INVARIANTS ===")
    run([str(py), "scripts/detroit_civilization_invariants.py", "--strict"], cwd=live)

    print("\n=== GROWTH ARCHITECTURE AUDIT ===")
    run([str(py), "scripts/audit_detroit_growth.py", "--strict"], cwd=live)

    print("\n=== LOCAL 100K HEADLESS STRESS ===")
    run([
        str(py),
        "scripts/stress_detroit_civilization.py",
        "--citizens", "100000",
        "--personas", "1000",
        "--events", "10000",
        "--max-seconds", "30",
    ], cwd=live)

    after = world_snapshot(live)
    if after["checkpoint"] != before["checkpoint"]:
        raise RuntimeError(
            f"checkpoint changed during migration preflight: {before['checkpoint']} -> {after['checkpoint']}"
        )
    if after["persona_dirs"] != before["persona_dirs"]:
        raise RuntimeError(
            f"persona directory count changed during migration preflight: "
            f"{before['persona_dirs']} -> {after['persona_dirs']}"
        )
    if after["civic_people_records"] != before["civic_people_records"]:
        raise RuntimeError(
            f"civic people count changed during migration preflight: "
            f"{before['civic_people_records']} -> {after['civic_people_records']}"
        )

    stats_cp = run([str(py), "scripts/detroit_state_store.py", "stats"], cwd=live)
    try:
        stats = json.loads(stats_cp.stdout)
    except Exception:
        stats = {}

    if int(stats.get("citizens", 0)) < int(before["civic_people_records"]):
        raise RuntimeError("indexed citizen count is smaller than the civic people registry")
    if int(stats.get("personas", 0)) < int(before["persona_dirs"]):
        raise RuntimeError("indexed persona count is smaller than the persistent persona directory count")

    return {"after_preflight": after, "store_stats": stats}


def restart_live(live: Path, py: Path) -> None:
    print("\n=== RESTARTING LIVE DETROIT ===")
    if shutil.which("launchctl") and PLIST.exists():
        domain = f"gui/{os.getuid()}"
        boot = subprocess.run(
            ["launchctl", "bootstrap", domain, str(PLIST)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        # bootstrap returns nonzero when an already-loaded label exists; kickstart
        # is authoritative for whether launchd can actually start the service.
        kick = subprocess.run(
            ["launchctl", "kickstart", f"{domain}/{LABEL}"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if kick.returncode == 0:
            print("launchd kickstart accepted.")
            return
        print("launchd kickstart failed; falling back to direct guarded service start.")
        if boot.stdout:
            print("bootstrap:", boot.stdout.strip())
        if kick.stdout:
            print("kickstart:", kick.stdout.strip())

    log = live / "logs" / "detroit-manual-start.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("ab", buffering=0)
    subprocess.Popen(
        [str(live / "scripts" / "start_detroit_persistent_service.sh")],
        cwd=str(live),
        stdout=fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def verify_restart(live: Path, seconds: int) -> dict[str, Any]:
    print("\n=== POST-RESTART VERIFY ===")
    deadline = time.monotonic() + max(5, seconds)
    observer = False
    city_pulse = False
    engine = False
    active_view = False
    boot_state = ""

    while time.monotonic() < deadline:
        observer = health("http://127.0.0.1:8766/api/health", timeout=0.8)
        city_pulse = health("http://127.0.0.1:8767/api/health", timeout=0.8)
        engine = bool(pids_for("scripts/run_detroit_persistent.py"))
        view = live / "data" / "detroit_persistent" / ".active_persona_view"
        active_view = view.exists() and any(view.iterdir())
        state_path = live / "runtime" / "boot_state"
        if state_path.exists():
            try:
                boot_state = state_path.read_text(encoding="utf-8").strip()
            except Exception:
                boot_state = ""
        if observer and engine and active_view:
            break
        time.sleep(2)

    result = {
        "observer_health": observer,
        "city_pulse_health": city_pulse,
        "engine_process": engine,
        "active_persona_view": active_view,
        "boot_state": boot_state,
        "checkpoint": read_json(live / "data" / "detroit_persistent" / "checkpoint.json", {}),
    }
    print(json.dumps(result, indent=2))

    failures = []
    if not observer:
        failures.append("observer health did not recover")
    if not engine:
        failures.append("Detroit engine process is not active")
    if not active_view:
        failures.append("RC2 active persona view was not rebuilt")
    if failures:
        print("\n=== STARTUP FAILURE DIAGNOSTICS ===")
        print(startup_diagnostics(live))
        raise RuntimeError("; ".join(failures))
    return result


def rollback_code(live: Path, backup_root: Path) -> None:
    before = backup_root / "code-before"
    for dirname in CODE_DIRS:
        src = before / dirname
        if src.exists():
            copytree_clean(src, live / dirname)
    for filename in TOP_FILES:
        src = before / filename
        if src.exists():
            shutil.copy2(src, live / filename)


def main() -> int:
    ap = argparse.ArgumentParser(description="Guarded live migration to Agentopia Detroit v1.8.0-RC2")
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    ap.add_argument("--public", type=Path, default=PUBLIC_ROOT)
    ap.add_argument("--skip-pull", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--verify-seconds", type=int, default=120)
    args = ap.parse_args()

    live = args.live.expanduser().resolve()
    public = args.public.expanduser().resolve()
    world = live / "data" / "detroit_persistent"
    if not world.exists():
        raise SystemExit(f"live persistent Detroit world not found: {world}")

    print("======================================================")
    print(" AGENTOPIA DETROIT v1.8.0-RC2 LIVE MIGRATION")
    print("======================================================")
    print("Public source:", public)
    print("Live world:   ", live)
    print()

    backup_root: Path | None = None
    before = world_snapshot(live)
    print("Pre-migration snapshot:")
    print(json.dumps(before, indent=2))

    try:
        if not args.skip_pull:
            git_pull_public(public)
        stop_live(live)
        backup_root = backup_live(live, before)
        sync_code(public, live)
        py = python_for(live)
        compile_rc2(live, py)
        validation = migrate_index_and_validate(live, py, before)

        marker = {
            "version": "1.8.0-RC2",
            "migrated_at": now(),
            "backup": str(backup_root),
            "before": before,
            "validation": validation,
            "status": "preflight_passed",
        }
        write_json(live / "runtime" / "rc2_migration.json", marker)

        if args.no_restart:
            print("\nRC2 migration preflight PASSED. Live Detroit remains paused by request.")
            return 0

        restart_live(live, py)
        restart = verify_restart(live, args.verify_seconds)
        marker["restart"] = restart
        marker["status"] = "live_verified"
        write_json(live / "runtime" / "rc2_migration.json", marker)

        print("\n======================================================")
        print(" RC2 LIVE MIGRATION: PASS")
        print("======================================================")
        print("Checkpoint preserved:", before["checkpoint"])
        print("Backup:", backup_root)
        print("Migration marker:", live / "runtime" / "rc2_migration.json")
        return 0

    except Exception as exc:
        print("\nMIGRATION FAILED:", exc, file=sys.stderr)
        if backup_root is not None:
            # A restart failure may leave launchd children running. Stop them
            # before replacing files underneath a live Python process.
            try:
                stop_live(live)
            except Exception as stop_error:
                print("WARNING: rollback pre-stop could not prove a clean stop:", stop_error, file=sys.stderr)
                print(startup_diagnostics(live), file=sys.stderr)
            try:
                rollback_code(live, backup_root)
                print("Code rollback restored from:", backup_root / "code-before", file=sys.stderr)
            except Exception as rollback_error:
                print("Code rollback also failed:", rollback_error, file=sys.stderr)
            print(
                "Persistent world backup is preserved at: " + str(backup_root / "detroit_persistent"),
                file=sys.stderr,
            )
            db = live / "data" / "detroit_persistent" / "civilization.sqlite3"
            if db.exists():
                print(
                    "NOTE: the additive RC2 civilization.sqlite3 index exists in the live world. "
                    "It does not replace JSON/persona state and can be safely re-synchronized on the next attempt.",
                    file=sys.stderr,
                )
        else:
            print(
                "Migration stopped before a backup/code/state migration was created.",
                file=sys.stderr,
            )
        print("Detroit remains paused for inspection.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
