# Agentopia Detroit RC2 Live Migration

This migration is intentionally separate from the public RC2 code merge.

The live persistent world may be located in a separate tree such as:

`$HOME/AI/Agentopia`

while the public development repository may be:

`$HOME/Desktop/Agentopia-Detroit-Public`

The guarded migration therefore never assumes that a Git pull in the public
clone updates the live world.

## One-command migration

From the public RC2 checkout:

```bash
./MIGRATE-AGENTOPIA-DETROIT-RC2.command
```

Or directly:

```bash
python3 scripts/migrate_detroit_rc2.py
```

Override the live location with:

```bash
AGENTOPIA_LIVE=/path/to/live/Agentopia ./MIGRATE-AGENTOPIA-DETROIT-RC2.command
```

## Safety gates

The migration:

1. requires the public checkout to be clean
2. fast-forwards public `main`
3. verifies `VERSION=1.8.0-RC2`
4. pauses the launchd service and Agentopia sidecars
5. waits for live engine processes to stop
6. creates a timestamped backup under `backups/rc2-migration/`
7. backs up the full persistent world
8. backs up the live `src/`, `scripts/`, and control commands being replaced
9. copies only public code into the live tree
10. does **not** overwrite `data/detroit_persistent`, models, logs, runtime, backups, or the live virtual environment
11. compiles RC2 Python
12. creates/synchronizes `civilization.sqlite3`
13. runs civilization invariants
14. runs the full growth architecture audit
15. runs the local 100K-citizen stress harness
16. verifies checkpoint, persona directory count and civic people count did not change during preflight
17. verifies indexed citizen/persona counts cover the existing live population
18. restarts the persistent service
19. verifies observer health, engine process and rebuilt active-persona view

If a validation step fails after backup, the script restores the prior code
snapshot and leaves Detroit paused. The world backup remains untouched for
manual recovery.

## Deliberate non-destructive behavior

The migration does not manually advance the checkpoint.

It does not delete or rewrite the persistent world as part of code deployment.

The SQLite civilization store is additive in RC2. Existing JSON and persona
directories remain available as rollback and migration sources.

## Useful modes

Preflight and migrate but do not restart:

```bash
python3 scripts/migrate_detroit_rc2.py --no-restart
```

Use an already-updated public checkout without pulling:

```bash
python3 scripts/migrate_detroit_rc2.py --skip-pull
```

Use a different live world location:

```bash
python3 scripts/migrate_detroit_rc2.py --live /path/to/Agentopia
```

## Success marker

A successful migration writes:

`runtime/rc2_migration.json`

The marker contains the backup path, pre-migration snapshot, indexed-store
validation results, restart verification and final migration status.
