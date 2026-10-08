# Agentopia Detroit v1.8.0-RC2 — Civilization Scale & Persistence

## Purpose

RC2 moves Agentopia Detroit from a directory-heavy persistent city toward an indexed, event-driven synthetic civilization without replacing the RC1 simulation engine.

The architectural rule is:

> **Civic existence scales broadly; expensive cognition is assigned selectively.**

RC2 keeps the existing JSON/persona world as the migration and debugging source while adding a SQLite civilization state plane, append-only event history, relevance-driven activation, explicit invariants, and a headless 100K-citizen scale test.

## What RC2 adds

### Indexed civilization state

File: scripts/detroit_state_store.py

The new embedded SQLite store creates indexed tables for citizens, durable entity-state snapshots, append-only civilization events, activation scores, and schema metadata.

SQLite is intentionally the first step. It gives Detroit transactional writes, indexes, WAL mode, foreign keys and fast local queries without adding an external service dependency.

The current JSON files are still retained. RC2 synchronizes them into the index so migration is reversible and operationally conservative.

Default local database: data/detroit_persistent/civilization.sqlite3

That runtime directory is already excluded from the public repository.

### Append-only civilization event ledger

The events table records facts such as births, migration, persona promotion, job changes, business creation or closure, faction membership, missions, legal cases, arrests, major health events, relationship milestones and active-cohort selections.

Events carry stable event IDs, simulation year/week, actor and subject IDs, source, importance, JSON payload and an optional dedupe key.

This makes history explicit instead of forcing every subsystem to infer history from today's files.

### Relevance-driven cognition

File: scripts/detroit_relevance_activation.py

RC1 separated civic population from the active AI cohort. RC2 changes how the active cohort is chosen.

TGOT, Morbeious and configured faction-critical citizens remain pinned when present. Remaining slots are ranked from recent high-signal events with deterministic tie-breaking.

Examples of high-signal events include active missions, arrests or legal cases, faction leadership, business start/closure, major health events, relationship changes, job changes and education milestones.

The active cohort is therefore a computational attention window, not a permanent social class.

If relevance selection fails for any reason, the RC1 deterministic foreground/background selection remains as the fallback.

### Civilization invariants

File: scripts/detroit_civilization_invariants.py

RC2 adds machine-checkable rules intended to stop silent state corruption. Initial invariants include unique citizen IDs, non-empty names, plausible birth years, promotion not preceding birth, dead personas not remaining active-eligible, nonnegative event importance, activation scores resolving to known citizens, and checkpoint year/week validity.

### 100K-citizen headless stress harness

File: scripts/stress_detroit_civilization.py

The scale harness creates a temporary civilization database with 100,000 civic citizens, 1,000 persistent personas, 10,000 civilization events and relevance selection of 128 active citizens. No production world data is modified.

During development of RC2, the isolated harness completed this workload in approximately **0.62 seconds** in the available execution environment. That is a development benchmark, not a promise about every machine.

CI uses a 30-second ceiling to catch major regressions while avoiding machine-specific microbenchmark assumptions.

## Boot flow in RC2

1. Load the canonical Detroit checkpoint/config.
2. Run lifecycle update.
3. Carry inactive persona profiles forward.
4. Promote the bounded yearly background cohort.
5. Synchronize legacy JSON/persona state into SQLite.
6. Record promotion events in the ledger.
7. Calculate the bounded active-AI target.
8. Score persistent personas by relevance.
9. Pin critical leaders/faction members.
10. Build the active persona view.
11. Assign local model pools.
12. Start the existing Agentopia world engine.

Year-end process recycling remains unchanged from RC1.

## Compatibility and rollback

RC2 is deliberately additive. Existing JSON and persona directories remain present and are canonical inputs during this release candidate. SQLite is a derived indexed state plane. The active selector has a deterministic RC1 fallback. The private Week 5 world should not be migrated until RC2 CI and migration testing are complete.

## Next migration stages

1. Emit native events from lifecycle, career, business, finance, legal, faction, health and relationship systems.
2. Move read-heavy population queries from filesystem scans to indexed state.
3. Add materialized aggregate tables for neighborhoods, employment, housing, businesses and institutions.
4. Add event compaction/snapshot policy for very long simulations.
5. Add compute-budget telemetry so TAi can allocate Citizen, Strategy, Social and Cyber inference capacity by task importance.
6. Expand invariants to money conservation, family chronology, household reconciliation, business closure/payroll rules and irreversible identity history.

## Definition of RC2 success

RC2 is ready to merge when Python compilation passes, the growth architecture audit passes, the 100K-citizen scale harness stays inside the CI budget, the public branch can build an active cohort from the indexed state plane, fallback behavior remains functional, and private persistent Detroit has not been modified during public validation.

## Core principle

Detroit is no longer scaling by asking every citizen to think all the time.

It is scaling by preserving **everyone's state and history**, then spending cognition where the civilization currently needs it.
