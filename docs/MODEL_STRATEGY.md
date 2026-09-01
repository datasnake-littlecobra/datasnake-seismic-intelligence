# Model Strategy: What "the model" Is, What It Isn't Yet, and Why the Sequence Matters

Companion to `docs/PROBLEM_AND_APPROACH.md` (the why) and
`docs/DATA_FLOW_WALKTHROUGH.md` (the data shapes). This doc answers a
narrower, harder question the other two don't: **what does it actually
mean to have "a model" here, do we already have one, and what does building
our own add that the existing one doesn't?**

Short answer up front, because it's easy to get lost in the two-stage plan
below: **we do not have a working model wired into this pipeline yet.**
`classify_window()` in `replay_pipeline.py` is a stub — it copies STEAD's
own known answer back out as if it were a prediction, with `confidence:
0.0` and `abstain: True` on every row. Stage 1 below is the very next
thing to build, not something already done.

---

## Clearing up "STEAD is already trained on PhaseNet"

This is the misconception worth untangling first, because it drove the
question that prompted this doc.

STEAD is **not** a trained model. It's a labeled dataset — waveforms plus
human-verified answers (is this an earthquake, and if so, exactly which
samples are the P-wave and S-wave arrivals). STEAD's own homepage and
paper describe it as a *benchmark dataset for training and evaluating*
phase-picking models — it doesn't ship a model, it ships the material a
model gets trained and graded on.

**PhaseNet** (Zhu & Beroza, 2018) is a separate thing: a specific neural
network architecture. Separately, other researchers have trained PhaseNet
*using* STEAD (among other datasets) and published the resulting trained
weights. That published, already-trained set of weights is what
`sbm.PhaseNet.from_pretrained("stead")` downloads via the SeisBench
library — "stead" here names *which trained weight file* to fetch, not a
claim that STEAD itself contains a model.

So the accurate chain is:

```
STEAD (labeled data) --[someone else already ran this]--> trained PhaseNet weights --[we load these]--> a model we can run
```

We are, right now, standing after that second arrow: we can pull an
already-trained model for free. We have not yet actually called it.

---

## Two questions that look similar but aren't

The user's instinct — "should we build our own PhaseNet from raw STEAD
ingest instead of using the pretrained one, to be on stronger footing" —
is really two separable questions:

1. **Do we run inference with an existing trained model, or train a brand
   new one ourselves?** (Stage 1 vs. Stage 2 below.)
2. **Is running the existing pretrained model on our pipeline's output
   circular or redundant**, since STEAD already "contains the answer"?

Question 2 first, because it's the one worth resolving before deciding
anything about Stage 2.

### Why running the pretrained model on our own windows is a real test, not a circular one

STEAD's CSV tells you the *ground truth label* for a trace
(`earthquake_local` vs `noise`, plus exact P/S arrival sample indices).
That label was produced by human seismologists reviewing the original
full-length recording — it says nothing about whether *our* bronze → silver
pipeline correctly preserved that signal after resampling, bandpass
filtering, normalizing, and chopping it into a 30-second window.

Concretely, here is what could go wrong between "STEAD says this is an
earthquake" and "our gold-layer window still looks like one":

- **Windowing could cut off the signal.** If `window_trace()`'s 30-second
  boundary happens to fall so the P/S arrival lands right at the edge, or
  in a different window than the arrival, the resulting window might
  contain none of the actual earthquake signal — just the quiet lead-in.
- **The bandpass filter could be misconfigured.** 1–45Hz is a reasonable
  default, but a bug (wrong units, wrong filter order, a swapped
  low/high cutoff) could strip the actual earthquake energy right along
  with the noise it's meant to remove.
- **Normalization could be wrong on an edge case.** Dividing by peak
  amplitude on a near-silent trace, or on a trace with one huge spike
  artifact, can distort the whole window's shape.
- **The `.T` transpose fixed earlier this project** (source files are
  `(samples, channels)`, the pipeline expects `(channels, samples)`) is
  exactly the kind of silent, no-error, wrong-answer bug this test is
  built to catch. Feed a transposed array into a real model and you don't
  get an exception — you get a confident, wrong classification.

So the test that matters is: **take a window our own pipeline produced,
run PhaseNet's real inference on it, and check whether the model still
recognizes it as an earthquake.** If our preprocessing preserved the
signal, PhaseNet's independent judgment (it was never told which STEAD
row this came from) should agree with STEAD's label. If our preprocessing
broke something, PhaseNet's judgment and STEAD's label will disagree — and
that disagreement is the first real signal that something upstream is
broken, which the pipeline currently has *no way to detect* (a stub always
"agrees" with itself). This is an **integration test of our own code**,
using an external, independent judge — not a redundant re-statement of
data that we already have. It answers "does our engineering hold up?", not
"is this really an earthquake?".

---

## The two-stage plan

### Stage 1 — Wire in the existing pretrained PhaseNet (do this first, do this now)

**What changes**: `classify_window()` in `replay_pipeline.py` stops being a
stub. It loads `sbm.PhaseNet.from_pretrained("stead")` once (module-level,
not per-window — loading weights is comparatively expensive, running
inference on a loaded model is cheap), calls it on the gold-layer window's
waveform array, and derives `event_type`/`confidence` from PhaseNet's real
output instead of copying STEAD's own label back out.

**Why this order**:
- **It's a small, well-scoped change.** One function, in one file, with a
  clear seam already built for it (the docstring in `classify_window()`
  says exactly this: "wire this to the trained model... this function is
  the seam"). No new infrastructure, no new dataset, no training loop.
- **It validates the pipeline built so far**, per the integration-test
  argument above — this is the first point at which a bug anywhere in
  bronze/silver/gold would actually surface as a wrong answer instead of
  silently passing.
- **It unblocks a real, honest demo sooner.** Right now, every row in
  `vibration_classified_events` has `abstain: True` and
  `confidence: 0.0` — accurate, but not demoable as "the model classified
  this." After Stage 1, rows carry a real model's real confidence score,
  and `model_version` reads something like `phasenet-stead-v1` instead of
  `stub-no-model-v0` — a materially different, truthful claim to make to
  an investor or government reviewer.
- **It doesn't foreclose Stage 2.** Nothing about wiring in the pretrained
  model changes the data pipeline, the schema, or the API — a custom
  model trained later drops into the exact same seam.

**What Stage 1 does *not* give us**: a model trained on *our* data with
*our* class definitions. PhaseNet's pretrained weights were trained to do
phase-picking (find P/S arrivals, distinguish earthquake from noise) — it
was never trained to distinguish `vehicle_human` from `environmental`,
because no dataset it saw during training labels those classes separately.
Stage 1 gives us a real, credible answer for the `seismic` vs.
`environmental`(-ish noise) distinction; it gives us nothing for
`vehicle_human`, which stays an abstained, honestly-labeled gap (see
`docs/TECHNICAL_DEBT.md`).

### Stage 2 — Train a model on our own data (do this later, once there's a reason to)

**What this actually requires**, stated plainly since "train our own
model" is often underestimated in scope:
- The **full** STEAD dataset (or a much larger sample than today's 50
  rows) — pretrained-weight quality came from ~1.2 million traces;
  training something competitive from scratch on 50 rows would not
  produce a usable model.
- GPU compute for the training run itself (CPU training on a dataset this
  size is impractical).
- A real training loop: loss function, optimizer, learning-rate schedule,
  train/val monitoring for overfitting — none of which exists in this
  repo yet.
- A rigorous eval harness beyond what `gold_label_split.py`'s leakage test
  already covers — per-class precision/recall/F1, confusion matrices,
  calibration checks — before a trained model's numbers mean anything.

**What it would genuinely buy us that Stage 1 can't**:
- **Closing the `vehicle_human` gap.** This is the real, concrete reason
  to eventually train something ourselves, not merely "our own model
  sounds more impressive." No public pretrained seismic model — PhaseNet
  included — was trained to separate vehicle/human-caused ground vibration
  from genuine environmental noise, because the datasets it saw don't
  label that distinction. Closing it requires: (a) sourcing/licensing a
  dataset that *does* label vehicle/human vibration separately, and (b)
  training on it, whether by fine-tuning PhaseNet's pretrained weights or
  training a new head. Neither can happen without a labeled source, so
  this genuinely can't be pulled earlier than Stage 1.
- **A model that's actually ours to fine-tune later.** Once real sensor
  hardware exists (Phase 2 of this project's broader plan), the highest-
  value future work is fine-tuning on real, proprietary, field-collected
  data — which requires already having a training pipeline built and
  proven, which is exactly what Stage 2 builds.
- **A stronger IP/credibility story for later**, once it's backed by a
  real eval run against real data — not before. A half-trained or
  under-evaluated custom model is a *weaker* demo claim than an honestly-
  labeled pretrained one, not a stronger one.

**Why Stage 2 shouldn't come before Stage 1**: everything Stage 2 needs
(a proven bronze→silver→gold pipeline, a full dataset pull that isn't
currently automatable — see `docs/TECHNICAL_DEBT.md`'s note on chunked
extraction, and a reason to believe the preprocessing is correct) is
either produced by Stage 1 or blocked on infrastructure Stage 1's
integration test would catch problems in first. Building a training loop
on top of preprocessing that hasn't been checked against an independent
judge risks training a model that "learns" a preprocessing bug rather than
real seismic signal — invisible in training metrics, only surfacing later
as unexplainably bad real-world performance.

---

## The demo narrative: (a) and (b), stated for an outside audience

Both of the following are honest claims — carefully worded to say exactly
what is and isn't true at each stage, which is itself part of the
credibility argument: an investor or government reviewer who has seen
enough AI pitches will notice, and discount, a claim that overstates
what's actually running.

### (a) Concept demo: STEAD data + an existing, published, peer-reviewed model

> "We built a governed data pipeline — ingestion, cleaning, windowing,
> labeling, leakage-safe splitting, and a queryable event store with full
> lineage — around a public, licensed (CC BY 4.0), peer-reviewed seismic
> benchmark dataset (STEAD, ~1.2M labeled recordings). We run a published,
> peer-reviewed phase-picking model (PhaseNet, Zhu & Beroza 2018) through
> that pipeline and serve its classifications, with confidence scores and
> an explicit human-review flag for low-confidence cases, through a live
> API to a monitoring dashboard."

**What this demonstrates, honestly**: the *engineering* — a real,
reproducible, governed pipeline capable of taking labeled seismic data in
and producing classified, queryable, auditable events out, end to end,
running automatically in CI on every code change. It does **not** claim we
built or trained the model — it claims we correctly integrated a
respected one into a production-shaped system. That's a legitimate,
demonstrable claim today, once Stage 1 lands.

**What it should not claim**: that the model was trained on "our" data
(it wasn't — it's public benchmark data), or that `vehicle_human`
detection works (it doesn't yet — no training signal exists for it).

### (b) Deeper demo: our own model, trained on STEAD's raw data

> "Beyond running an existing model, we built our own training pipeline on
> top of STEAD's raw, unprocessed recordings — meaning we're not limited
> to problems the original PhaseNet authors chose to solve. We can extend
> the same architecture and pipeline to classes the public model can't
> distinguish (like vehicle/human-caused vibration vs. genuine
> environmental noise), and — critically — the same training pipeline is
> what lets us later fine-tune on our own field-deployed sensors' real
> data, rather than staying permanently dependent on public benchmark
> data."

**What this demonstrates, honestly**: technical depth beyond integration
— that this team can build and evaluate a model, not just call one — and,
more importantly for the long-term pitch, a credible path to a model that
improves on *our own* real-world data over time, which is the actual
long-term differentiator versus "we called an open-source model." This is
the stronger claim, but it is only as credible as the eval numbers behind
it — an unevaluated or overfit model actually *weakens* this pitch versus
not claiming it at all.

**Sequencing for the demo, matching the engineering sequence above**: lead
with (a) as soon as Stage 1 lands — it's real, running, and honestly
described today. Introduce (b) once Stage 2 has an actual eval run to
point to, not before. Showing (a) working end-to-end, then describing (b)
as the concrete, already-scoped next step (not a vague future promise) is
a stronger position than promising both at once and having neither fully
land.

---

## Where this leaves `classify_window()` today

Nothing in this doc has been implemented yet. `classify_window()` in
`src/02_ml_pipeline/replay_pipeline.py` is still the stub described in
`docs/PROBLEM_AND_APPROACH.md` and `docs/DATA_FLOW_WALKTHROUGH.md`. Stage 1
(above) is the concrete next implementation step once there's a decision
to proceed with it.
