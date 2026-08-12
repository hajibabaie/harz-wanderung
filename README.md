# Harz Wanderung — Saturday trip planner

Plans Saturday day-trips to collect all 222 Harzer Wandernadel stamps,
starting from Clausthal-Zellerfeld. Built stage by stage; every stage
caches its work, so re-runs are cheap.

## Status

- [x] Step 1 — stamp data (`data/stamps.geojson`, 222/222 recovered)
- [ ] Step 2 — walking network + elevation
- [ ] Step 3 — cluster stamps into day-trips
- [ ] Step 4 — route each trip (TSP + parking)
- [ ] Step 5 — rank trips, write plan.csv / GPX / map / progress list

## Setup

Needs [uv](https://docs.astral.sh/uv/). Then:

    uv sync

## Run Step 1 again

    uv run python -m harzplan.acquire

- The official GPX ZIP is cached at `cache/hwn_gpx.zip`.
  Delete that file to force a fresh download (for example when the
  official site publishes a new year's file — then also update
  `gpx_url` in `config.toml`).
- Output: `data/stamps.geojson` plus a recovered/missing report.
  The script never invents coordinates; gaps stay visible.

## Mark stamps as done

After a hike, add the collected stamp numbers to `config.toml`:

    [progress]
    done = [1, 5, 12]

Later planning stages skip these stamps and re-plan the rest.

## All settings

Everything lives in `config.toml`: home coordinates, loop length
limits (10–18 km), max ascent (600 m), stamps per trip. No magic
numbers in code.

## Data license

Stamp coordinates come from harzer-wandernadel.de (prepared by
Markus Gründel). Free for private personal use only — keep this
repository private and do not redistribute the data.
