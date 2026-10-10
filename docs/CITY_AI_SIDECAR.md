# Optional AI Adviser for Multiple City Sandboxes

The City AI Coordinator is an **opt-in experimental sidecar** to the isolated City Sandbox. It samples up to eight synthetic residents per call, asks a local OpenAI-compatible model (default 127.0.0.1:8081) for a constrained fictional activity, and writes proposals to `city_ai/decisions.json`.

**It does not execute activities, modify resident state, run Detroit's engine, or enable AI autonomy.** It falls back to `rest` when model output is invalid or model service is offline. It allows localhost HTTP only and makes bounded requests. Test independently for Chicago and Flint.

From a clone with an initialized City Sandbox:

```bash
python3 scripts/city_ai_coordinator.py data/city_imports/city_chicago
python3 scripts/city_ai_coordinator.py data/city_imports/city_chicago --live
python3 scripts/test_city_ai_coordinator.py
```

The first command is **read-only preview**. The second requires a compatible local LLM server and creates `city_ai/decisions.json` without altering canonical `sandbox_runtime/state.json`. The sidecar is idempotent per world/tick/cohort/model. Run city sandboxes and advisers separately by world. Never point external model URLs here.

Next prerequisites for true AI-controlled multi-city simulation: a per-city transaction coordinator, engine-wide world-path injection, lifecycle/economy/mobility adapters, lineage/faction scoping, events and checkpoint replay tests, and multi-writer locks. The Detroit persistent engine still uses Detroit-specific paths and is not launched by these commands.
