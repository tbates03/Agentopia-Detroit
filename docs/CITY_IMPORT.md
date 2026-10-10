# City Import Engine — Stage 1

**State: staging importer delivered; multi-city simulation launch NOT enabled.**

City Builder creates an editable city manifest from Nominatim / OpenStreetMap samples. This CLI validates a downloaded manifest and creates a **new, isolated city staging directory**. It never reads or copies the existing Detroit citizen database, never starts an engine, and refuses to replace existing targets.

## One-time city import from the web page

1. Run the Live World observer or `python3 -m http.server 8766 --bind 127.0.0.1 --directory live_world/static`.
2. Open `http://127.0.0.1:8766/city-builder.html`.
3. Select Chicago, Flint, or another city, discover its center, import a bounded OSM sample, edit and verify names, then download `agentopia-city-<id>.json`.
4. Dry-run first:

```bash
python3 scripts/import_city_manifest.py ~/Downloads/agentopia-city-chicago.json --dry-run
```

5. Stage:

```bash
python3 scripts/import_city_manifest.py ~/Downloads/agentopia-city-chicago.json
```

The default output is `data/city_imports/city_chicago/` relative to the repository. This folder contains `manifest.json`, `profile.json`, `geography.json`, `import_report.json`, and `DO_NOT_LAUNCH.txt`.

**Do not commit generated city directories without reviewing names, licensing, provenance and privacy.** Keep local files out of source control; use public research packs for reviewed contributions.

## Why launching is still blocked

The current persistent runner, `scripts/run_detroit_persistent.py`, explicitly binds to `data/detroit_persistent`, alters Detroit-specific `world.name` and `data_dir`, and calls Detroit-scoped managers. Redirecting that script to Chicago without parameterizing every world-specific service could corrupt Detroit or create inconsistent economies and resident locations. **This importer intentionally sets `launch_ready: false`.**

Needed before enabling a launch button:
- Inject and validate `world_id` and world directory across runner, growth manager, city context, geography governor, mobility, business, finance, healthcare, family and renderer.
- Generate a new population and persona configuration (not copies of real or private Detroit biographies), location graph, jobs and institutions with consistency tests.
- Turn OSM *named sample* into real directed routing geometry with neighborhood boundaries; add licensing and attribution review.
- Implement an isolated per-world checkpoint, launchd/port strategy, lock, model pool selection and boot smoke test.
- Test multi-world simultaneous operation, restart recovery, non-contamination and explicit user approval.

## Run importer unit tests

```bash
python3 scripts/test_city_import.py
```

The test checks dry run, successful isolated staging, duplicate import rejection, manifest validation, path traversal, reserved Detroit ID and schema counts.

For City Builder web tests see [City Builder](CITY_BUILDER.md).
