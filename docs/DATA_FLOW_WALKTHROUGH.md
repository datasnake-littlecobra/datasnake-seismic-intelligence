# Data Flow Walkthrough: What the Data Actually Looks Like, Stage by Stage

Companion to `docs/PROBLEM_AND_APPROACH.md` (the why) and
`docs/MODULE2_ARCHITECTURE.md` (the operational status). This doc is the
"what does the data look like, and which exact code touches it" reference —
written because reading a diagram of arrows between boxes isn't how this
clicks; seeing the actual shape of the data at each step is.

Illustrative example values below (clearly marked) — no successful pipeline
run has produced real output yet (see MODULE2_ARCHITECTURE.md's status), so
these show what the *code* produces given real input, not a captured run.

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

**Relevant code**: `pull_stead_sample()` — instantiates the dataset,
takes the first N metadata rows (`.iloc[:sample_size]`), writes them to
`stead_sample_metadata.csv`.

**Shape after this stage**: a small metadata CSV (the table above, N rows)
+ (once wired correctly — see "the SeisBench problem" below) the matching
raw waveform arrays, one 3×6000-sample array per trace (3 channels ×
60 seconds × 100Hz).

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
