-- Reference queries for exploring `vibration_classified_events` in the
-- Supabase SQL Editor. Not migrations, not run by any pipeline — copy/paste
-- individual queries as needed. Grouped by what question they answer.
--
-- Table is currently near-empty (schema live, no real classified rows yet —
-- see docs/MODULE2_ARCHITECTURE.md for why). Several of these return zero
-- rows today; they're here so they're ready the moment data lands, and so
-- you can audit the pipeline's own claims independently rather than taking
-- validate.py's word for it.

-- ── Volume & freshness ───────────────────────────────────────────────────

-- Row count and time range
select count(*) as total_rows,
       min(event_time) as earliest,
       max(event_time) as latest
from vibration_classified_events;

-- Per-pipeline-run breakdown — one row per replay_pipeline.py invocation
select pipeline_run_id, source_dataset, data_version, count(*),
       min(created_at) as run_started, max(created_at) as run_finished
from vibration_classified_events
group by pipeline_run_id, source_dataset, data_version
order by min(created_at) desc;

-- ── Class distribution ───────────────────────────────────────────────────

select event_type, count(*), round(avg(confidence)::numeric, 3) as avg_confidence
from vibration_classified_events
group by event_type
order by count(*) desc;

-- ── Governance / model-honesty checks ────────────────────────────────────
-- (abstain / requires_human_review are the fields that keep an
--  under-confident model from silently reporting a wrong answer)

select
  count(*) filter (where abstain) as abstained,
  count(*) filter (where requires_human_review) as needs_review,
  count(*) as total,
  round(100.0 * count(*) filter (where abstain) / nullif(count(*), 0), 1) as pct_abstained
from vibration_classified_events;

-- ── Data-quality self-audit ───────────────────────────────────────────────
-- Same checks src/02_ml_pipeline/tests/test_split_leakage.py and
-- test_duplicate_detection.py run in Python — here in SQL so you can verify
-- the live table independently, not just trust the pipeline code.

-- Leakage: any scenario_family_id spanning more than one split?
-- Should always return zero rows.
select scenario_family_id, count(distinct split) as split_count
from vibration_classified_events
group by scenario_family_id
having count(distinct split) > 1;

-- Duplicates: should always return zero rows given the
-- unique(source_dataset, raw_waveform_ref) constraint in the migration.
select source_dataset, raw_waveform_ref, count(*)
from vibration_classified_events
group by source_dataset, raw_waveform_ref
having count(*) > 1;

-- ── Cross-reference with the model catalog ───────────────────────────────

select e.event_type, count(*), r.status, r.accuracy_pct
from vibration_classified_events e
join model_registry r on r.slug = 'seismic-vibration-ground'
group by e.event_type, r.status, r.accuracy_pct;

-- ── Geospatial coverage ───────────────────────────────────────────────────
-- Many Phase 1 rows won't have a location — replayed catalog data isn't
-- always lat/lon-tagged the way a live deployed sensor would be.
select count(*) filter (where location is not null) as with_location,
       count(*) as total
from vibration_classified_events;
