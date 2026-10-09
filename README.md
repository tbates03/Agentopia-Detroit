# Agentopia Detroit

## A Persistent AI Society Built on Agentopia

**Experimental Alpha - v1.8.0-RC1**

Agentopia Detroit is a persistent multi-agent simulation built as a fork of the original Agentopia project:

https://github.com/Neph0s/Agentopia

Detroit fork:

https://github.com/tbates03/Agentopia-Detroit

Agentopia Detroit extends the original long-horizon AI society into a persistent fictional Detroit of 2045.

---

## Why This Project Exists

Agentopia Detroit is not only an AI city.

It is a working experiment in **right-sized local AI architecture**.

The project asks a simple systems question:

> **What is the smallest model that can reliably complete the task?**

Instead of sending every request to one large general-purpose model, Agentopia Detroit separates workloads and routes them to smaller local models that are appropriate for the work.

The current local model pool uses three Liquid AI model tiers:

| Role | Model | Purpose |
|---|---|---|
| Social | LiquidAI LFM2.5 350M | High-frequency, lightweight social interactions |
| Citizen | LiquidAI LFM2.5 1.2B Instruct | Routine dialogue and citizen reasoning |
| Strategy | LiquidAI LFM2.5 2.6B | Planning, strategy and higher-complexity work |

An optional specialist model can be added for workloads that should not be handled by the core three-model pool.

The objective is **not** to prove that small models can replace frontier models.

The objective is to show that many useful workloads may not require a frontier model in the first place.

**Core principle: use the smallest model that can reliably perform the task, then escalate only when necessary.**


See [Right-Sized Local AI Architecture](docs/RIGHT_SIZING_ARCHITECTURE.md).

### Agentopia World League + TAi — Transparent AI

Agentopia Detroit now includes a public **World League** for community right-sizing research.

**[View the World League Leaderboard](LEADERBOARD.md)**

Fork the project, create your own world, keep it alive, and submit a privacy-safe World Beacon. The initial leaderboard ranks worlds by **committed simulation weeks completed**. As the community grows, the display expands from weeks to months, years, and eventually decades while preserving weeks as the canonical research unit.

But persistence is only the game layer.

The research layer asks contributors to add the jobs, trades, business processes, administrative work, public services, languages, and local workflows that exist in their communities so we can test what model size is actually required for those tasks.

**Please contribute tasks in the language in which the work is really performed. Do not translate yourself into English for us.** English summaries are useful for maintainers, but the native-language task is the primary research artifact.

This is also a transparent community-learning mechanism for **TAi — Transparent AI**. TAi should learn from people who know their language, profession, community, and workflow — not from us guessing at someone else's culture.

> **We learn from people willing to teach us, not by guessing at them.**

Research/evaluation consent and model-training consent are separate. A community contribution is not silently converted into model-training data.

See:

- [Agentopia World League](docs/WORLD_LEAGUE.md)
- [TAi — Transparent AI Community Learning](docs/TAI_TRANSPARENT_AI.md)
- [Community Research](research/README.md)



#### World Context Research

The community research roadmap now includes an implemented **World Context Engine v1.0.0** for weather, seasons, and culturally grounded calendars. It generates deterministic synthetic daily weather, maps place-appropriate seasons, injects the context into citizen prompts, exposes it through Live World telemetry, and lets mobility consume the same weather truth. Participating worlds can contribute up to 50 widely celebrated holidays, observances, festivals and culturally important dates per represented community when those calendars are validated rather than guessed.

A new local research page is available from the Live World server at:

    http://127.0.0.1:8766/world-league.html

See [World Context Research Roadmap](docs/WORLD_CONTEXT_ROADMAP.md).

World Context files:

- `scripts/detroit_world_context.py` — simulation/context authority
- `scripts/detroit_world_context_daemon.py` — live sidecar telemetry
- `research/culture_calendars/` — provenance-backed calendar packs
- `research/schema/culture_calendar.schema.json` — maximum 50 observances per community pack


---

## Michigan AI Symposium Demonstration

Agentopia Detroit is being prepared as a live demonstration of right-sized architecture, persistent agents and local AI performance for the **2026 Michigan AI Symposium**.

The city is the visible demonstration.

The architecture underneath it is the research story.

A persistent society creates continuous mixed workloads involving:

- conversations
- memory
- relationships
- planning
- financial transactions
- businesses
- careers
- education
- healthcare
- mobility
- public events
- factions
- missions
- world-state persistence

That makes the project useful for studying more than raw tokens-per-second.

The project is intended to examine:

- CPU/GPU utilization
- system memory use
- model memory footprint
- request latency
- throughput
- model saturation
- task distribution by model tier
- escalation/fallback rate
- simulation phase duration
- wall-clock time per simulated week
- persistent-state recovery

The central research question is:

> **How much intelligence can we keep local?**

---

## What Makes Detroit Different

Agentopia Detroit is not a chatbot demo. Citizens exist inside a persistent world and can:

- maintain long-term memories
- plan weekly goals
- meet and communicate with other citizens
- form relationships
- work and pursue careers
- earn and spend money
- participate in businesses
- attend educational activities
- experience healthcare events
- travel through a mobility network
- join factions
- participate in missions
- experience investigations and consequences
- resume across simulation checkpoints

## Growth Architecture

v1.8.0-RC1 adds a growth architecture audit and removes inherited assumptions that could turn the original Agentopia design into hard ceilings for a persistent city.

Detroit now separates:

1. **Civic population** — lightweight persistent lifecycle population, including families, descendants and migration.
2. **Persistent persona population** — citizens promoted into durable Agentopia persona/state storage.
3. **Active AI cohort** — the bounded local-model foreground that performs expensive weekly reasoning.

This lets Detroit grow without pretending one local computer should run every resident as a full LLM agent every week.

Major RC1 changes include a 52-week simulation year, annual migration, background-to-persona promotion, inactive profile carry-forward, year-boundary cohort refresh, adaptive concurrency, bounded rotating global prompts, scalable vacancies, active-cohort mobility, growing public-space capacity, and the PublicActivity semaphore deadlock correction.

Run the architecture regression audit with:

```bash
python scripts/audit_detroit_growth.py --strict
```

See **[Detroit Growth Architecture Audit](docs/DETROIT_GROWTH_AUDIT.md)**.

---

## Major Systems

- Persistent World
- Cognitive Society
- Human Lifecycle
- Social and Relationship Systems
- ThAI Guardians
- Obsidian Network
- Mission and Justice System
- Financial System
- Career Economy
- Human Economy
- Business Economy
- Education and Skills
- Health and Healthcare
- Mobility and Time
- Weather, Seasons & Cultural Calendars
- Digital Twin Telemetry
- Live World Observer
- Right-Sized Local Model Pool

---

## Right-Sized Local Model Pool

Model weights are **not stored in this repository**.

The launcher knows which official model repositories/files to request. If the selected GGUF file is not already cached locally, `llama-server` can resolve it from Hugging Face on first use.

Current core pools:

```text
8084  social     LiquidAI/LFM2.5-350M-GGUF
8081  citizen    LiquidAI/LFM2.5-1.2B-Instruct-GGUF
8082  strategy   LiquidAI/LFM2.5-2.6B-GGUF
```

The core launcher supports automatic hardware profiles:

| Profile | Intended Use |
|---|---|
| light | Lower-memory systems / experimentation |
| balanced | Typical development system |
| performance | Higher-memory systems / high concurrency |
| auto | Detect available memory and select a profile |

Override the automatic choice with:

```bash
AGENTOPIA_PROFILE=light bash scripts/start_detroit_llama.sh
AGENTOPIA_PROFILE=balanced bash scripts/start_detroit_llama.sh
AGENTOPIA_PROFILE=performance bash scripts/start_detroit_llama.sh
```

Individual concurrency/context values can also be overridden with environment variables. See the right-sizing document for details.

The optional cyber-specialist pool is separate from the three core pools and is not required for the basic right-sizing demonstration.

---

## Practical Hardware Guidance

These are practical starting points, **not certified minimum requirements**.

### Light experimentation

- modern 4-6 core CPU
- 16 GB system RAM
- SSD storage
- CPU-only inference is possible, but slower
- use the `light` profile

### Recommended student/developer system

- 6-8+ modern CPU cores
- 24-32 GB RAM
- SSD
- GPU acceleration or Apple Silicon is helpful but not required
- use `auto` or `balanced`

### Higher-concurrency experimentation

- 48+ GB RAM
- capable GPU or high-memory unified architecture
- use `performance`

The important point is that Agentopia Detroit is intentionally designed to explore how far small local models can be pushed before a larger model is justified.

---

## Persistent Simulation

Agentopia Detroit separates the live simulation from the last committed checkpoint.

Example:

```text
Committed checkpoint: Week 4
Live simulation:      Week 5 / Activity D1
```

The committed checkpoint is the recovery anchor. A partially completed week is not treated as durable history until it successfully completes.

---

## Live World Observer

The local observer normally runs at:

```text
http://127.0.0.1:8766
```

It can display simulation phase, citizens, conversations, model pools, factions, public events, economy, finance, lifecycle, healthcare, mobility, missions and other world telemetry.

The performance/telemetry direction for the project is to make model utilization visible alongside the society so the user can see both **what the agents are doing** and **what the computer is spending to do it**.

### Live Right-Sizing Performance

The Live World dashboard now includes a **Right-Sizing Performance** panel showing actual local telemetry:

- host CPU utilization
- system/unified memory use
- live busy/total slots for the 350M, 1.2B and 2.6B pools
- uncached inference request counts
- average end-to-end inference latency
- success rate
- per-tier workload share
- recent requests per minute

The panel is driven by privacy-safe telemetry. It records model tier, latency, success and timing only; it does **not** record prompts, responses, credentials or citizen conversation text.

The City Pulse telemetry service is started automatically by the persistent service launcher. For a manual development run, start it separately:

```bash
python scripts/agentopia_city_pulse.py
```

Then open the Live World dashboard at `http://127.0.0.1:8766`.

---

## Installation

Clone:

```bash
git clone https://github.com/tbates03/Agentopia-Detroit.git
cd Agentopia-Detroit
```

Create a Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install a recent `llama.cpp` / `llama-server` for local inference.

Start the right-sized local model pool:

```bash
bash scripts/start_detroit_llama.sh
```

On the first run, missing model files may be obtained by `llama-server` from the model repository configured in the launcher.

Model weights are distributed by their respective model publishers and remain subject to their own licenses and terms.

### Configuration

The original Agentopia configuration example remains available:

```bash
cp config.example.json config.json
```

Do not commit `config.json`.

---

## Running Detroit

The persistent Detroit runtime is:

```bash
python scripts/run_detroit_persistent.py
```

**Important alpha note:** Professor Bates' active persistent city state is intentionally not published. The public repository contains the Detroit engine and systems, but not the private live checkpoint/history. A sanitized starter world is a separate release item.

Local model helper scripts include:

```text
scripts/start_detroit_llama.sh
scripts/stop_detroit_llama.sh
scripts/agentopia-pool-status.sh
```

---

## Private Data Is Not Included

The active development simulation is intentionally excluded.

Not included:

```text
data/detroit_persistent/
logs/
runtime/
llm_cache/
generations/
backups/
model weights
credentials
```

---

## Beyond the Simulation

The right-sizing experiment is intentionally larger than Agentopia itself.

The same architectural idea can be applied to routine workloads such as:

- email classification and triage
- scheduling
- document routing
- local search
- knowledge retrieval
- document summarization
- structured data extraction
- office administrative workflows
- local personal assistants

A large model remains valuable when the problem actually requires it.

Agentopia Detroit explores how often it does **not**.

---

## Project Status

This is experimental alpha software.

Current development areas include:

- v1.8.0-RC1 live migration/validation
- large-population storage/indexing
- dynamic active-cohort relevance scheduling
- household truth unification
- simulation performance
- context budgeting
- model routing
- repetition handling
- fail-forward recovery
- persistent-state integrity
- installation automation
- Linux portability
- hardware auto-detection
- right-sizing telemetry
- sanitized starter worlds

---

## Repository Lineage

```text
Neph0s/Agentopia
        |
        v
tbates03/Agentopia-Detroit
```

The GitHub fork relationship is intentionally preserved.

## License and Attribution

The upstream Agentopia README states that Agentopia is released under the MIT License.

Agentopia Detroit preserves the upstream Git history and project attribution.

See `NOTICE.md` for additional lineage information.

Model weights are not redistributed by this repository and may have separate licensing terms.

---

## Credits

Original Agentopia:  
**Neph0s and Agentopia contributors**

Detroit fork, research direction and project architecture:  
**Professor Timothy E. Bates**

---

## Why Detroit?

Detroit has repeatedly reinvented itself around transformative technology.

Agentopia Detroit explores what happens when AI agents do not simply answer a prompt, but instead have to live with what happens next.

And underneath that simulation is another question:

> **How little compute do we actually need to accomplish useful AI work?**
