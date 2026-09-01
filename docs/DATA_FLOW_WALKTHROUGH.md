# Data Flow Walkthrough: What the Data Actually Looks Like, Stage by Stage

Companion to `docs/PROBLEM_AND_APPROACH.md` (the why) and
`docs/MODULE2_ARCHITECTURE.md` (the operational status). This doc is the
"what does the data look like, and which exact code touches it" reference —
written because reading a diagram of arrows between boxes isn't how this
clicks; seeing the actual shape of the data at each step is.

Illustrative example values below (clearly marked) reflect the *shape* the
code produces, not necessarily a literal captured row — though as of the
first successful end-to-end CI run, the pipeline described here has now
actually written 100 real rows into `vibration_classified_events` (50
STEAD windows × their real `event_type`/`split`/`scenario_family_id`; see
MODULE2_ARCHITECTURE.md's status for the run details, and the new section
below for how to look those real rows up yourself).

---

## Stage 0: What STEAD's raw metadata actually contains

STEAD ships one big `merged.csv` where every row describes one recorded
trace. Real column names, illustrative values for one earthquake row:

| column | example value | meaning |
|---|---|---|
| `trace_name` | `109C.TA_20090529014938_EV` | unique ID for this recording |
| `network_code` | `TA` | which seismic network recorded it |
| `receiver_code` | `109C` | which station |
| `receiver_latitude` / `_longitude` | `32.89`, `-117.19` | where the station is |
| `source_id` | `10974` | **the earthquake event this trace belongs to** — this is the field `scenario_family_id` is built from (see below) |
| `source_magnitude` | `3.2` | the earthquake's magnitude |
| `p_arrival_sample` | `1852` | which sample index the P-wave arrives at |
| `s_arrival_sample` | `2431` | which sample index the S-wave arrives at |
| `trace_category` | `earthquake_local` | STEAD's own label — `earthquake_local` or `noise` |

The actual waveform — a 3-component (vertical + 2 horizontal) time series,
100 samples/second, ~60 seconds long — lives separately, in `merged.hdf5`,
keyed by `trace_name`. The CSV tells you *about* a trace; the HDF5 holds
the *numbers*.

---

## Stage 1: Bronze — `src/02_ml_pipeline/bronze_ingest.py`

**What it does**: pulls the raw metadata + waveform pair, unmodified, and
records exactly what was pulled (a manifest — checksum, count, license,
timestamp) for lineage. No filtering, no labeling here on purpose — bronze
is "as received."

**Relevant code**: `pull_sample()` — reads the small local sample
(`data/stead_sample/`, see `local_sample.py`), takes the first N metadata
rows (`.iloc[:sample_size]`), writes them to `stead_sample_metadata.csv`.

**Shape after this stage**: a small metadata CSV (the table above, N rows).
The matching raw waveform for each row is looked up on demand by
`trace_name` in silver (next stage) — one array per trace, 6000 samples ×
3 channels natively in the source file, transposed to (3 channels, 6000
samples) by `local_sample.get_waveform()` to match the channel-first
convention the rest of this pipeline uses (60 seconds × 100Hz per trace).

---

## Stage 2: Silver — `src/02_ml_pipeline/silver_clean.py`

**What it does**: three concrete transformations to each raw waveform
array, plus **windowing** (see the dedicated section below):

1. **`bandpass_filter()`** — strips frequencies outside 1–45Hz. Real
   earthquake energy lives in this band; anything outside it (very slow
   drift, very high-frequency electronic noise) is discarded before the
   model ever sees it.
2. **`normalize()`** — divides by the peak amplitude, so a nearby small
   earthquake and a distant large one that happen to produce similar
   *waveform shapes* aren't distinguished by raw amplitude alone.
3. **`window_trace()`** — slices into fixed 30-second chunks (see below).

**Shape after this stage**: instead of one 3×6000 array per trace, you get
`floor(6000 / 3000) = 2` windows of 3×3000 each (our config: 30 sec × 100Hz
= 3000 samples). One input trace can become multiple output windows.

---

## Stage 3: Gold — `src/02_ml_pipeline/gold_label_split.py`

**What it does**: assigns a label and a train/val/test split to every
window — see "gold_label_split and scenario_family_id" below for the full
reasoning. Output is one row per window:

| window_id | source_idx | scenario_family_id | event_type | split | source_dataset |
|---|---|---|---|---|---|
| `stead_0_0` | `0` | `stead_10974` | `seismic` | `train` | `STEAD` |
| `stead_0_1` | `0` | `stead_10974` | `seismic` | `train` | `STEAD` |
| `stead_7_0` | `7` | `stead_22103` | `environmental` | `val` | `STEAD` |

Notice rows 1 and 2 share `scenario_family_id` (same earthquake, same
station, two windows) and are both `train` — never split across groups.

---

## Stage 4: Replay — `src/02_ml_pipeline/replay_pipeline.py`

**What it does**: for each gold-layer row, calls `classify_window()`
(currently a stub — see PROBLEM_AND_APPROACH.md), then upserts into
`vibration_classified_events`. A real row, once the model is actually
wired in, looks like:

```json
{
  "event_id": "3fa2...-uuid",
  "sensor_id": "replay:stead",
  "event_type": "seismic",
  "confidence": 0.94,
  "scenario_family_id": "stead_10974",
  "raw_waveform_ref": "stead_0_0",
  "split": "train",
  "source_dataset": "STEAD",
  "evidence": {"window_id": "stead_0_0", "source_idx": 0},
  "abstain": false,
  "requires_human_review": false
}
```

This is what the FastAPI service's `GET /events` ultimately serves.

---

## Windowing — what it does, and why it matters even with a pretrained model

**What it does mechanically**: chops a variable/long recording into
fixed-length pieces (here, 30 seconds at 100Hz = 3000 samples per channel).

**Why this is required regardless of whether *we're* training anything**:
PhaseNet — like almost all neural networks with a fixed input layer — was
built to accept one specific input shape. It cannot accept "a recording
of arbitrary length"; it accepts exactly (3 channels × 3000 samples), or
whatever shape it was built for. Windowing isn't a training-time-only step
— it's how *any* waveform, whether from the original training data or a
brand-new live sensor reading tomorrow, gets reshaped into something the
model's fixed input layer can actually accept. Skip it and inference simply
can't run — it's a hard shape mismatch, not a quality tradeoff.

**Why we still window STEAD/Iquique specifically**, given their traces
already arrive as fairly short segments (not raw endless streams): our
pipeline's window length (30s) is a choice independent of whatever length
each source dataset happens to natively provide, and a live sensor feed
*will* be a raw endless stream with no natural boundaries at all —
windowing is what creates a "thing to classify" out of continuous data in
the first place. Using the same windowing code against benchmark data now
is what proves that code will work unchanged against a real stream later.

---

## `gold_label_split.py` and `scenario_family_id`

**What the file does**: two jobs — (1) map each dataset's own label
(`trace_category`) onto our `event_type` vocabulary, (2) decide which
split (`train`/`val`/`test`) each window belongs to.

**Why `scenario_family_id` exists**: it's built from STEAD's `source_id` —
the ID of the *earthquake*, not the individual recording. Multiple stations
often record the same earthquake, producing multiple trace rows that are
all, fundamentally, evidence of one event.

**The failure this prevents — data leakage**: if station A's recording of
earthquake #10974 lands in `train` and station B's recording of that *same*
earthquake #10974 lands in `test`, a model could score deceptively well on
"test" not because it generalized to earthquakes in general, but because
it's recognizing something specific to that one already-seen event. Groups
sharing a `scenario_family_id` are always kept entirely on one side of the
split. This exact bug is what `src/02_ml_pipeline/tests/test_split_leakage.py`
verifies against — including a test that deliberately breaks a split and
confirms the check catches it, not just that the check exists.

---

## Where raw sensor data connects to all of this (Phase 2)

Every stage above operates on **windows**, regardless of where they came
from. A live sensor's continuous stream, once chopped into 30-second
windows by the same windowing logic, is structurally identical to a gold-
layer row from STEAD — same shape, same downstream code. The pieces that
change between "replaying a public dataset" and "a real deployed sensor"
are narrower than they might seem:

- **Bronze** changes from "pull a benchmark sample" to "read the next
  chunk off a live stream" — a different *source*, same *output shape*.
- **Silver and Gold's windowing/filtering are unchanged** — this is the
  code being proven right now.
- **`event_type` labeling changes** from "copy the dataset's known answer"
  to "the model's actual prediction" — because there's no known answer for
  live data. This is exactly the stub in `classify_window()` that needs
  real wiring.
- **`scenario_family_id`** stops being "which earthquake" (unknowable in
  real time, before an event is confirmed across stations) and would need
  a live-appropriate equivalent — worth deciding deliberately when this
  phase actually starts, not now.

See `docs/PROBLEM_AND_APPROACH.md` for the fuller Phase 2 data-ecosystem
picture (hardware, streaming ingestion, the monitoring/feedback loop).

---

## Stage 5: the database and API side — where "which table connects to what" lives

Everything above happens to local files (CSVs, an HDF5 file) that never
touch a database until the very last step. This section covers what
happens *after* `replay_pipeline.py` writes a row — the part that's easy
to lose track of because it spans three different places: the
`vibration_classified_events` table itself, its (non-obvious) link to
`model_registry`, and the FastAPI service that turns a DB row into JSON.

### `vibration_classified_events`: one row = one classified window

Full column list is in
`data/schema/0049_vibration_classified_events.sql`. The one thing worth
saying plainly: **every column on this table is populated by
`replay_pipeline.py`'s `run()` function, in one place** — there's no
trigger, no second writer, no background job touching this table. If a
column's value looks wrong, `replay_pipeline.py` (specifically the row
dict built in `run()`, around line 174) is the only place to look.

### The `model_registry` link: a slug, not a foreign key

`vibration_classified_events` has **no `model_id` or `model_registry_id`
column, and no foreign key to `model_registry` at all.** The two tables
are connected only by a shared *string value* — `model_registry.slug =
'seismic-vibration-ground'`, matched against
`vibration_classified_events.model_version` conceptually (the actual
model that produced a row), and against the module as a whole for catalog
display purposes.

Why this is worth calling out: it's easy to expect a real FK here and go
looking for one. There isn't one, deliberately — `model_registry` is a
catalog table (one row per *model*, for the `/ai-models` hub page to
display), while `vibration_classified_events` is an event table (one row
per *classified window*, potentially millions of rows). Joining them is a
manual `join ... on r.slug = 'seismic-vibration-ground'` (a literal
constant, not a stored column on either side) rather than a normal
`join ... on e.model_id = r.id`:

```sql
-- Real query, works today (data/analysis/vibration_classified_events_queries.sql)
select e.event_type, count(*), r.status, r.accuracy_pct
from vibration_classified_events e
join model_registry r on r.slug = 'seismic-vibration-ground'
group by e.event_type, r.status, r.accuracy_pct;
```

`model_registry.status = 'demo'` and `accuracy_pct = null` for this row
today — an honest reflection of Stage 1/2 not being wired in yet (see
`docs/MODEL_STRATEGY.md`). Once a real model is wired in and evaluated,
updating `accuracy_pct`/`status` on this **one row** in `model_registry`
is a separate, manual step from anything `replay_pipeline.py` does — the
pipeline never writes to `model_registry` itself.

### FastAPI's `GET /events`: which DB column becomes which JSON field

`src/03_api_service/app/routers/events.py` runs one query
(`EVENTS_QUERY`) and returns its rows almost verbatim — there's no
renaming, no computed fields, no hidden transformation. The mapping is
column-name-to-key-name, unchanged:

| DB column (`vibration_classified_events`) | JSON key in `GET /events` response | Notes |
|---|---|---|
| `event_id` | `event_id` | UUID, primary key |
| `sensor_id` | `sensor_id` | e.g. `"replay:stead"` — see schema comment on why this isn't an FK into `sensors` |
| `event_time` | `event_time` | when the pipeline stamped this row (see caveat below) |
| `latitude`, `longitude` | `latitude`, `longitude` | usually `null` for Phase 1 replayed data (STEAD rows aren't station-geocoded in this pipeline yet) |
| `event_type` | `event_type` | `seismic` / `environmental` today (real PhaseNet output — see caveat below); `vehicle_human`/`unknown` are defined but never produced by this model |
| `confidence` | `confidence` | PhaseNet's own peak P/S (or noise) probability for this window — see `docs/MODEL_STRATEGY.md` for exactly how |
| `severity_score` | `severity_score` | `null` — no magnitude/severity model wired in yet, honestly reported as "not computed" |
| `scenario_family_id` | `scenario_family_id` | e.g. `"stead_10974"` |
| `human_summary` | `human_summary` | `null` — never populated by any current code path |
| `source_dataset` | `source_dataset` | `"STEAD"` |
| `evidence` | `evidence` | jsonb, e.g. `{"window_id": "stead_0_0", "source_idx": 0}` |
| `abstain` | `abstain` | `true` when confidence is below `config_vibration.yaml`'s `model.review_threshold` (0.5) |
| `requires_human_review` | `requires_human_review` | same condition as `abstain` |
| `created_at` | `created_at` | row insert time — the actual real-world "when was this written" timestamp |

Columns that exist on the table but are **not** in `EVENTS_QUERY`'s
`SELECT` and so never appear in the API response at all:
`raw_waveform_ref`, `split`, `data_version`, `model_version`,
`pipeline_run_id`, `review_notes`, `location`. If you need any of these
for a frontend feature, that's a one-line addition to `EVENTS_QUERY` and
`EVENT_BY_ID_QUERY` in `events.py` — not a schema change.

**Caveat on `event_time` worth knowing**: `run()` in `replay_pipeline.py`
sets `event_time` to `pd.Timestamp.utcnow()` at pipeline-run time (line
178) — it is **not** derived from anything in STEAD's own metadata (STEAD
rows don't carry a usable absolute timestamp in this pipeline's current
columns). Practically: every row from one pipeline run shares almost the
same `event_time` (whenever the run happened), not the historical time
the underlying earthquake actually occurred. `created_at` and `event_time`
will therefore look almost identical for all of today's data — that's
expected, not a bug, and worth knowing before building a frontend
timeline view that assumes `event_time` reflects real-world event history.

### Worked example: tracing one `event_id` all the way back to a file on disk

This traces a single row through every layer, so "which table connects to
what" has one concrete path to follow instead of an abstract diagram.
Numbers below are illustrative (they follow the real code's logic, not a
copy-pasted live row) — run the SQL yourself against the real table to
get a real `event_id` to substitute.

**Step 1 — pick a real row from the database:**

```sql
select event_id, raw_waveform_ref, scenario_family_id, source_dataset, split
from vibration_classified_events
limit 1;
```

Say this returns:

```
event_id            = 3fa2b6e1-...-uuid
raw_waveform_ref    = stead_0_0
scenario_family_id  = stead_10974
source_dataset      = STEAD
split               = train
```

**Step 2 — `raw_waveform_ref` is the gold-layer `window_id`.** Find the
matching row in the gold CSV that `replay_pipeline.py` read from
(`data/module2_vibration/gold/stead_gold.csv`, produced by
`gold_label_split.py`):

```python
import pandas as pd
gold = pd.read_csv("data/module2_vibration/gold/stead_gold.csv")
gold[gold["window_id"] == "stead_0_0"]
# -> source_idx=0, scenario_family_id=stead_10974, event_type=seismic, split=train
```

`source_idx` (here, `0`) is the pointer into the *silver*-layer metadata —
it's the row position in the silver CSV this window was cut from (see
`gold_label_split.py`'s merge on `source_idx`, line 107-112).

**Step 3 — `source_idx` traces to the silver-layer window**, which in
turn traces to the bronze-layer metadata row it was windowed from
(`data/module2_vibration/silver/stead_silver_metadata.csv`, produced by
`silver_clean.py` — this file carries the `trace_name` column through
from bronze, unchanged, specifically so this trace-back is possible).

**Step 4 — the bronze row's `trace_name` is the real key into the
original committed sample file.** This is the actual raw waveform data:

```python
import h5py
with h5py.File("data/stead_sample/stead_sample_waveforms.hdf5", "r") as f:
    waveform = f["109C.TA_20090529014938_EV"][()]  # shape (6000, 3) — see local_sample.py's transpose note
```

**The full chain, restated as one line**:

```
vibration_classified_events.event_id
  -> .raw_waveform_ref (= gold.window_id)
    -> gold.source_idx
      -> silver_metadata row (same source_idx) -> .trace_name
        -> stead_sample_waveforms.hdf5[trace_name]  (the actual numbers)
```

Every arrow above is a real, followable join key that exists in a real
file or table today — nothing in this chain is aspirational.

---

## Quick reference: which file/table owns which question

| Question | Where to look |
|---|---|
| "What does this event's raw waveform actually look like?" | `data/stead_sample/stead_sample_waveforms.hdf5`, keyed by `trace_name` (via the chain above) |
| "Why did this window get labeled `seismic`?" | `gold_label_split.py`'s `TRACE_CATEGORY_TO_EVENT_TYPE` mapping, applied to the bronze row's `trace_category` |
| "Why is this row in `train` and not `test`?" | `gold_label_split.py`'s `split_by_family()`, keyed on `scenario_family_id` |
| "What confidence/model produced this classification?" | `replay_pipeline.py`'s `classify_window()` — real SeisBench PhaseNet inference as of Stage 1 (see `docs/MODEL_STRATEGY.md`) |
| "Is this model any good?" | `model_registry` row where `slug = 'seismic-vibration-ground'` (joined manually, not via FK — see above) |
| "What does the frontend actually receive for this event?" | `src/03_api_service/app/routers/events.py`'s `EVENTS_QUERY` column list (table above) |
| "Which pipeline run wrote this row, and when?" | `vibration_classified_events.pipeline_run_id` + `created_at` — see the "Per-pipeline-run breakdown" query in `data/analysis/vibration_classified_events_queries.sql` |
