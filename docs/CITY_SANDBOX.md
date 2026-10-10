# City Sandbox v1 — runnable, isolated preview

**Status:** Runnable deterministic synthetic-resident simulation with independent checkpoints and read-only web viewer. **Not** full Detroit AI-engine parity, and does not use language models.

## Create Chicago in a clean clone

In City Builder (`live_world/static/city-builder.html`), discover/edit Chicago and export `agentopia-city-chicago.json`. Then from the repository root:

```bash
python3 scripts/import_city_manifest.py ~/Downloads/agentopia-city-chicago.json
python3 scripts/run_city_sandbox.py init data/city_imports/city_chicago --population 32
python3 scripts/run_city_sandbox.py step data/city_imports/city_chicago --steps 4
python3 scripts/run_city_sandbox.py serve data/city_imports/city_chicago --port 8777
```

Open http://127.0.0.1:8777. To advance automatically instead of manual `step`, stop the separate `serve` process and run:

```bash
python3 scripts/run_city_sandbox.py run data/city_imports/city_chicago --port 8777 --interval 3
```

Create Flint using the same process with `city_flint` and use a **different port** (for example, 8778). Each city uses its own `sandbox_runtime/state.json`; checkpoint writes are atomic. Existing staging directories and initialized sandbox states are not overwritten.

Run offline tests:

```bash
python3 scripts/test_city_sandbox.py
```

## Important boundaries

- City residents are synthetic test fixtures (`Resident 001`, etc.) with deterministic schedules, not autonomous reasoning agents.
- Only the Chicago/Flint manifest geography and institution names are consumed. There is no complete navigable street graph or city-government system.
- This launcher never imports or starts `run_detroit_persistent.py`, never copies Detroit citizens and never modifies `data/detroit_persistent`. It binds its viewer only to localhost.
- The standalone HTTP viewer shows recent synthetic resident activities through a read-only endpoint.
- Do not run two writers against the **same** sandbox folder concurrently. A cross-process writer lock is a future hardening gate.
- A future full multi-city engine requires parameterizing all Detroit-specific managers, data paths, checkpoint ownership, model-server allocation and observer routing, followed by reproducible cross-city isolation tests.

The current milestone demonstrates **city choice → geographic import → independent runnable preview → persistent state → read-only viewing**. It does not claim complete one-shot AI civilization conversion.
