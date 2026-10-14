# Agentopia Detroit visualization baseline v2.0.19

Accepted October 14, 2026: v2.0.19 is the **base visualization** for Agentopia Detroit. The user's working Mac browser showed mapped streets, Detroit River, buildings, and 54 live residents at the time of acceptance.

Source lives under `live_world/static/city-geo/`. Use `index.html?era=2045&gpu=webgl2&v=219` served by Agentopia's local observer. This is **not a standalone runnable world**: the viewer loads locally provisioned GIS data under `city-geo/data/`, Detroit era packs under `city-geo/packs/`, and separately installed Three.js dependencies under `city-v2/vendor/`. Those larger/private runtime datasets were deliberately not committed. Preserve and validate them on each installation.

**Do not regress:** validated Detroit River and Belle Isle boundaries, mapped road geometry, correct X-east/Z-south projection, observer `/api/snapshot` resident overlay, inline editor, 14-era controls, WebGL2 safe default, source-linked historic massing, no forced redirect to old safe mode.

**Next stage:** geographically correct Ambassador Bridge, Gordie Howe International Bridge, MacArthur Bridge and related approaches; their 3D geometry, locations, periods, and assets must be validated before activation. No bridge changes are included in this baseline commit.

**Scope:** visualization source only. This does not alter the city engine, checkpoints, AI models, simulation, society, economy, or the running Mac instance. Historical eras before 2045 are not to include invented speculative architecture. 2045 may be future-inspired.

**Limitations:** the recorded shoreline guard and historic building models remain approximate, not surveyed/photogrammetric. The observer's street-level resident positions are inferred where GPS is unavailable.

**Release provenance:** sourced from `AGENTOPIA-DETROIT-v2.0.19-UNIFIED-BOOT-REPAIR.zip`, whose modules were byte-identical to the accepted version. CSS dependencies were taken from v2.0.17 and the v2.0.3 geography package, respectively.
