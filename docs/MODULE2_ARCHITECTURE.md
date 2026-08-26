# Seismic/Vibration Intelligence — Architecture

**Status:** Schema is live on the real database. FastAPI service is live on
Railway (`/health` confirmed responding). Bronze → silver → gold has run
successfully end to end for the first time (verified locally: 50 real STEAD
traces → 100 labeled, split windows, zero schema/leakage/duplicate issues)
and push-triggering is back on. Replay (the DB-write step) is the one piece
not yet exercised against real data — needs the CI secrets confirmed set.

This is DataSnake's Module 2 — ground-sensor vibration classification,
one of four planned modules turning raw sensor/media data into classified,
governed event records (evidence, confidence, `abstain`,
`requires_human_review`, `scenario_family_id`) surfaced on a shared
dashboard. Originally built inside `datasnake-weather-intelligence`
(alongside an unrelated NOAA/USGS ingestion pipeline) and split into this
dedicated repo once the shared-repo model started causing confusion between
old and new work.

---

## Signal path

```
data/stead_sample/ — small, real, pre-extracted STEAD sample (CC BY 4.0)
  (25 earthquake_local + 25 noise, extracted once, locally, by hand —
   see scripts/extract_stead_sample.py. Not a live SeisBench pull; see
   Troubleshooting for why.)
        v
Bronze  (data/module2_vibration/bronze/, .gitignored — raw samples)
        v  bandpass filter, normalize, window
Silver  (data/module2_vibration/silver/)
        v  label, group by scenario_family_id, split train/val/test
Gold    (data/module2_vibration/gold/)
        v  pretrained PhaseNet, per-class eval
Model registry (models/registry/<name>/metadata.json)   [local metadata, separate from the DB table below]
        v
Replay pipeline (src/02_ml_pipeline/replay_pipeline.py, idempotent upsert)
        v
vibration_classified_events (Supabase Postgres, terrawatchapp's project)  [LIVE — schema applied]
  + one seed row in the existing model_registry table (slug: seismic-vibration-ground)
        v
FastAPI service (src/03_api_service/, GET /events)
        v
terrawatchapp-beta dashboard (hyperlocalwatch.com) — separate repo, separate session
```

**Everything above the database line runs in CI, not on anyone's laptop —
one manual, one-time exception.** Extracting the small local sample
(`scripts/extract_stead_sample.py`) has to run somewhere with enough disk
and bandwidth to hold the full ~14GB source chunks temporarily — that step
was done once, by hand, and its small output (`data/stead_sample/`) is
committed to the repo. Everything downstream of that — bronze, silver,
gold, replay — runs automatically in `.github/workflows/pipeline.yml` on
every push to `main` and on demand.

---

## What's live vs. what's wired-but-unverified

| Stage | State |
|---|---|
| Database schema (`vibration_classified_events` + `model_registry` seed row) | **Live** — applied and verified against the real project |
| Pipeline tests (`src/02_ml_pipeline/tests/`) | **Passing** |
| Bronze/silver/gold | **Verified working end to end** against real data (50 STEAD traces -> 100 windows, zero validation issues) — the CI run is the same code, next push confirms it there too |
| Replay (writes to Supabase) | **Not yet confirmed** — needs `DATABASE_URL`/`DATABASE_POOLER_URL` set as GitHub Actions secrets (separate from Railway's own env vars — see "What you still need to do") |
| FastAPI service | **Live on Railway**, `/health` confirmed responding |
| Frontend surfacing on hyperlocalwatch.com | **Not started** — separate repo (`terrawatchapp-beta`), separate session, consumes `docs/API_CONTRACT_MODULE2.md` |

---

## Database

Target is **terrawatchapp's own Supabase project** — the same one backing
`terrawatchapp-beta` — not a dedicated one, so Module 2 slots into that
app's existing conventions instead of standing up parallel infrastructure.

- **Table**: `vibration_classified_events` — dedicated, purpose-built
  (typed `event_type`, `abstain`, `requires_human_review`,
  `scenario_family_id`, full data lineage). Deliberately *not* folded into
  the existing generic `model_inference_log` table, even though that table
  covers similar ground for other models (`pipeline-detection`, `oil-spill`,
  `seismic-insar`) — kept separate so Module 2 doesn't collapse into a shape
  built for other models' needs.
- **Catalog entry**: one seed row in the existing `model_registry` table
  (`slug: seismic-vibration-ground`, `status: demo`) so Module 2 shows up in
  the already-live `/ai-models` hub UI for free. Naming deliberately
  distinct from the existing `seismic-insar` model — that one is satellite
  InSAR deformation, a different modality entirely.
- **Migration file**: `data/schema/0049_vibration_classified_events.sql` —
  already applied manually via the Supabase SQL Editor (the sandbox this was
  built in couldn't reach the project directly — see Troubleshooting).
  Numbered to match `terrawatchapp-beta/supabase/migrations/`' own sequence,
  since that's the project of record.
- **RLS**: enabled, public-select policy, writes reserved for the
  pooler/service credential — matches every other table in that project.

---

## Hosting

- **Pipeline**: GitHub Actions (`.github/workflows/pipeline.yml`) for
  bronze/silver/gold/replay, by design — the one exception is the one-time,
  by-hand local sample extraction (`scripts/extract_stead_sample.py`),
  which needs disk/bandwidth no CI runner has for a full source download.
- **API service**: Railway, git-triggered deploy from this repo's `main`,
  root directory `src/03_api_service` (`railway.json` already configured).
  Independent of the Vultr box running `datasnake-fastapi-router` /
  `datasnake-sensor-data` — those stay reference-only, unrelated to this repo.
- **Database**: Supabase Postgres, terrawatchapp's project (see above).
  Connect via the **transaction pooler** (port 6543), not the direct host
  (port 5432) — see Troubleshooting.

---

## What you still need to do

Nothing here requires you to write or run code locally — but two things
need a human clicking through a dashboard, since neither can be done from
a coding session:

1. **Add repo secrets** — GitHub repo → Settings → Secrets and variables →
   Actions → add `DATABASE_URL` and `DATABASE_POOLER_URL` (the terrawatchapp
   Supabase pooler connection string, port 6543). Without these,
   `pipeline.yml` will fail at the replay step.
2. **Connect this repo to a Railway project** — Railway dashboard → New
   Project → Deploy from GitHub repo → pick `datasnake-seismic-intelligence`
   → set root directory to `src/03_api_service`. Add `DATABASE_POOLER_URL`
   and `MODULE2_API_TOKEN` as Railway environment variables too (Railway
   doesn't read GitHub Actions secrets — they're separate stores).

---

## Pluggable-module principle (for Module 3/4, later)

`src/03_api_service/app/routers/events.py` has no seismic-specific logic —
just `GET /events`, `GET /events/{id}` reading a governance-shaped row.
Seismic-specific code lives entirely under `app/modules/seismic/`. A future
module (coastal visual, infrastructure condition) should be able to write
into its own table and reuse the same route shape without touching
`events.py`, provided its output conforms to the same governance fields
(`evidence`, `confidence`, `abstain`, `requires_human_review`,
`scenario_family_id`).

---

## Troubleshooting log

- **Direct Postgres host resolves IPv6-only.** `db.<ref>.supabase.co:5432`
  has no IPv4 address unless the project has the IPv4 add-on. Use the
  **transaction pooler** host instead (`aws-<n>-<region>.pooler.supabase.com:6543`
  — Dashboard → Connect → Transaction pooler tab).
- **Raw-TCP database connections don't work from a locked-down dev
  sandbox** — confirmed against that sandbox's own documented network
  policy, not a bug. This is the reason the pipeline runs in GitHub Actions
  rather than requiring anyone's laptop — CI runners have normal outbound
  access.
- **Verify which project a connection string actually points to before
  trusting it.** One shared early in this build turned out to be a
  different, unrelated Supabase project (a podcast/media product — tables
  like `brands`, `voice_clones`, no `model_registry`). Caught via
  `select tablename from pg_tables where schemaname = 'public'` before
  anything was written. Worth re-running any time credentials change hands.
- **Railway auto-detection needs an exact `requirements.txt` and `railway.json`
  at repo root.** A build failed with "could not determine how to build the
  app" because the one dependencies file was named `requirements-ml.txt`
  (Railway's Nixpacks/Railpack only recognizes the exact name) and
  `railway.json` lived in a subdirectory Railway never scanned without a
  Root Directory override. Fixed by renaming the file and moving the config
  to root with an explicit `buildCommand` — no Root Directory setting needed.
- **Resolved: SeisBench's STEAD/Iquique loaders genuinely have no
  partial-download option.** Confirmed by an actual CI run hitting an
  84.9GB download target regardless of `sample_size`, then verified against
  SeisBench's own source: STEAD's loader has no `chunks` parameter and
  always fetches the merged ~85GB file; Iquique's `_download_dataset` isn't
  even implemented. Separately confirmed from the original source
  (`github.com/smousavi05/STEAD`) that the dataset genuinely is split into
  6 chunks (~14-16GB each) — SeisBench's Python loader just doesn't expose
  that. Fix: downloaded two chunks directly from the original source (one
  `noise`, one `earthquake_local`) on a local machine, extracted 25 examples
  of each with `scripts/extract_stead_sample.py`, and committed the small
  (~3.7MB) result to `data/stead_sample/`. `bronze_ingest.py` and
  `silver_clean.py` now read from that directly — no SeisBench download
  call anywhere in the automated path. Verified end to end: 50 real traces
  -> 100 labeled, split windows, zero schema/leakage/duplicate issues.
  One real gotcha this surfaced: the raw HDF5's waveform shape is
  `(samples, channels)`, not `(channels, samples)` — transposed once in
  `local_sample.py` so the rest of the pipeline didn't need to change.
- **Supabase free-tier quota exceeded by a pre-existing, unrelated table,
  not by Module 2's own data.** `measurements` (ocean/weather buoy
  time-series, unrelated to this module) had grown to 1.6M rows / 423MB —
  nearly the entire database. Fixed for free by deleting raw rows older
  than 30 days (the app's own `measurements_series()` RPC never reads raw
  rows past 36 hours anyway — it already switches to the pre-aggregated
  `measurements_hourly` view beyond that window, so old raw rows were dead
  weight) followed by `vacuum full measurements` to actually reclaim the
  disk space (a plain `DELETE` does not shrink the file on its own). Dropped
  the database from ~568MB to ~110–150MB. Reference queries for this kind of
  investigation: `data/analysis/vibration_classified_events_queries.sql`.

---

## Known Phase 1 limitations

- `vehicle_human` event type has no labeled training data yet (STEAD/INSTANCE
  don't cover it) — see `src/02_ml_pipeline/gold_label_split.py`.
- No live sensor — `replay_pipeline.py` replays public gold-layer data
  instead.
- `datasnake-fastapi-router`'s `datasnake.io/datapreview` outage is a
  separate, pre-existing issue on unrelated infrastructure, out of scope
  here.
