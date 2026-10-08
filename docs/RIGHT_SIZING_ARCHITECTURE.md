# Agentopia Detroit: Right-Sized Local AI Architecture

## Purpose

Agentopia Detroit is a persistent multi-agent simulation and a systems experiment in **right-sized local AI**.

The experiment asks:

> **What is the smallest model that can reliably perform the task?**

Instead of assigning every workload to one large model, Agentopia Detroit separates classes of work and maps them to different local model tiers.

The objective is not "small models at all costs."

The objective is **smallest sufficient model, with escalation when additional capability is justified**.

---

## Research Hypothesis

Many persistent-agent workloads can be served by relatively small local models when:

1. work is decomposed into narrower tasks,
2. models are selected according to task complexity,
3. persistent state exists outside the model,
4. structured systems reduce the amount the model must infer from scratch,
5. stronger reasoning is used only where it adds value.

A persistent world is intentionally demanding because it produces continuous heterogeneous work rather than a single benchmark prompt.

---

## Current Model Tiers

The current three-pool local configuration is defined in `scripts/start_detroit_llama.sh`.

### Social pool

- Repository: `LiquidAI/LFM2.5-350M-GGUF`
- GGUF: `LFM2.5-350M-QAD-Q4_0.gguf`
- Alias: `agentopia-social`
- Default port: `8084`
- Intended work: high-frequency lightweight interactions

### Citizen pool

- Repository: `LiquidAI/LFM2.5-1.2B-Instruct-GGUF`
- GGUF: `LFM2.5-1.2B-Instruct-QAD-Q4_0.gguf`
- Alias: `agentopia-citizen`
- Default port: `8081`
- Intended work: routine dialogue and citizen reasoning

### Strategy pool

- Repository: `LiquidAI/LFM2.5-2.6B-GGUF`
- GGUF: `LFM2.5-2.6B-QAD-Q4_0.gguf`
- Alias: `agentopia-strategy`
- Default port: `8082`
- Intended work: planning, strategy and higher-complexity tasks

### Optional specialist pool

Agentopia Detroit also contains an optional cyber-specialist launcher. It is deliberately separate from the three core pools so the primary demonstration can run without a larger specialist model.

---

## Automatic Hardware Profiles

The local launcher supports four profile names:

```text
auto
light
balanced
performance
```

`auto` detects available system memory and chooses a profile.

Current defaults:

| Profile | Context | Social Slots | Citizen Slots | Strategy Slots |
|---|---:|---:|---:|---:|
| light | 8192 | 8 | 4 | 2 |
| balanced | 12288 | 16 | 8 | 4 |
| performance | 16384 | 48 | 32 | 8 |

These are experimental operating profiles, not universal performance guarantees.

Override the profile:

```bash
AGENTOPIA_PROFILE=light bash scripts/start_detroit_llama.sh
```

Or override individual values:

```bash
AGENTOPIA_CONTEXT_TOKENS=8192 \
AGENTOPIA_SOCIAL_SLOTS=8 \
AGENTOPIA_CITIZEN_SLOTS=4 \
AGENTOPIA_STRATEGY_SLOTS=2 \
bash scripts/start_detroit_llama.sh
```

---

## First-Run Model Behavior

The model weights are not committed to the Agentopia Detroit repository.

For each configured pool, the launcher first searches common local caches and `$AGENTOPIA_HOME/models`.

If the requested GGUF is not found, the launcher uses the `llama-server -hf` mechanism with the configured repository and file.

This keeps the Git repository small and separates application code from third-party model distribution.

Users remain responsible for the license and usage terms of the models they choose.

---

## Architectural Pattern

```text
                         TASK
                          |
                          v
                 CLASSIFY / ROUTE
                   /      |      \
                  /       |       \
                 v        v        v
               350M     1.2B     2.6B
              SOCIAL   CITIZEN  STRATEGY
                 \        |        /
                  \       |       /
                   v      v      v
                  PERSISTENT WORLD
                         STATE
```

A future direction is dynamic escalation:

```text
small model
    |
    +-- sufficient --> accept result
    |
    +-- insufficient --> larger/specialist model
```

---

## Why Persistence Matters

A chatbot can forget the cost of a poor answer after one interaction.

A persistent society cannot.

Agentopia Detroit carries consequences forward through:

- memory
- relationships
- employment
- finances
- businesses
- education
- healthcare
- mobility
- factions
- missions
- public events
- checkpoints

That makes persistent simulation useful for studying both model behavior and architecture under sustained load.

---

## Performance Questions

The project is intended to measure:

### Compute

- CPU utilization
- GPU utilization where available
- system/unified memory
- model memory footprint
- concurrency
- queue depth

### Inference

- requests per model
- tokens per second
- latency
- time to first token
- context utilization
- retries
- truncations
- failed generations

### Orchestration

- percentage of work completed by each tier
- escalation rate
- fallback rate
- model saturation
- successful task completion per unit of compute

### Persistent World

- active citizens
- phase duration
- wall-clock time per simulated week
- activities completed
- conversations generated
- state writes
- financial transactions
- mobility events
- public events
- checkpoint/recovery behavior

The important question is not simply:

> Which model is fastest?

It is:

> **What amount of compute was required to complete the workload reliably?**

---

## Michigan AI Symposium Demo

Agentopia Detroit is being prepared as a live example of right-sized AI architecture for the **2026 Michigan AI Symposium**.

The proposed demonstration combines two views:

### 1. The society

Visitors see citizens:

- talking
- remembering
- working
- learning
- traveling
- spending
- forming relationships
- reacting to world events

### 2. The machine

At the same time, performance telemetry shows:

- which model tier is busy
- request counts
- latency
- throughput
- memory use
- CPU/GPU utilization
- model saturation
- local-vs-escalated workload distribution

The purpose is to connect:

```text
AI behavior + architecture + compute + performance
```

rather than demonstrating only a chatbot response.

---

## Beyond Agentopia

The same principle can apply to everyday local AI workloads:

- inbox triage
- email classification
- scheduling
- local document search
- document routing
- routine summarization
- structured extraction
- office administrative work
- personal knowledge systems
- local assistants

Agentopia Detroit intentionally uses a difficult persistent society as a stress test for an idea that may be useful in much simpler systems.

---

## Core Principle

> **Use the smallest model that can reliably perform the task. Escalate only when necessary.**

## Core Question

> **How much intelligence can we keep local?**
