# DataSnake Seismic Intelligence

Ground-sensor vibration classification: turns waveform data into classified
events (seismic / vehicle-human / environmental / unknown) with confidence
scores, then serves them to DataSnake's monitoring dashboard.

Full architecture, current status, and troubleshooting notes:
**[docs/MODULE2_ARCHITECTURE.md](docs/MODULE2_ARCHITECTURE.md)** — start there.

For the problem this is actually solving, the reasoning behind how it's
built, and an honest read on current maturity:
**[docs/PROBLEM_AND_APPROACH.md](docs/PROBLEM_AND_APPROACH.md)**.

For what the data actually looks like at each pipeline stage, tied to the
exact code that produces it:
**[docs/DATA_FLOW_WALKTHROUGH.md](docs/DATA_FLOW_WALKTHROUGH.md)**.

## Layout

```
src/02_ml_pipeline/    bronze -> silver -> gold -> replay pipeline, + tests
src/03_api_service/    FastAPI service (GET /events), deploys to Railway
notebooks/module2_seismic/   same pipeline stages, for interactive/EDA use
data/schema/            SQL migrations for the vibration_classified_events table
.github/workflows/       CI: tests on every push, full pipeline on push + on demand
```

## Nothing here needs to run on your machine

Push to `main` and GitHub Actions runs the tests, then the pipeline
(`.github/workflows/pipeline.yml`), end to end — also runnable on demand
from the Actions tab. Bronze/silver/gold read a small, real, pre-extracted
local sample rather than pulling live (see docs/MODULE2_ARCHITECTURE.md's
troubleshooting log for why). Railway redeploys the API on every push to
`main`. See "What you still need to do" in
[docs/MODULE2_ARCHITECTURE.md](docs/MODULE2_ARCHITECTURE.md) for the two
one-time dashboard setup steps (repo secrets, Railway connection) that
can't be done from a coding session.

## API contract

Frontend integration doc for the `terrawatchapp-beta` team:
[docs/API_CONTRACT_MODULE2.md](docs/API_CONTRACT_MODULE2.md).
