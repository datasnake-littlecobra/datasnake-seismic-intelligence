# Handoff: `ingest-datasnake-vibration` Edge Function

Paste this whole file as a message to the Claude Code session working on
`terrawatchapp-beta`. It's a concrete implementation spec, not a research
task — the investigation behind it is already done.

---

## What this is

A new Supabase Edge Function, following the exact same pattern as the
existing `ingest-seismic`/`ingest-weather`/`ingest-space` functions, that
makes Module 2 (DataSnake's ground-sensor vibration classification) show
up in the real app — Global Events Feed, Events Map, Alerts — for the
first time. Right now it doesn't appear there at all; this closes that gap
with one new file, no schema migration, no frontend changes.

## Why this is safe and small

- `public.events`'s `kind` check constraint already allows `'datasnake'` —
  confirmed by reading `supabase/migrations/0002_events_ingest.sql`
  directly. No migration needed.
- `vibration_classified_events` (Module 2's output table) lives in the
  **same Supabase project/database** as `public.events` — this can be a
  direct cross-table SQL read inside the edge function, no HTTP call to
  any external API needed.
- This adds a new file; it doesn't touch any of the 5 existing ingest
  functions or their shared helper (`_shared/ingest-common.ts`).

## Implementation

Create `supabase/functions/ingest-datasnake-vibration/index.ts`, modeled
directly on `ingest-seismic/index.ts`:

```ts
import { serve } from 'https://deno.land/std@0.224.0/http/server.ts'
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.3'
import { runIngest, type EventRow } from '../_shared/ingest-common.ts'

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? ''
const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''

interface VibrationRow {
  event_id: string
  event_time: string
  latitude: number | null
  longitude: number | null
  event_type: string
  confidence: number
  scenario_family_id: string
  source_dataset: string
  model_version: string
  abstain: boolean
  requires_human_review: boolean
  evidence: Record<string, unknown>
}

async function ingestVibration(): Promise<EventRow[]> {
  const admin = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  })

  // Skip 'environmental' (background-noise, not-an-earthquake) rows —
  // not alert-worthy. Only 'seismic' (and, once trained, 'vehicle_human')
  // belong in a public alerting feed.
  const { data, error } = await admin
    .from('vibration_classified_events')
    .select('event_id, event_time, latitude, longitude, event_type, confidence, scenario_family_id, source_dataset, model_version, abstain, requires_human_review, evidence')
    .neq('event_type', 'environmental')
    .order('event_time', { ascending: false })
    .limit(500)

  if (error) throw new Error(error.message)

  return ((data ?? []) as VibrationRow[]).map((r): EventRow => ({
    source: 'datasnake.vibration',
    external_id: r.event_id,
    kind: 'datasnake',
    category: 'seismic_vibration',
    // Only non-environmental rows reach here. requires_human_review means
    // the model itself flagged low confidence — 'caution' is the honest
    // severity for that; a confident detection is 'danger'. There is
    // deliberately no 'safe' case here (that's what filtering out
    // 'environmental' above already handles).
    severity: r.requires_human_review ? 'caution' : 'danger',
    title: `${r.event_type === 'seismic' ? 'Seismic' : r.event_type} ground-vibration detected`,
    summary: `Confidence ${(r.confidence * 100).toFixed(0)}% · ${r.source_dataset} · model ${r.model_version}`,
    location: r.latitude != null && r.longitude != null
      ? { lat: r.latitude, lon: r.longitude }
      : null,
    location_label: null,
    country: null,
    region: null,
    magnitude: null,
    depth_km: null,
    kp: null,
    occurred_at: r.event_time,
    expires_at: null,
    payload: {
      confidence: r.confidence,
      scenario_family_id: r.scenario_family_id,
      model_version: r.model_version,
      source_dataset: r.source_dataset,
      abstain: r.abstain,
      requires_human_review: r.requires_human_review,
      evidence: r.evidence,
    },
  }))
}

serve((req) => runIngest('datasnake-vibration', ingestVibration, req))
```

**One caveat worth carrying into the UI, not just this function**:
`event_time` on Module 2's rows is stamped at *pipeline run time*, not the
real historical moment an earthquake occurred (Phase 1 replays a public
benchmark dataset, not a live feed — see
`datasnake-seismic-intelligence/docs/API_CONTRACT_MODULE2.md`). Rows from
one pipeline run will cluster at nearly the same `occurred_at`. That's
expected, not a bug in this function.

## Deployment steps (same as the other 5 functions)

1. `supabase functions deploy ingest-datasnake-vibration --no-verify-jwt`
2. Add a pg_cron entry calling it hourly, same pattern as the existing 5
   (check `supabase/migrations/` for how their cron entries are registered
   — likely a `select cron.schedule(...)` migration).
3. No new secrets needed — it uses the same `SUPABASE_URL`/
   `SUPABASE_SERVICE_ROLE_KEY` every other ingest function already has.

## Verification

After the first run, confirm with:

```sql
select kind, source, category, count(*), max(occurred_at)
from events
where source = 'datasnake.vibration'
group by kind, source, category;
```

Expect a nonzero count, `kind = 'datasnake'`, `category = 'seismic_vibration'`.
Cross-check the count against:

```sql
select count(*) from vibration_classified_events where event_type != 'environmental';
```

(Run this second query against `vibration_classified_events` — same
project, so a single Supabase SQL Editor session can run both.)

## Naming convention going forward (for context, not needed to implement this one)

This function is named `ingest-datasnake-vibration` — no "parametric"
prefix, because Module 2 (ground-sensor vibration classification) isn't a
parametric-insurance product. A second DataSnake module is starting now:
a parametric flood-risk index, whose ingest function should be named
`ingest-datasnake-parametric-flood` (and a future wildfire equivalent
`ingest-datasnake-parametric-wildfire`) — the `parametric-` prefix marks
the insurance-product family specifically, while modules like this one
that don't belong to that family (vibration monitoring, and whatever else
comes later) just get `ingest-datasnake-<module>`. Not needed for this
handoff — just so the pattern doesn't have to be re-derived next time.
