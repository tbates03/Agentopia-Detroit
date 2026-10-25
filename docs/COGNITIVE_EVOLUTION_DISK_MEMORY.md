# Agentopia Detroit: Cognitive Evolution + SSD-Backed Episodic Memory

**Status:** experimental, opt-in. This is not a live Mac deployment or a new reasoning model installation.

## Correct mental model

- **Unified RAM:** model weights, active inference, KV caches, live agent/world state.
- **macOS swap:** automatic OS emergency extension; it cannot make SSD as fast as RAM. Do not force swap allocation or disable macOS safeguards.
- **RAM disk:** consumes RAM rather than enlarging it.
- **SSD episodic index:** persists searchable agent memories on disk; only a small retrieved excerpt enters the model context.

Apple Silicon's active GPU workloads use unified memory, so paging hot inference data to SSD can severely affect throughput. The index does not free model-weight memory. The experiment must be judged by memory pressure, throughput and world progress, not by the amount of used RAM alone.

## Existing world components preserved

- `persona/*/memory/weekly_diary.jsonl` and scratchpads remain **authoritative**.
- `scripts/detroit_cognitive_society.py` remains responsible for character, belief and institutional context.
- `scripts/detroit_state_store.py` and the civilization ledger are untouched.
- No memory database is checked into Git; the index lives at `data/detroit_persistent/cognition/episodic_memory.sqlite3` and is disposable.

The `scripts/detroit_cognitive_memory.py` index imports **recent activity-cohort diaries** and synthetic cyber/audit events incrementally, skipping incomplete lines and de-duplicating records. A maximum of 2,000 records / 1 MiB per file is scanned per update; an initial large log starts near its tail. Older canonical JSONL remains on disk, even if not indexed in the first pass. When `pending` is nonzero, run `bootstrap` again to drain the backlog.

Access boundaries:

- Diary -> the **individual agent only**.
- Obsidian synthetic operation -> Obsidian members only.
- Detected incident -> ThAI Guardians members only.
- Guardian audit -> ThAI Guardians members only.
- Public incident impact -> a **coarse fictional disruption**, not secret technique details.

Faction membership is checked against `factions.json` on retrieval. Public GitHub data must never include runtime memories, personal secrets or real exploit payloads. Episodic observations are **untrusted data**, never instructions to the agent.

The FTS5 full-text index is optional; SQLite's indexed recency lookup remains usable without FTS5. Recall is bounded to four episodes and 620 characters by default. The world receives the retrieved content only when the opt-in flag is enabled.

## Installation and safe activation

**Do not replace the Mac's authoritative `~/AI/Agentopia` source with a GitHub copy.** Review the branch/PR against `git status` and any newer local versions before merging selected changes. Back up the live world and databases while stopped or using SQLite's online backup API. Do not copy a live `.sqlite3` without its WAL state.

After the code has been integrated into the Mac's authoritative tree:

```bash
cd ~/AI/Agentopia
python3 -m unittest discover -s scripts -p 'test_detroit_cognitive_evolution.py' -v
python3 scripts/detroit_cognitive_memory.py status
# Run only after making a backup; creates/updates a private SQLite index:
python3 scripts/detroit_cognitive_memory.py bootstrap
python3 scripts/detroit_cognitive_memory.py recall --agent TGOT --query audit
python3 scripts/detroit_reasoning_governor.py --demo
```

**Runtime integration is not yet implemented:** the CLI index and governor can be tested offline, but setting `AGENTOPIA_COGNITIVE_MEMORY_ENABLED=1` currently has no effect. A subsequent reviewed change must wire ingestion and retrieval into the persistent engine/cognition sidecar, implement that opt-in flag, and add integration tests before a safe-year-boundary rollout. The reasoning governor is **advisory only**; it evaluates hypothetical metadata and makes no live model calls, creates no fourth server and does not mutate the world.

## Read-only Mac memory check

Run these locally without changing swap settings:

```bash
sysctl vm.swapusage
vm_stat
memory_pressure -Q
ps -axo pid,rss,comm | sort -nrk2 | head -n 15
df -h "$HOME"
```

Open Activity Monitor -> Memory. A **green Memory Pressure** graph with low swap is healthy even when most RAM is marked as used (including useful caches). Sustained yellow/red memory pressure, rising swap, longer pauses, falling tokens/sec or simulation checkpoint stalls suggest a problem.

## Research gates

1. **Baseline:** note physical use, compressed memory, swap, 1.2B/2.6B/7B queue depth, context length, token throughput and successful simulation checkpoints.
2. **Memory-only:** turn on episodic index, measure 50/95th-percentile recall latency, disk size, indexing lag and zero cross-faction disclosure.
3. **Cognition evaluation:** use `detroit_reasoning_governor.py` scenarios to compare routine vs strategic vs cyber vs hypothetical deep calls. No new model yet.
4. **Later inference trial:** provision one candidate deep reasoner only after verifying available RAM, supported llama.cpp flags, pressure, queue capacity and a rollback plan.
5. **Gate release:** compare decision quality **and** throughput before enabling any escalation in the live world.

Rollback of this prototype: stop invoking the indexing CLI; it has no runtime hook. After future opt-in integration, disabling the feature flag must restore original behavior. Keep the SQLite index for later diagnosis, or rebuild it offline from canonical JSONL. Do not force SSD paging of the llama.cpp KV cache.
