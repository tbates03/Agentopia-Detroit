# City Builder — community testing MVP

City Builder is an **adjacent, read-only web page** in Agentopia Detroit. It discovers and edits a small geographic sample for a city using OpenStreetMap services and exports an `agentopia.city.manifest.v1` JSON file.

**Not yet implemented:** creating an isolated, runnable Chicago/Flint world, converting an existing live world, retrieving complete road geometry, importing population, or launching a 3D city. Do not upload a private Detroit world database.

## Quick start (no running simulation required)

From a clean clone:

```bash
git clone https://github.com/tbates03/Agentopia-Detroit.git
cd Agentopia-Detroit
python3 -m http.server 8766 --bind 127.0.0.1 --directory live_world/static
```

Open **http://127.0.0.1:8766/city-builder.html**. The main City Builder link in `index.html` works with the existing observer too; the preview itself is a static HTML page with no Agentopia engine dependency.

The discovery buttons require internet and access to third-party Nominatim and Overpass APIs. Those public services may deny browser CORS, rate-limit traffic, or be unavailable. Manual entry and JSON preview/export work even if those services fail. Avoid automated request floods.

## Contributor smoke test

1. Open the City Builder page and enter `Chicago, Illinois, USA`.
2. Select **Discover city** and verify name/country/coordinates, or enter these manually if geocoding fails.
3. Choose radius 1 km and **Fetch streets & places** if Overpass is reachable. This is a bounded sample near a central point, not a complete city.
4. Review and edit names. Enter `America/Chicago` only after validating the selected jurisdiction/time zone.
5. Click **Preview JSON** then **Download city manifest JSON**.
6. Confirm schema `agentopia.city.manifest.v1`, custom world ID, geography arrays, source provenance, and `deployment.mode = staging_only`.
7. Confirm Detroit state was not modified (City Builder has no write endpoint).

Repeat with `Flint, Michigan, USA` or another city and report mismatches and regional differences.

## Run automated checks

```bash
python3 scripts/test_city_builder.py
```

Python 3 standard library is enough. When Node.js is installed, the checker also runs `node --check` against the inline JavaScript.

## Data provenance and licensing

Data: © OpenStreetMap contributors, ODbL. Geocoding by Nominatim; street/place sampling by Overpass. Export includes provenance entries; check relevant API usage rules, attribution, database rights and ODbL/share-alike obligations. Geographic facts must be distinguished from fictional simulation projections. Review name spelling and completeness manually.

## Roadmap: one-shot city generation

A future importer will validate a manifest, resolve each city's world-specific modules and climate/calendar packs, generate a **new isolated world directory**, run migration/consistency tests, and activate only with explicit consent and checkpoint safety. Shared engine paths currently assume `data/detroit_persistent` and must be parameterized before full city generation is safe.

For planned 3D voxel/Unreal clients see [Detroit 3D World Roadmap](DETROIT_3D_WORLD_ROADMAP.md).

## Feedback

When filing a PR/discussion, include target city, browser, whether Nominatim/Overpass succeeded, export schema validation, attribution concerns and any reproducible error. **Do not include personal data, credentials or private city state.**
