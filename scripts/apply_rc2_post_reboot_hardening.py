#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE = Path(os.environ.get("AGENTOPIA_LIVE", str(Path.home() / "AI" / "Agentopia"))).expanduser()

SYNC_DIRS = ("src", "scripts", "live_world")
TOP_FILES = (
    "VERSION",
    "AGENTOPIA-FULL-SYSTEM-CHECK.command",
    "AGENTOPIA-DETROIT-STATUS.command",
    "AGENTOPIA-HUMAN-ECONOMY-STATUS.command",
)


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def copytree(source: Path, dest: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        dest,
        symlinks=True,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".DS_Store"),
    )


def restore_tree(source: Path, dest: Path) -> None:
    if not source.exists():
        return
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, symlinks=True)


def run(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    cp = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if cp.stdout:
        print(cp.stdout.rstrip())
    if check and cp.returncode != 0:
        raise RuntimeError(f"command failed ({cp.returncode}): {' '.join(cmd)}")
    return cp


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply RC2 post-reboot hardening to live Agentopia Detroit")
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    ap.add_argument("--public", type=Path, default=ROOT)
    args = ap.parse_args()

    live = args.live.expanduser().resolve()
    public = args.public.expanduser().resolve()
    world = live / "data" / "detroit_persistent"
    if not world.exists():
        print(f"ERROR: live Detroit world not found: {world}", file=sys.stderr)
        return 2

    # Reuse the already-tested guarded process management from RC2 migration tooling.
    sys.path.insert(0, str(public / "scripts"))
    import migrate_detroit_rc2 as guard

    py = guard.python_for(live)
    before = guard.world_snapshot(live)
    backup = live / "backups" / "rc2-post-reboot-hardening" / stamp()

    print("=" * 62)
    print(" AGENTOPIA DETROIT RC2 POST-REBOOT HARDENING")
    print("=" * 62)
    print("Public source:", public)
    print("Live root:    ", live)
    print("Checkpoint:   ", json.dumps(before.get("checkpoint", {})))
    print()

    backup_created = False
    try:
        guard.stop_live(live)

        print("\n=== BACKUP ===")
        backup.mkdir(parents=True, exist_ok=False)
        copytree(world, backup / "detroit_persistent")
        for dirname in SYNC_DIRS:
            copytree(live / dirname, backup / "code-before" / dirname)
        for filename in TOP_FILES:
            src = live / filename
            if src.exists():
                dst = backup / "code-before" / filename
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        backup_created = True
        print("Backup complete:", backup)

        print("\n=== SYNC HARDENED RC2 CODE ===")
        for dirname in SYNC_DIRS:
            copytree(public / dirname, live / dirname)
        for filename in TOP_FILES:
            src = public / filename
            if src.exists():
                shutil.copy2(src, live / filename)

        print("\n=== COMPILE ===")
        run([
            str(py), "-m", "py_compile",
            "scripts/run_detroit_persistent.py",
            "scripts/detroit_human_lifecycle.py",
            "scripts/detroit_human_economy.py",
            "scripts/detroit_humanity_daemon.py",
            "scripts/detroit_state_store.py",
            "scripts/audit_detroit_growth.py",
            "live_world/server.py",
        ], cwd=live)

        print("\n=== RECONCILE LIFECYCLE / HOUSEHOLDS ===")
        run([str(py), "scripts/detroit_human_lifecycle.py", "update"], cwd=live)
        run([str(py), "scripts/detroit_human_economy.py", "init"], cwd=live)

        print("\n=== SYNCHRONIZE RC2 CIVILIZATION STORE ===")
        run([str(py), "scripts/detroit_state_store.py", "sync"], cwd=live)
        run([str(py), "scripts/detroit_civilization_invariants.py", "--strict"], cwd=live)
        run([str(py), "scripts/audit_detroit_growth.py", "--strict"], cwd=live)

        after = guard.world_snapshot(live)
        if after.get("checkpoint") != before.get("checkpoint"):
            raise RuntimeError(
                f"checkpoint changed during hardening preflight: {before.get('checkpoint')} -> {after.get('checkpoint')}"
            )

        print("\n=== RESTART UNDER LAUNCHD ===")
        guard.restart_live(live, py)
        restart = guard.verify_restart(live, 150)

        print("\n=== HEARTBEAT VERIFY ===")
        hb_path = live / "runtime" / "engine_heartbeat.json"
        hb_error = live / "runtime" / "engine_heartbeat.error.log"
        engine_pids = guard.pids_for("scripts/run_detroit_persistent.py")
        expected_pid = engine_pids[0] if engine_pids else None
        hb = {}
        deadline = __import__("time").monotonic() + 90
        last_error = None
        while __import__("time").monotonic() < deadline:
            try:
                if hb_path.exists():
                    hb = json.loads(hb_path.read_text(encoding="utf-8"))
                    pid = int(hb.get("pid") or 0)
                    if (
                        hb.get("version") == "1.8.0-RC2"
                        and pid > 0
                        and (expected_pid is None or pid == expected_pid)
                    ):
                        try:
                            os.kill(pid, 0)
                            break
                        except OSError:
                            pass
            except Exception as exc:
                last_error = exc
            __import__("time").sleep(1)
        else:
            err_text = hb_error.read_text(encoding="utf-8", errors="replace") if hb_error.exists() else ""
            raise RuntimeError(
                f"fresh RC2 heartbeat did not appear for engine pid={expected_pid}; "
                f"last={hb!r}; read_error={last_error}; writer_error={err_text.strip() or 'none'}"
            )
        print(json.dumps(hb, indent=2))

        print("\n=== RC2 STORE ===")
        run([str(py), "scripts/detroit_state_store.py", "stats"], cwd=live)

        marker = {
            "version": "1.8.0-RC2",
            "backup": str(backup),
            "before": before,
            "after_preflight": after,
            "restart": restart,
            "heartbeat": hb,
            "status": "pass",
        }
        marker_path = live / "runtime" / "rc2_post_reboot_hardening.json"
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")

        print("\n" + "=" * 62)
        print(" RC2 POST-REBOOT HARDENING: PASS")
        print("=" * 62)
        print("Backup:", backup)
        print("Marker:", marker_path)
        return 0

    except Exception as exc:
        print("\nHARDENING FAILED:", exc, file=sys.stderr)
        try:
            guard.stop_live(live)
        except Exception:
            pass

        if backup_created:
            try:
                print("Restoring world and code backup...", file=sys.stderr)
                restore_tree(backup / "detroit_persistent", world)
                for dirname in SYNC_DIRS:
                    restore_tree(backup / "code-before" / dirname, live / dirname)
                for filename in TOP_FILES:
                    src = backup / "code-before" / filename
                    if src.exists():
                        shutil.copy2(src, live / filename)
                print("Rollback restored from:", backup, file=sys.stderr)
                old_py = guard.python_for(live)
                guard.restart_live(live, old_py)
            except Exception as rollback_exc:
                print("Rollback/restart failed:", rollback_exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
