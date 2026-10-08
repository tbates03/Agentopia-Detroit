# Agentopia Detroit Changelog

## v1.8.0-RC2 — Civilization Scale & Persistence

- Added SQLite indexed civilization state with WAL, foreign keys and citizen/entity indexes.
- Added append-only civilization event ledger with stable IDs and dedupe keys.
- Added relevance-driven active-AI cohort selection with critical-leader/faction pinning.
- Preserved deterministic RC1 active-cohort fallback.
- Integrated JSON/persona-to-SQLite synchronization into growth preflight.
- Added persona-promotion ledger events.
- Added civilization invariant checks.
- Added 100K-citizen / 1K-persona / 10K-event headless stress harness.
- Expanded the growth regression audit from 23 to 28 checks.
- GitHub Actions validation: 28/28 checks passed; 100K stress completed in 0.842s.
- Live persistent Detroit migrated successfully to RC2 on October 8, 2026: 216 civic citizens, 202 persistent personas, 9/9 civilization invariants, 28/28 growth checks, 100K stress in 0.337s, and observer/City Pulse/engine/active-view verified after restart.



## 1.8.0-RC1 - Growth Architecture Audit

This release candidate audits the Detroit fork against the original Agentopia assumptions and removes current hard blockers to long-run civic growth.

### Time and persistence

- changed the Detroit persistent runtime from the inherited compressed 10-week year to 52 simulation weeks per year
- retained five LLM-heavy activity days per week while World Context represents the seven-day calendar
- changed reward compatibility to a 13-week period so the 52-week year passes core validation
- expanded the practical simulation horizon to one million configured years
- added safe year-boundary process recycling from the committed checkpoint so newly promoted citizens can enter future active cohorts

### Population and lifecycle

- added Detroit Growth Manager
- added annual bounded migration in addition to births
- preserved and propagated explicit founder lineage through recorded parent relationships
- removed the first-100 truncation from lifecycle activation candidates
- added background-to-persistent-persona promotion
- added current-year profile carry-forward for inactive personas
- separated civic population, persistent persona population and active AI population

### Local compute and context scale

- removed the 12-worker ceiling from all fast speed modes
- added configurable adaptive world-task concurrency
- fixed PublicActivity multi-slot semaphore deadlock
- bounded and rotated global citizen summaries used by God-model prompts
- bounded and rotated encounter-generation citizen context
- moved rich weekly mobility generation to the active AI cohort

### Economy and city capacity

- scaled Career Economy vacancies with the active cohort
- made Detroit Career/Business Economy authoritative over the inherited yearly position market after bootstrap
- confirmed Human Economy housing stock already expands with household demand
- added incremental public-map growth with duplicate-name avoidance

### Validation

- added `docs/DETROIT_GROWTH_AUDIT.md`
- added `scripts/audit_detroit_growth.py --strict`
- added GitHub Actions growth-audit validation

This is an **RC** because the public architecture has been patched, but the private persistent Detroit world must be migrated and observed before this becomes the next stable Detroit runtime.


## 1.7.4.5.1 - Experimental Alpha

Initial public Detroit fork preparation.

Major development areas include:

- persistent world execution
- checkpoint recovery
- Detroit 2045 world
- cognitive society
- human lifecycle
- social and faction systems
- mission and justice system
- financial system
- career economy
- human economy
- business economy
- education and skills
- healthcare
- mobility and time
- digital twin telemetry
- Live World observer
- local model pool tooling
- watchdog and operational tooling
- right-sized local AI research architecture

### Right-Sizing documentation / launcher update

The public alpha now documents the central research purpose of Agentopia Detroit:

**Use the smallest model that can reliably perform the task, then escalate only when necessary.**

The core local launcher now supports automatic `light`, `balanced`, and `performance` profiles and exposes concurrency/context overrides through environment variables.

The current three-model Liquid AI pool remains:

- LFM2.5 350M for lightweight social work
- LFM2.5 1.2B Instruct for routine citizen reasoning
- LFM2.5 2.6B for strategy and higher-complexity work

Model weights remain external to this repository.

Current alpha limitations include:

- household systems are not yet fully unified
- model repetition and context handling are still being optimized
- installation is not fully hardware-independent
- some operational helpers currently assume macOS
- model weights are not distributed
- private persistent world state is not distributed
- sanitized starter world is not yet included


### Live Right-Sizing Performance panel

- added host CPU and memory telemetry
- added live model busy-slot telemetry
- added privacy-safe per-inference timing records
- added request counts and success rate
- added average observed inference latency
- added task distribution across 350M / 1.2B / 2.6B tiers
- added requests-per-minute visibility
- added automatic City Pulse telemetry startup and watchdog recovery

The telemetry record intentionally excludes prompts, responses, credentials and citizen conversation content.


### Agentopia World League / TAi Transparent AI community research

- launched LEADERBOARD.md for participating persistent worlds
- leaderboard progress is based on committed simulation weeks
- display scale is designed to expand from weeks to months, years and decades as participation grows
- added privacy-safe World Beacon export tooling
- added generated leaderboard tooling
- added GitHub validation workflow for community submissions
- added multilingual Research Pack schema for jobs, trades, business workflows and other task families
- made native-language task text the primary research artifact; English summaries are optional
- added contributor provenance requirements for cultural/regional context
- separated public research/evaluation consent from model training/fine-tuning consent
- documented Agentopia World League as a transparent community-learning layer for TAi — Transparent AI


### World League weather, seasons and cultural calendar research

- added standalone World League / TAi research webpage
- added weather and environmental workload context to the roadmap
- added place-appropriate seasonality rather than assuming Detroit/Northern Hemisphere patterns
- added support direction for up to 50 widely celebrated holidays, observances, festivals and culturally important dates per represented community
- required contributor/community/source validation instead of TAi guessing cultural calendars
- documented that culture/language groups are never ranked against one another; task/model behavior is the research target


### World Context Engine v1.0.0

- implemented deterministic synthetic daily weather for each simulation week
- implemented season mapping by configured hemisphere/climate profile
- added shared environmental impacts for transportation, outdoor work, energy demand and health stress
- injected current world context into citizen prompts without inferring protected/cultural identity
- added live World Context sidecar and heartbeat
- exposed world-context telemetry in the Live World snapshot and World League webpage
- made Mobility & Time consume World Context weather as the environmental authority when available
- added provenance-backed culture/community calendar packs with a hard maximum of 50 observances per pack
- added U.S. public/federal civic baseline as a public calendar, explicitly not as a complete U.S. cultural definition
- added native-language calendar fields and explicit community membership support
- added weather/season/calendar metadata to privacy-safe World Beacons
