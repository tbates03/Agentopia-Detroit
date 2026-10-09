# Agentopia

**English** | [简体中文](docs/README.zh.md) | [日本語](docs/README.ja.md) | [한국어](docs/README.ko.md)

**Agentopia** is a framework for long-term life simulation in multi-agent societies. Agentopia simulates human social life across years: In our experiments, 100 agents autonomously take part in social life over 10 simulated years. 
They set and pursue their own goals, develop and fulfill their needs, and interact with other agents to build relationships within the society.

It is built around two questions: can we build an AI agent society where agents effectively simulate human life, and can experience and rewards from such a society improve LLMs' capabilities? To the latter end, we define a *life reward* that mirrors human well-being — social standing, subjective fulfillment, and economic status — and use it to train large language models, improving their anthropomorphism and role-playing ability.

---

## Overview

Agentopia simulates human social life at the scale of years. Each agent:

- Sets and pursues personal goals, develops skills, and engages in economic activities
- Develops and fulfills needs across mood, material, and social dimensions
- Interacts with other agents to build relationships within the society
- Manages its long-term memory along the way
- Lives through a weekly cycle: **Plan → Contact → Activity → Review**
- At each year-end, updates its profile, applies for new careers, and receives a *life reward* reflecting social standing, subjective fulfillment, and economic status

An **environment model** (a capable LLM) serves as the generative engine orchestrating the simulation — verifying agent responses, providing feedback, and scheduling events — without hard-coded rules.

## Repository Structure

```
├── config.example.json     # Configuration template (copy to config.json and fill in)
├── requirements.txt
├── data/
│   ├── apartment/          # Example world: modern apartment complex
│   ├── school/             # Example world: school setting (chinese high school)
│   └── persona_template/   # Template for persona data format
├── scripts/
│   ├── run_world.py        # Main entry point for running a simulation
│   ├── build_rft_data.py   # Compute advantages + build RFT training data
│   ├── compute_metrics.py  # Quantitative per-agent / per-year metrics for a run
│   ├── time_analysis.py    # Per-week wall-clock timing for a run
└── src/
    ├── agents/             # Role-playing agent: prompts, context, memory
    └── world/              # Simulation engine: scheduling, activities, rewards
```

## Getting Started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp config.example.json config.json
```

Edit `config.json`:
- Set `world.name` to the world you want to run (e.g. `apartment`, `school`)
- Set `role_model` and `god_model` to model names defined in `models`
- Fill in API keys and endpoints for the models you want to use
- Adjust `world.time.n_year` to control the length of the simulation
- Set `fallback_model` to a model used if the primary call fails (e.g., the response cannot be correctly parsed)
- Tune `max_concurrency` to control the maximum number of parallel LLM requests

### 3. Run a simulation

```bash
python scripts/run_world.py
```

To override the world at runtime:

```bash
python scripts/run_world.py --world apartment
```

## Model Configuration

Agentopia supports multiple LLM backends. Configure them in `config.json` under `models`:

| Backend | Required fields |
|---|---|
| OpenAI-compatible (vLLM, local) | `url`, `api_key`, `vllm_model_name` |
| Anthropic (Claude) | `api_key`, `anthropic_model_name` |
| Google Gemini (Vertex AI) | `credentials_file`, `project`, `location` |
| Azure OpenAI | `url`, `api_key`, `api_version` |

For thinking-capable models served via vLLM, set `"enable_thinking": true` in the model config.

## Simulation Data Layout

Each run gets its own directory under `data/`, named `worldname_MMDDHHMM` (e.g.
`school_06031205`). On start it is copied from the base world (e.g. `data/school/`),
then all simulation output is written into it. Data is append-only JSONL except for
profiles and config files. 

```
data/<world>_<MMDDHHMM>/      # One run directory (copied from base world data/<world>/)
├── config.json               # Effective config for this run (CLI overrides applied)
├── checkpoint.json           # Resume checkpoint (last completed year/week/stage)
├── worldview.json            # World setting / background
├── positions.json            # Generated available career positions
├── locations.json            # Generated map
├── public_events.jsonl       # World-level public events
├── persona/<name>/           # Per-agent data
│   ├── profile/year=<YYYY>.json   # Yearly profile snapshot
│   ├── state.jsonl                # Vitality, fulfillment, skills, assets over time
│   ├── schedule.jsonl             # Weekly schedules
│   ├── activity.jsonl             # Activity outcomes
│   ├── reward.jsonl               # Per-agent reward results (social/subjective/economy/total)
│   ├── generation/year=<YYYY>/week=<W>.jsonl   # Raw LLM generation traces
│   ├── memory/
│   │   ├── weekly_diary.jsonl     # Weekly diary entries
│   │   ├── history.jsonl          # Long-term life history
│   │   └── scratchpad/            # Memory files the agent autonomously manage during simulation
│   │       ├── general.jsonl          # Core notes: long-term goals, plans, progress, todos, reflections, e.t.c.
│   │       ├── characters/<person>.jsonl   # Per-person notes: knowledge of the other character and the agent's view of their relationship (one file per character)
│   │       └── others/<thing>.jsonl        # Notes on other topics (one file per topic)
│   └── contact/<person>.jsonl     # Agent-to-agent message logs
├── reward/                   # World-level reward data
│   ├── rankings/year=<YYYY>/week=<W>.jsonl   # PageRank inputs (affection/respect)
│   ├── metrics/year=<YYYY>/week=<W>.jsonl    # Computed reward metrics per agent
│   └── advantages.jsonl                      # Trajectory returns + per-period advantages
└── god/<feature>/year=<YYYY>/week=<W>.jsonl  # Environment-model generation traces
```

## Life Reward Training

A primary goal of Agentopia is to improve the anthropomorphic role-playing
ability of LLMs through social simulation. To that end, `scripts/build_rft_data.py`
selects, from a finished simulation, the high-advantage trajectories (see Section 4
of the paper) and packages them into training data. 
It measures agents' life-reward and calculates returns and advantages,
selects the highest-advantage trajectories, and collects their generation traces into a
training set.

```bash
python scripts/build_rft_data.py --data-dir school_06031205 --top 0.25 
```

Key arguments:

- `--data-dir` (required): a specific simulation run directory under `data/`, named
  `worldname_<runid>` (e.g. `school_06031205`) — **not** the base world name `school`.
- `--top`: fraction of top trajectories to keep per period (defaults to
  `world.reward.rft_top_fraction` in `config.json`).
- `--n-year`: restrict selection to the first N simulated years.

Outputs (under `rft_data/`):

- `rft_data/<data-dir>_Y<year>W<week>.jsonl` — training samples
- `rft_data/<data-dir>_Y<year>W<week>.md` — statistics report on the selected training samples
- `rft_data/god_<data-dir>_Y<year>W<week>.jsonl` — sampled environment-model
  generation data (only if `data/<data-dir>/god/` exists)

## Analysis Skills

The repo ships a set of [Claude Code](https://claude.com/claude-code) skills under
`.claude/skills/` for inspecting a finished run. When working in Claude Code, invoke a
skill by name (e.g. `analyze run school_06031205`); each skill also lists trigger
phrases in its `SKILL.md` frontmatter.

| Skill | What it does |
|---|---|
| `analyze-run` | Qualitative deep-dive into a run — agent experiences, inner journey, personality growth — producing system-level and per-agent reports under `data/<run>/run_analysis/`. |
| `run-metrics` | Quantitative metrics for a run (tokens, contacts, activities, spending, skills, fulfillment, social eval). Wraps `scripts/compute_metrics.py`; writes `analysis/results/<run>_metrics.json`. |
| `analyze-activity` | Checks whether agents' activity-phase utterances read like a real human, against the criteria in `analyze-activity/PRINCIPLES.md`. Uses `scripts/extract_activity_dialogues.py`. |
| `time-analysis` | Reports per-week wall-clock time consumed by a run, parsed from `logs/<run>/world.log`. Wraps `scripts/time_analysis.py`. |

These skills are optional analysis helpers; they are not required to run a simulation.

## License

This project is released under the MIT License.
