# Agentopia Detroit Growth Architecture Audit

**Status:** v1.8.0-RC1 architecture review  
**Baseline:** upstream `Neph0s/Agentopia`  
**Target:** persistent Agentopia Detroit civic simulation + local-AI/right-sizing research platform

## Executive result

Agentopia Detroit is no longer an apartment-scale, fixed-cohort role-play experiment. It is becoming a persistent civic simulation in which the **city population, persistent citizen population, and expensive AI-active population are intentionally different layers**.

The growth audit found several inherited assumptions that were reasonable for the original Agentopia project but would eventually stop Detroit from behaving like a growing city. The v1.8.0-RC1 changes remove the hard blockers while retaining bounded controls where they protect context windows, local compute, or per-citizen state.

The governing rule is:

> **Detroit may grow without requiring every resident to be a full LLM agent every simulated week.**

## Where the fork started vs. where Detroit is going

| Area | Original Agentopia direction | Detroit direction | Growth impact | v1.8.0-RC1 disposition |
|---|---|---|---|---|
| Time | 10 weeks/year, 5 activity days/week | 52 calendar weeks/year, 5 LLM-heavy activity days/week | Hard calendar/lifecycle mismatch | **Fixed** |
| Run horizon | Small finite configured year count | Persistent long-run city | Hard long-horizon ceiling | **Fixed** |
| Population | Existing persona folders; population settings do not create a persistent civic population | Lifecycle population, lineage, births, migration, promotions | Hard population-growth gap | **Fixed** |
| Persona continuity | Active personas receive yearly profiles | Background personas must survive years before activation | Later activation could fail | **Fixed** |
| Active AI | Effectively fixed/foreground cohort | Bounded cohort that expands with promoted population | Hard compute/growth coupling | **Fixed** |
| Cohort refresh | Agents created once per process | Safe year-boundary process recycle | New citizens could never enter a long-running process | **Fixed** |
| Concurrency | Fast modes capped at 12 | Hardware-aware configurable ceiling | Throughput ceiling | **Fixed** |
| Public activity slots | Multi-slot semaphore acquired permit-by-permit | Atomic, capacity-clamped reservation | Deterministic deadlock risk | **Fixed** |
| Global prompts | All citizens can be concatenated into global prompts | Deterministic rotating representative context | Context-window grows O(N) | **Fixed** |
| Encounters | Every idle citizen/profile can enter one God prompt | Bounded rotating per-day sample | Context-window grows O(N) | **Fixed** |
| Mobility | Rich weekly trip generation for every persona | Rich mobility for active cohort; background population remains persistent | Weekly CPU/state growth O(N) | **Fixed** |
| Jobs | Fixed 60-vacancy generator | Vacancy supply scales with active cohort | Labor-market bottleneck | **Fixed** |
| Job authority | Legacy yearly Agentopia market + Detroit weekly career/business systems | Detroit Career/Business Economy authoritative after bootstrap | Competing truth sources | **Fixed** |
| Housing | Fixed initial stock with expansion helper | Dynamic stock expansion by household need | No hard population cap | **Already scalable** |
| Healthcare | Finite provider capacities | Finite capacity creates congestion/delay | Intentional scarcity, not population cap | **Keep bounded** |
| Public locations | Initial fixed map | Shared map grows gradually with active cohort | Soft spatial-richness ceiling | **Fixed** |
| Possessions | 50/citizen | Same | Per-citizen context/state protection | **Keep bounded** |
| Future scheduling | 4-week default horizon | Same | Local planning bound, not city-size bound | **Keep bounded** |
| Events | Bounded number/week | Bounded events with many possible participants | Prompt/scene protection | **Keep bounded** |

## The three population layers

Detroit now treats population as three related but distinct layers.

### 1. Civic population

The Human Lifecycle engine is the broadest population truth. People may exist as children, teens, adults, seniors, partners, descendants, migrants, or deceased historical residents without each person consuming an LLM slot every week.

This layer supports:

- births from explicit family/partner relationships
- mortality as a fictional simulation mechanic
- kinship and households
- belief change without equating religion with extremism
- annual migration
- founder/resident lineage
- activation eligibility

This is the layer that can ultimately grow into the thousands.

### 2. Persistent persona population

A bounded number of eligible background residents are promoted into durable persona directories over time.

Promoted personas receive:

- persistent identity and profile storage
- lifecycle provenance
- career/economic eligibility
- future active-cohort eligibility
- yearly profile carry-forward while inactive

A citizen does **not** disappear merely because they are outside the current AI-active cohort.

### 3. Active AI cohort

This is the expensive foreground simulation window.

The active cohort:

- is selected at boot/year rollover
- keeps TGOT, Morbeious and faction-critical citizens pinned when present
- prefers existing foreground citizens
- expands gradually as persistent persona population grows
- defaults to a configurable 64–128 local-agent envelope
- may be overridden by explicit environment settings for stronger hardware

This is a **compute policy**, not the definition of who exists in Detroit.

## Time-model correction

The original 10-week year was useful for rapid social simulation, but it conflicts with Detroit systems that already reason in real annual cadence:

- lifecycle age changes are annual
- Career Economy accumulates experience as 1/52 year per week
- Education uses multi-month durations such as 26 weeks
- Human Economy annualizes weekly inflation over 52 weeks
- World Context maps weather/seasons/calendar dates across the year
- World League research uses committed weeks as the canonical unit

Detroit therefore uses:

- **52 simulation weeks/year**
- **7 calendar days/week for date, weather, season and holiday context**
- **5 LLM-heavy activity days/week for the original Agentopia weekly social/activity loop**
- **13-week reward compatibility period**, which divides 52 cleanly

The five activity-day model is intentionally preserved. The calendar layer and the expensive role-play layer do not have to be identical.

## Growth mechanics added

### Annual migration

The one-time migration seed is no longer the only non-birth population source. Human Lifecycle now supports deterministic bounded annual arrivals.

Default policy:

- target rate: 2% of current living civic population
- minimum: 2 arrivals/year
- maximum: 8 arrivals/year

These are simulation defaults, not demographic claims. Origin never determines protected traits, religion, personality, skill, or model routing.

### Lineage propagation

Children inherit explicit founder lineage when one or both recorded parents carry founder lineage. Lineage is provenance, not destiny and not a protected-trait proxy.

### Background-to-persona promotion

The Growth Manager promotes a small bounded number of eligible adults each year. Promotion creates a durable persona but does not automatically force that person into the current active AI cohort.

### Background profile carry-forward

Agentopia core expects an exact `profile/year=<current>.json`. Active agents receive yearly LLM profile evolution, but inactive personas do not.

The Growth Manager now carries the latest prior profile forward for inactive personas so a citizen can safely return to the active cohort after years outside it.

## Scaling local intelligence rather than scaling prompts forever

A growing city cannot solve scale by sending more and more citizen text into every God-model call.

Detroit now uses deterministic rotating context windows for global tasks.

### Global citizen summaries

Global God tasks receive:

- total active population count
- representative profile count
- a bounded rotating citizen sample
- TGOT and Morbeious pinned when available

Omitted citizens keep their full persistent state. They are omitted from that **one global prompt**, not from the city.

### Encounter generation

Encounter prompts use a bounded rotating set of idle citizens per day. This prevents a city of hundreds or thousands of residents from turning one encounter-generation request into an unbounded context payload.

### Mobility

Full trip/schedule simulation is now foreground work. The active cohort receives rich mobility generation; broader civic population can remain in lighter aggregate/background systems until promoted.

## Local compute policy

The old speed controller capped all fast modes at 12 concurrent world tasks, so `x1000` could have the same concurrency as Normal.

v1.8.0-RC1 separates **timeline speed** from a configurable concurrency ceiling.

Default world-task policy:

- Slow: 1
- Normal: up to 12
- x2: up to 16
- x5: up to 24
- x10/x1000: up to configured cap
- default `AGENTOPIA_CONCURRENCY_CAP=32`
- never exceeds the base configured concurrency

The model servers still enforce their own slot/context limits. Higher concurrency should be measured, not assumed to be faster.

## PublicActivity deadlock correction

The prior scheduler could request N semaphore permits for one public activity and acquire them sequentially. A public task could partially consume the semaphore and wait forever for permits that could never become available.

The fix:

- clamps requested public slots to actual activity capacity
- treats a multi-slot reservation as one logical reservation under a lock
- releases exactly the held number of permits

This preserves parallelism while preventing the Week-5 style barrier deadlock.

## Job and business authority

Detroit's Career and Business economies now model:

- unemployment
- hiring
- vacancies
- promotions/raises
- retraining
- retirement
- entrepreneurship
- payroll
- business revenue/debt
- layoffs and bankruptcy

The original Agentopia yearly position market is therefore no longer allowed to silently overwrite Detroit's weekly economy after bootstrap.

Vacancy supply also scales with active population instead of remaining fixed at 60.

## Physical-space growth

Human Economy already expands housing stock as household demand grows.

v1.8.0-RC1 now also allows the shared **public location map** to expand gradually as the active cohort grows. Existing locations are retained; incremental generation is instructed not to duplicate existing names.

Default public-space policy:

- original base location count remains the floor
- target is approximately one shared public location per three active personas
- default maximum is 120 shared public locations
- private homes remain separate

This is a richness/civic-space policy, not one location per citizen.

## Bounds intentionally retained

Not every limit is a defect. Several limits should remain because they protect the system:

| Guardrail | Why it stays |
|---|---|
| 50 possessions/citizen | Keeps per-person state and prompts bounded |
| 4-week future social schedule | Human-scale planning window; avoids endless schedule context |
| Bounded events/week | Attendance can scale without generating hundreds of event descriptions |
| Bounded active AI cohort | Preserves local-compute feasibility |
| Bounded rotating global contexts | Prevents context-window growth from becoming a population ceiling |
| Healthcare capacity | Creates meaningful scarcity, waiting and infrastructure pressure |
| Public location maximum | Prevents map context from becoming another unbounded prompt surface |

A bound is acceptable when it limits **work per step**. It is a problem when it limits **who can exist or whether the city can continue**.

## Year-boundary cohort recycle

A single Python process cannot discover newly promoted personas because `World.agents` is built during initialization.

Detroit now treats a fully completed simulation year as a clean process boundary:

1. normal weekly checkpoints continue as before
2. year-end profile/reward work finishes
3. core commits the next-year checkpoint
4. the runner exits with intentional code `75`
5. the persistent service immediately relaunches
6. lifecycle and growth preflight run
7. inactive profiles are carried forward
8. eligible residents may be promoted
9. active cohort and model assignments are rebuilt
10. simulation resumes from the committed next-year checkpoint

No checkpoint is manually advanced.

## Regression audit

Run:

```bash
python scripts/audit_detroit_growth.py --strict
```

The audit checks the architecture markers for:

- 52-week time model
- reward compatibility
- practical persistent horizon
- lifecycle growth and annual migration
- lineage
- background persona promotion
- inactive profile continuity
- active-cohort scaling and refresh
- adaptive concurrency
- PublicActivity deadlock hardening
- bounded global prompts
- bounded encounter prompts
- active-cohort mobility
- scalable vacancy supply
- Detroit career authority
- World Context
- public-map expansion

When run inside the private live project, it also reports the current checkpoint, civic population, persona population, background population, and active view count.

## Remaining scale frontier

The v1.8.0-RC1 architecture removes the current **hard growth blockers**, but it does not claim infinite scale on one laptop.

At much larger populations, the next engineering transition is expected to be:

- indexed/SQLite or embedded analytical storage instead of repeated directory scans
- event partitioning/compaction
- aggregate background economy and mobility models
- dynamic active-cohort scheduling by relevance rather than only yearly promotion
- distributed/model-server placement across multiple machines
- stronger backpressure and phase budgets
- empirical auto-tuning from TAi right-sizing telemetry

Those are scale transitions, not reasons to cap Detroit at its original cohort.

## Architectural principle

Agentopia Detroit should grow like a city, not like one prompt.

**State can scale broadly. Expensive cognition must remain selective, observable and right-sized.**
