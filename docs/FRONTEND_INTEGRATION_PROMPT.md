# Prompt: Verify + Explore Module 2 (Seismic/Vibration Intelligence) Integration

Paste this whole file as your first message to the Claude Code session
working on `terrawatchapp-beta` / `hyperlocalwatch.com`. It's written to be
self-contained — that session has no memory of how this backend was built.

---

## Who you are, and what you're being asked to do

You're working in `terrawatchapp-beta`, the Vue3/Vite frontend that deploys
to `hyperlocalwatch.com`. A separate project, `datasnake-seismic-intelligence`
(a different repo, built and maintained in a different Claude Code session),
has just finished building and verifying a real, working backend for a new
feature: **Module 2 — ground-sensor vibration/seismic classification**. Your
job right now is NOT to build the full dashboard yet. It's three things, in
order:

1. **Verify you can actually connect to it** — call the real API, get real
   data back, confirm the whole chain works from your side.
2. **Explore what you got back** and figure out what's genuinely useful to
   show someone, given what's actually in the data today (not what you wish
   were in it).
3. **Identify gaps** — what fields, parameters, or new endpoints would you
   need for the kind of modern analytics UI (charts, drill-down tables,
   one-click visual summaries) that would actually be compelling — and write
   those gaps down clearly, since they need to become a request back to the
   backend session, not something you can just invent client-side.

Do NOT modify anything in the `datasnake-seismic-intelligence` repo — you
don't have it checked out, and it's owned by a different session. If you
need something from it, add it as a bullet in your findings, not code.

---

## What's actually true about this data right now (read this before building anything)

This is a young, honestly-scoped system. A few things matter a lot for
what you should and shouldn't build:

- **This is real data flowing through a real, automated pipeline** — not
  mock data, not a prototype that fakes its output. Public, licensed
  earthquake-catalog data (STEAD, CC BY 4.0) is cleaned, windowed, and run
  through a real pretrained AI model (PhaseNet), and the results are
  written into a live Postgres table by a fully automated CI pipeline.
- **It is NOT a live sensor feed yet.** There's no hardware deployed yet.
  `sensor_id` values look like `replay:stead`, not real device IDs.
  `event_time` is stamped at *pipeline run time*, not the real historical
  moment an earthquake happened — most rows from one run share nearly the
  same `event_time`. **Don't build a real-time-feed UI or a time-series
  chart that assumes `event_time` is meaningful event history** — it isn't,
  yet.
- **`latitude`/`longitude` are usually null.** This catalog data isn't
  station-geocoded in the pipeline yet. Don't build a map view assuming
  most rows are geolocated.
- **`severity_score` is always null.** No magnitude/severity model exists
  yet — leave it out of the UI rather than showing an empty/zero value.
- **Only 2 of 4 possible event types actually occur today**: `seismic` and
  `environmental`. `vehicle_human` and `unknown` are valid values in the
  schema but structurally cannot be produced by the current model — no
  public dataset separately labels vehicle/human-caused vibration. Don't
  build a UI that assumes all 4 classes will have data.
- **A real accuracy check now exists, with one honest caveat.** Recent rows
  carry both the model's own guess (`event_type`) and the known correct
  answer (`evidence.ground_truth_event_type`) — so real accuracy is
  measurable, and it currently measures very high (~100% on the current
  sample). The caveat: the AI model was originally trained on this exact
  public dataset, so this mainly proves "the pipeline correctly hooks up to
  the model," not yet "the model is this accurate on real-world data it's
  never seen." If you build any accuracy/confidence display, consider
  surfacing that nuance rather than a bare "100% accurate" claim — it'll
  read as more credible to a technical viewer, not less.
- **Go through the API, not a direct Supabase read.** `vibration_classified_events`
  technically has a public-select RLS policy (like other tables you already
  read directly, e.g. `model_registry`), but this one is deliberately
  designed to go through the FastAPI service below instead — there's
  planned data-pipeline work (chunking/partitioning at scale) that belongs
  in that Python service, not in Postgres RPCs. Please route through
  `GET /events`.

---

## The technical contract

Full reference: `docs/API_CONTRACT_MODULE2.md` and `docs/MODULE2_ARCHITECTURE.md`
in the `datasnake-seismic-intelligence` repo (ask the user for read access to
it if you want the full detail — you shouldn't need to for this task).

**Base URL**: `https://<RAILWAY_APP_URL>` — ask the user for the real
deployed URL; it isn't committed anywhere as plain text (Railway assigns
it, and it was never written down verbatim in the repo's docs).

**Auth**: every endpoint except `/health` requires a header:
```
x-api-token: <MODULE2_API_TOKEN>
```
Ask the user for this value directly — it's a secret, not something to
guess or hardcode.

**Endpoints**:

- `GET /health` → `{"status": "ok"}`, no auth. Call this FIRST to confirm
  basic connectivity before anything else.
- `GET /events` — query params (all optional): `event_type`
  (`seismic`/`vehicle_human`/`environmental`/`unknown`), `requires_review`
  (boolean), `limit` (default 50, max 500), `offset` (default 0).
- `GET /events/{event_id}` — single row, 404 if not found.
- `GET /openapi.json` — machine-readable schema, prefer this over hand-
  parsing docs if you're generating TypeScript types.

**Response shape for `GET /events`**:
```json
{
  "rows": [
    {
      "event_id": "uuid",
      "sensor_id": "replay:stead",
      "event_time": "2026-08-10T14:23:45Z",
      "latitude": null,
      "longitude": null,
      "event_type": "seismic",
      "confidence": 0.87,
      "severity_score": null,
      "scenario_family_id": "stead_1234",
      "human_summary": null,
      "source_dataset": "STEAD",
      "evidence": {
        "window_id": "stead_1234_0",
        "source_idx": 1234,
        "ground_truth_event_type": "seismic"
      },
      "abstain": false,
      "requires_human_review": false,
      "created_at": "2026-08-10T14:24:01Z"
    }
  ],
  "total": 50,
  "offset": 0,
  "limit": 50
}
```

---

## Step-by-step task

1. **Connectivity check.** Call `GET /health`, then `GET /events?limit=10`
   with the real token. Confirm you get real rows back, not an error. Report
   this plainly — don't proceed to step 2 until this actually works.

2. **Look at what you actually got.** Pull a decent sample (e.g.
   `limit=100`) and look at the real distribution: how many `seismic` vs.
   `environmental`, the range of `confidence` values, how many
   `requires_human_review`. This tells you what's honestly displayable
   today vs. what would look sparse or broken (e.g. a map with almost no
   coordinates).

3. **Propose a first-pass set of UI components that fit what's real today**,
   not a wishlist. Given the caveats above, reasonable starting ideas:
   - A donut/bar chart of `event_type` distribution.
   - An expandable event list/table — collapsed row shows type/confidence/
     time, expanded row shows the raw `evidence` (including the ground-truth
     comparison, which is genuinely interesting: "model said X, actually Y").
   - A "flagged for human review" count/badge — this is a legitimately
     good thing to show regardless of model maturity, since it visibly
     proves the system doesn't overclaim when unsure.
   - A confidence distribution histogram.
   - Explicitly skip (for now): a live map, a real-time feed, anything
     framed as "current/live sensor status."

4. **Write down the gaps.** As you build/explore, you'll likely want data
   that doesn't exist yet — e.g., a proper historical timestamp, real
   geolocation, pagination cursors, aggregate/summary endpoints instead of
   raw rows (`GET /events/stats` returning pre-computed counts, say). Don't
   invent these client-side — list them clearly (field name, why you want
   it, what UI it would unblock) so the user can hand that list back to the
   `datasnake-seismic-intelligence` session as a concrete, prioritized
   request.

5. **Report back** with: (a) confirmation the connection works, (b) what you
   actually built or prototyped, (c) the gap list from step 4. The user will
   relay this to the backend session to close the loop.
