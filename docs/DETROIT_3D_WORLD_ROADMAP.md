# Agentopia Detroit — Civilization and 3D World Roadmap
**Planning baseline: 2026-10-09** · **Status: proposed milestones, not delivered features**

## Vision
Grow a persistent, culturally diverse AI civilization whose residents have families, jobs, neighborhoods, institutions, beliefs, routines, consequences and lifetimes. Visualize the *same authoritative simulation* in an explorable city: streets, homes, businesses, schools, public spaces, infrastructure and the actions of residents.

## Architectural contract
- **Mac-hosted Python simulation remains authoritative** for identity, time, life events, movement, economic state and world checkpoints. Renderers never originate durable canon.
- **Read-only world projection / digital-twin API** publishes versioned snapshots and ordered, idempotent events, with stable citizen/building/household IDs; clients handle reconnect and replay.
- **Presentation-agnostic scene schema**: world coordinates, geometry/parcel IDs, transform, appearance, animation intent, activity, timestamps, LOD class, privacy/visibility and authority version.
- **Simulation is not frame-rate dependent.** 3D FPS must not change model calls, agent decision rate, clock advancement, or persistence.
- **Deterministic recovery**: snapshots plus event cursor, event IDs, checkpoint epoch, schema migration tests. Reject stale/out-of-order render updates and handle backpressure.
- **Visibility and permissions**: public spaces visible by default; private rooms and conversations only if permissions explicitly allow them. No publication of real user data, secrets, private city state, or model weights.

## Delivered / verified / pending (do not conflate)
| Layer | Status as of Oct 9, 2026 |
| --- | --- |
| Persistent Detroit engine | Live on author's Mac, reported v1.8.0-RC2; public GitHub may lag |
| Growth/active AI cohort/scheduling | Existing project architecture; source reconciliation pending |
| Family graph | Local read-only validation **PASS**: 220 people, 208 households |
| Family Phase 1 event registry | Installed locally; append-only event foundation, no autonomous modifications |
| Family Phase 2A lifecycle hook | Installed on disk; activates **only at next engine interpreter start** |
| Family API | Locally verified **HTTP 200** at `/api/family`; initially zero events |
| Family native navigation | Patch package prepared; local installation/visual verification **not confirmed** |
| Automated household moves, wealth transfer, divorce, family UI drilldown | Not delivered |
| Real-time voxel / Unreal render | **Roadmap only; not implemented** |

## Prioritized delivery sequence

### Gate 0 — Public/local code reconciliation and reproducibility
- Compare Mac HEAD, current branch, working tree and remote `origin`; review diffs before publishing.
- Run secret checks; exclude `.env`, `config.json`, `data/detroit_persistent/`, `runtime/`, `logs/`, `backups/`, credentials, screenshots of private data and model weights.
- Add automated tests for source compatibility, health endpoints, import/compile and checkpoint recovery; publish source **only after** local verification.
- Maintain public release notes distinguishing GitHub code from locally installed patches.
**Exit:** clean reviewed changeset, reproducible boot and API smoke tests, no live state published.

### Gate 1 — Family, households, lineage and activity fidelity
- Safely activate Phase 2A at a checkpoint boundary; verify idempotence and no double births/annual events.
- Complete native Family navigation, family timeline and neighborhood/citizen linkage.
- Implement consensual/probabilistic partnership changes, child development, households and estate transfer via single owner, ledger checks and explicit policy.
- All changes emit typed durable domain events with references to originating simulation ticks.
**Exit:** restart/replay regression; lifecycle, family, ledger and UI agree on IDs and events.

### Gate 2 — World geometry and spatial truth
- Create stable coordinates for Detroit-inspired **fictional** streets, blocks, parcels, neighborhoods, buildings, rooms, road networks, transit stops and public venues.
- Define indoor/outdoor boundaries, occupancy, doors and permissions; align agent mobility/activity paths to spatial locations.
- Build a deterministic procedural block/parcel generator using versioned seeds; store only overrides and scene metadata.
**Exit:** a resident's route, destination and activity match the same coordinates in API, map and persisted world.

### Gate 3 — Voxel 3D prototype (first renderer)
- Implement browser-local low-poly/voxel city viewer with streaming chunks, instancing, occlusion, LOD and spatial interest subscriptions.
- Represent pedestrians with distinct identities and animation states: walking, riding, working, studying, shopping, eating, socializing, resting and emergency response.
- Animate **reported activity**, never invent city events because an animation plays.
- Support camera follow, citizen/household lookup, neighborhood focus, speed controls (view playback vs simulation speed separate), weather/day-night/seasons, accessibility controls.
- Begin with one neighborhood and 25–50 visually active residents, measure memory, draw calls and FPS, then expand.
**Exit:** usable scene on target hardware, reconnect/replay correct, no simulation latency regression.

### Gate 4 — Unreal Engine high-fidelity renderer (parallel option)
- Build an Unreal client from the **same scene/event contract**, not a fork of the world engine.
- Use World Partition and scalable HLOD/Nanite where applicable; MetaHuman/character instancing only where the performance/license constraints allow.
- Use skeletal animation, behavior-based animation state mapping, interiors, vehicles, weather, lighting and cinematic observer cameras.
- Separate engine-machine rendering from Mac model inference if full-detail performance requires it; benchmark bandwidth and scene streaming.
- Compare implementation cost, performance, package size, remote-access experience and license constraints against voxel viewer before choosing default.
**Exit:** one district fully interactive as viewer, consistent with voxel/API behavior; no duplicate world truth.

### Gate 5 — Civic depth, resilience and multi-city expansion
- City government: elections, council, taxes, budgets, zoning, housing, emergency services and policy consequence.
- Critical infrastructure and OT/ICS simulation: power, water, telecoms, transport, safety with simulated incidents and recovery.
- Faction activity: ThAI Guardians, Obsidian Network; recruitment, education, investigations, defensive cyber scenarios and governance.
- Cultural representation: validated holiday packs (up to 50 per community), languages, faiths, migration, holidays, education and family observances; do not generate stereotypes.
- Link simulated worlds across regions with sovereign rules, data partitions, federated summaries and explicit trust boundaries.
**Exit:** measurable civil systems, explainable outcomes, resilient persistence across interruptions and load.

## Simulation-to-renderer event contract (proposal)
```json
{
  "schema": "detroit.scene.event.v1",
  "world_id": "detroit-fictional-2045",
  "checkpoint_id": "checkpoint-opaque-id",
  "sequence": 12345,
  "event_id": "stable-opaque-event-id",
  "sim_time": { "year": 2045, "week": 5, "day": 1, "tick": 3 },
  "subject": { "kind": "citizen", "id": "stable-citizen-id" },
  "event_type": "activity.started",
  "activity": "working",
  "location_id": "stable-place-id",
  "animation_intent": "work",
  "visibility": "public"
}
```
Illustrative schema only: do **not** treat these values as live facts, an implemented endpoint or a committed schema.

## Success measures
- Canonical event replay rate and duplicate suppression; time to recover after restart.
- Number of persisted civic residents, active agents and 3D-visible residents **reported separately**.
- P50/P95 inference latency, queue depth, checkpoint duration and model load while rendering.
- FPS / frame time, scene memory, initial load time, chunk streaming latency, renderer power consumption.
- Percentage of visual behaviors traceable to canonical events; event-to-display delay.
- Family/ledger consistency, privacy enforcement and scenario outcomes.

## Non-goals
- No Unreal requirement for users running a headless server.
- No full LLM inference for every background pedestrian on every rendered frame.
- No upload of the author's persistent city or private agent biographies to a public GitHub repository.
- No assertion that 3D animations represent actual decisions unless backed by simulation events.
