# Technical Debt Register: Known STEAD-Specific Shortcuts

This is a deliberate list, not an accident report. Every item below is a
place where the pipeline was built to work correctly for **one dataset
(STEAD) run in one way (a replayed local sample, not a live feed)** —
because that's the fastest path to a real, working, demoable pipeline —
at the cost of assumptions that will break the moment a second dataset,
a live sensor feed, or a bigger STEAD pull enters the picture.

**Standing decision (confirmed with the project lead, 2026)**: stay
hardcoded for now. Do not build the general adapter/plugin abstraction
until there's solid, demo-worthy data and a real reason (a second source,
or the start of live sensor integration) to generalize. Generalizing
before that point is speculative engineering against a shape of problem
we don't have real requirements for yet — see this repo's own stated
principle against building for hypothetical future requirements.

Each entry below states: what's hardcoded, why that's an acceptable
shortcut *right now*, what specifically breaks if a second source or live
data shows up before it's fixed, and the trigger condition for when to
prioritize the fix. Treat "trigger condition" as the thing to check before
starting any new dataset/source integration work — if a trigger has fired,
fix that item first, don't build the new integration on top of it.

---

## 1. `gold_label_split.py`: `TRACE_CATEGORY_TO_EVENT_TYPE` is a STEAD-vocabulary mapping

**Where**: `src/02_ml_pipeline/gold_label_split.py`, module-level dict:

```python
TRACE_CATEGORY_TO_EVENT_TYPE = {
    "earthquake_local": "seismic",
    "noise": "environmental",
}
```

**What's hardcoded**: this dict's *keys* are STEAD's exact label
vocabulary (`trace_category` values). Any row whose `trace_category`
isn't one of these two exact strings silently falls through to
`"unknown"` via `.fillna("unknown")` on line 92 — not an error, just a
silent reclassification.

**Why acceptable now**: STEAD is the only dataset actually flowing
through this pipeline. There's no second vocabulary to reconcile yet, so
a STEAD-shaped mapping is simply correct, not incomplete.

**What breaks with a second source**: INSTANCE (once its local sample
exists — see item 4) uses its own label vocabulary, which is not
guaranteed to use the exact strings `"earthquake_local"`/`"noise"`. If
INSTANCE's labels differ even slightly (a very real possibility — dataset
authors rarely share an exact vocabulary), every INSTANCE row would
silently land in `"unknown"` — not a crash, not a warning, just wrong
labels that look plausible. This is the most dangerous kind of debt here:
it fails quietly.

**What breaks with live sensor data**: live raw sensor readings have no
`trace_category` at all — that column only exists because STEAD's authors
hand-labeled it. This mapping is meaningless for a live feed; the labeling
step for live data has to come from the model's prediction instead (see
`docs/DATA_FLOW_WALKTHROUGH.md`'s "Where raw sensor data connects to all
of this" section — this is one of the concrete pieces flagged there).

**Trigger to fix**: before wiring in a second dataset with its own label
vocabulary (INSTANCE or otherwise) — replace the flat dict with a
per-dataset mapping (e.g. keyed first by `source_dataset`, or via the
adapter-pattern refactor previously considered and explicitly deferred).

---

## 2. `gold_label_split.py`: `assign_scenario_family()` assumes a `source_id` column

**Where**: `src/02_ml_pipeline/gold_label_split.py`, `assign_scenario_family()`:

```python
if "source_id" in bronze_meta.columns:
    return bronze_meta["source_id"].fillna(bronze_meta.index.to_series().astype(str))
return bronze_meta.index.to_series().astype(str)
```

**What's hardcoded**: the leakage-prevention grouping key is STEAD's
`source_id` column specifically (the ID of the originating earthquake).
The `if "source_id" in columns` guard is a soft fallback — if the column
is simply *absent*, every row silently becomes its own scenario family
(no grouping at all), rather than raising an error.

**Why acceptable now**: STEAD's metadata reliably has `source_id`, so the
grouping is correct for what's actually running. The fallback path has
never been exercised by real data yet.

**What breaks with a second source**: if a second dataset's equivalent
"which earthquake is this" column has a different name, the `if` check
silently fails, every row becomes its own family, and — critically — the
leakage protection that `scenario_family_id` exists to provide
(see `docs/DATA_FLOW_WALKTHROUGH.md`) **silently stops working**. The
pipeline would keep running, keep writing rows, and give no indication
that train/val/test leakage protection had quietly degraded to a no-op
for that dataset. This is worse than a crash — a crash would at least be
noticed. `test_split_leakage.py` (see `src/02_ml_pipeline/tests/`) only
protects the case it was written against (STEAD's shape); it should be
re-run explicitly against any new dataset's real column names before
trusting it there.

**What breaks with live sensor data**: there is no equivalent of "which
earthquake" available in real time — you don't know two stations recorded
the same event until it's confirmed after the fact. `docs/
DATA_FLOW_WALKTHROUGH.md` already flags this as a design decision to make
deliberately when Phase 2 starts, not an accident to fix later.

**Trigger to fix**: same as item 1 — before a second dataset is wired in.
At minimum, change the silent fallback to a hard error (fail loud if the
expected grouping column is missing) even before building the general
fix, so a future integration mistake surfaces immediately instead of
silently shipping ungrouped, leakage-vulnerable splits.

---

## 3. `local_sample.py` / `bronze_ingest.py`: hardcoded local file layout

**Where**: `src/02_ml_pipeline/local_sample.py`'s `sample_dir()`:

```python
def sample_dir(dataset: str) -> Path:
    return ROOT / "data" / f"{dataset}_sample"
```

...and the fixed filenames `{dataset}_sample_metadata.csv` /
`{dataset}_sample_waveforms.hdf5` referenced in `load_metadata()` and
`get_waveform()`.

**What's hardcoded**: an exact directory-naming and file-naming
convention (`data/<dataset>_sample/<dataset>_sample_metadata.csv` and
`..._waveforms.hdf5`), plus a specific one-time manual extraction process
(`scripts/extract_stead_sample.py`, run by hand, locally, once) to
populate it. There is no automated ingestion path at all today — every
dataset this pipeline reads from requires a human to run an extraction
script on their own machine and commit the output.

**Why acceptable now**: this was the correct, fastest fix for a real,
confirmed blocker — SeisBench's STEAD/INSTANCE loaders have no
partial-download option and were pulling 84.9GB in CI (see
`docs/MODULE2_ARCHITECTURE.md`'s troubleshooting log). A small, real,
committed sample unblocks the entire rest of the pipeline immediately,
which is exactly what let bronze→silver→gold→replay go from "blocked" to
"actually running end to end" this cycle.

**What breaks at production scale**: this doesn't scale to STEAD's full
~85GB, let alone a live sensor feed. Two specific limits:
- **Git isn't built for large binary data.** Committing a bigger sample
  (or full dataset) would bloat repo size and clone time indefinitely.
- **A human-run extraction script is a manual step in what's otherwise a
  fully automated CI pipeline** (`.github/workflows/pipeline.yml`'s whole
  point was removing manual steps — see its own header comment). Scaling
  the *amount* of STEAD data used, without changing this, means someone
  manually re-extracting and re-uploading a bigger file by hand — the
  opposite of the automation goal already achieved for everything
  downstream of bronze.

**What breaks with live sensor data**: obviously, there is no "extract a
sample from a fixed archive" step for a continuous live stream — this
whole approach is a Phase 1 substitute (see `replay_pipeline.py`'s own
module docstring) for a live feed, not a version of one.

**Trigger to fix**: two independent triggers, either one is enough to act
on:
1. **Before meaningfully increasing the STEAD sample size** beyond what's
   comfortably committable to git (the current 50 rows / ~3.7MB is fine;
   thousands of rows / hundreds of MB would not be) — at that point,
   revisit STEAD's actual chunked distribution (6 separate ~14-16GB
   chunks at the source, confirmed to exist, distinct from SeisBench's
   merged-only API) as a path to a CI-automatable *partial* real pull,
   rather than a bigger manual extraction.
2. **Before Phase 2 (live sensor integration) starts at all** — this is
   the point where "local sample file" needs to become "streaming
   ingestion source," a materially different design, not an extension of
   this one.

---

## 4. INSTANCE dataset: never actually extracted

**Where**: `config_vibration.yaml`'s `instance` section, marked
`NOT YET AVAILABLE`; `src/02_ml_pipeline/local_sample.py`'s
`load_metadata()` raises a clear `FileNotFoundError` if called for it.

**What's hardcoded**: nothing code-wise here — this is a straightforward
"not done yet," called out explicitly rather than silently stubbed. Worth
tracking anyway because items 1 and 2 above are specifically *about* what
happens the moment this changes.

**Why acceptable now**: the project lead's explicit decision this cycle
was to finish and understand the STEAD-only pipeline first, before adding
a second dataset. INSTANCE was previously confirmed CC BY 4.0 licensed
(same standard applied to STEAD), so licensing isn't the blocker — timing
and priority are.

**Trigger to fix**: whenever INSTANCE (or any other dataset) is actually
prioritized — and when that happens, items 1 and 2 above should be
addressed *first*, using INSTANCE's real column names/vocabulary as the
concrete second case that proves the fix actually generalizes, rather
than fixing them speculatively without a second real dataset to check
against.

---

## 5. `classify_window()`'s "confidence" is a max-over-time score — asymmetric and possibly misleading for the environmental branch

**Status: fixed** (`_peak_sustained_probability()` now replaces the raw
max, and `ground_truth_event_type` is now stored in `evidence` — see below
for what was true before the fix and what changed). Left in the register
rather than deleted, since the trigger conditions below are still
relevant (e.g. the threshold may need retuning once real accuracy is
measured against the newly-preserved ground truth).

**Where**: `src/02_ml_pipeline/replay_pipeline.py`'s `classify_window()`.

**What's happening**: after the first real CI run, every one of the 100
rows came back with `confidence` rounding to `1.000`, split exactly 50/50
`seismic`/`environmental`, and zero abstains. That's not obviously a good
sign — it's a sign the confidence number needs scrutiny before it's
trusted or shown to anyone external.

The likely cause: `seismic_score`/`noise_score` are each `probs[...].max()`
— the single highest probability PhaseNet assigned *anywhere in the whole
30-second window*, per class. For the `seismic` branch this is plausibly
meaningful (PhaseNet finding one genuinely sharp, confident P/S arrival is
exactly what a well-trained phase-picker should do). For the
`environmental` branch it's close to a tautology: almost *any* 30-second
window — real earthquake windows included — has some quiet moment where
the model assigns noise a probability near 1. Taking the max over the
whole window means "confidence" for `environmental` rows is measuring
"was there ever a quiet instant," not "is this window free of seismic
activity." That would explain a suspiciously perfect, undifferentiated
`1.000` average far better than "the model is extremely good."

**Why this wasn't caught before landing**: verifying the *interface*
(shapes, what type the model returns) was done locally against a real
`seisbench` install before this shipped. Verifying the *statistical
behavior* of the resulting confidence score across a real batch of mixed
data requires exactly the kind of run that just happened in CI — this is
the first time real numbers existed to look at.

**What breaks if this isn't fixed**: any accuracy/calibration claim built
on this confidence number is unreliable, and the abstain/human-review
governance mechanism is effectively disabled for the `environmental`
branch (nothing will ever score low enough to trigger review) — exactly
the guardrail this project has otherwise been careful to keep honest.

**Trigger to fix**: before reporting any accuracy/confidence-calibration
number externally (a demo, an investor conversation, `model_registry`'s
`accuracy_pct`), or before this data reaches a frontend dashboard. Two
concrete, independent fixes worth doing together, not treated as
optional polish:
1. **Verify actual accuracy against ground truth first.** The DB's
   `event_type` column now holds the *model's* decision, not the known
   answer — the gold-layer CSV's ground truth is only preserved in the
   CI run's uploaded artifact (`pipeline-output-stead`), not queryable
   from Supabase directly. Worth adding the ground-truth label into the
   `evidence` jsonb column at write time specifically so accuracy can be
   checked with one SQL query against the live table, not a downloaded
   artifact.
2. **Replace the max-over-time heuristic with something that actually
   distinguishes "quiet somewhere" from "quiet everywhere"** — e.g. a
   window-level score computed from the mean (not max) P/S probability,
   or the fraction of timesteps above a pick threshold, rather than a
   single time-step's peak.

**Both done.** `_peak_sustained_probability()` replaces the raw
`.max()` with the peak of a moving average over `sustain_window_sec`
(config, default 0.5s) — a single stray high sample gets diluted by
averaging with its (low) neighbors, while a genuine arrival, which
naturally spans many consecutive samples, survives smoothing. `run()`
now writes `ground_truth_event_type` into `evidence` alongside the
model's own `event_type`, so real accuracy is one SQL query away — see
`data/analysis/vibration_classified_events_queries.sql`'s "Accuracy
against ground truth" section.

**Still open**: `detection_threshold` (0.3) and `sustain_window_sec`
(0.5s) are both reasonable starting points, not tuned against real
accuracy data — now that accuracy is actually measurable, revisit both
once there's a real precision/recall signal to tune against, rather than
leaving them as first-guess defaults indefinitely.

---

## What this list deliberately does not include

**The adapter/plugin pattern itself** (a `DatasetAdapter` Protocol
generalizing bronze/gold across sources) is not listed as a standalone
debt item — it's the *shape* of the fix for items 1–3 above, not a debt in
its own right. Building it now, before a second real dataset exists to
validate the abstraction against, risks guessing wrong about what actually
needs to be pluggable (a documented anti-pattern in this repo's own
engineering principles: don't design for hypothetical future
requirements). The right time to build it is alongside the second real
case (item 4's trigger), using that real case to keep the abstraction
honest.
