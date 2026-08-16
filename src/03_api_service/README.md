# Module 2: Seismic/Vibration Intelligence — API Service

FastAPI service exposing classified vibration events. Deployed to Railway,
independent of the Vultr-hosted `datasnake-fastapi-router` (a deliberately
separate stack — see the plan's hosting decision).

---

## Structure

```
app/
  main.py              # app factory, CORS, health check
  core/
    config.py           # loads ../../config_vibration.yaml
    db.py                # SQLAlchemy engine (DATABASE_POOLER_URL, pgbouncer-aware)
    auth.py               # Phase 1 static-token auth stub
  routers/
    events.py             # MODULE-AGNOSTIC: GET /events, GET /events/{id}
  modules/
    seismic/
      classify.py          # the ONLY place that imports SeisBench/PyTorch
      schemas.py            # seismic-specific Pydantic models
```

`routers/events.py` has no seismic-specific logic — a future Module 3/4
should be able to write into its own table and reuse this same route shape,
per CLAUDE.md's pluggable-module principle. Anything seismic-specific lives
under `modules/seismic/`.

---

## Environment variables required

| Variable | Purpose |
|---|---|
| `DATABASE_POOLER_URL` (or `DATABASE_URL` as fallback) | Supabase pgbouncer pooler connection |
| `MODULE2_API_TOKEN` | Static API token for Phase 1 auth (see `app/core/auth.py`) |

---

## Run locally

```bash
pip install -r ../../requirements.txt
cd src/03_api_service
uvicorn app.main:app --reload --port 8000
curl -H "x-api-token: $MODULE2_API_TOKEN" http://localhost:8000/events
```

## Deploy to Railway

1. Connect this GitHub repo to a new Railway project (railway.app dashboard — no CLI/SSH required, matches the "manageable from a phone" requirement).
2. **Leave Root Directory unset** (default = repo root) — `railway.json` lives at the repo root specifically so Railway finds it without any manual Root Directory setting; its `startCommand` does its own `cd src/03_api_service` internally.
3. Set `DATABASE_POOLER_URL` and `MODULE2_API_TOKEN` as Railway environment variables (Settings → Variables) — separate from the GitHub Actions secrets, Railway doesn't read those.
4. Railway builds from `railway.json` (Nixpacks, explicit `pip install -r requirements.txt`) and runs the start command automatically on every push to `main`.
5. See `docs/API_CONTRACT_MODULE2.md` for the response shape the frontend session should expect.
