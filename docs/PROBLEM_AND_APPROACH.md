# The Problem, the Approach, and Where This Is Headed

This doc exists for a specific reason: to answer "why does this matter" and
"what are we actually building" in one place, honestly — what's proven,
what's still a stub, and what the credible path from here looks like. Written
for a technical reader deciding whether this is worth paying attention to,
not as a marketing page.

---

## The problem

A raw ground-vibration sensor cannot tell an earthquake from a truck driving
past. This sounds minor; it's actually the reason dense, low-cost seismic
sensor networks have struggled to become real infrastructure, despite being
technically cheap to deploy for over a decade.

The pattern in the field has been: sparse networks of expensive, carefully
sited, professionally maintained seismometers, placed *away* from human
activity specifically to avoid this problem — which means away from the
places most people actually live. A dense network placed *in* populated
areas (where an early-warning signal or a structural-health signal would
actually be useful) is constantly triggered by traffic, construction,
footsteps, HVAC systems — anything that shakes the ground. Without reliable
classification, that's not a monitoring network, it's a noise generator, and
nobody trusts an alert system that cries wolf.

**This is also, structurally, a hard problem to make progress on — for
reasons that aren't really about model architecture:**

- **The labeled data needed to train a good classifier is scarce for the
  negative classes specifically.** Benchmarks like STEAD and INSTANCE give
  you hundreds of thousands of confirmed *earthquake* examples (decades of
  institutional labeling effort — see below), but essentially nothing
  labeled for "this was a truck" or "this was a person walking." We hit this
  directly: `vehicle_human` has zero labeled examples in either dataset we
  use. That's not an oversight on our part; it's a real, field-wide gap.
- **It sits at a narrow intersection** — ML engineering and seismology
  domain knowledge together — that fewer teams than you'd expect actually
  occupy.
- **Research and infrastructure are usually built by different people.**
  Academic work in this space (PhaseNet, EQTransformer, the SeisBench
  toolbox) produces excellent models and benchmarks, but a trained model
  sitting in a paper is a long way from a governed pipeline that ingests
  real data, tracks lineage, writes to a queryable store, and serves a live
  dashboard. Most of the effort in this repo so far is that second, less
  glamorous half.

---

## What this is actually for

Once ground vibration can be reliably classified, the same signal feeds
several real, distinct use cases:

- **Early warning.** Seconds of lead time before shaking arrives only has
  value if the alert is trustworthy — a system with a high false-positive
  rate gets ignored or disabled, which defeats the entire point.
- **Structural health monitoring.** A bridge, pipeline, or building sensor
  should trigger an inspection on genuinely anomalous vibration, not on
  every passing train.
- **Parametric insurance.** An objective, automated "a qualifying seismic
  event happened here" signal that can trigger payout without a slow manual
  claims process — faster for the policyholder, harder to dispute.

---

## The approach, and why it's built this way

**Governed inference, not just a model score.** Every classified row
carries `confidence`, `abstain`, and `requires_human_review` — the system
is built to say "I don't know" rather than confidently guess when it isn't
sure. That's a deliberate product decision, not an incidental schema field:
a safety-adjacent system that always answers, even when wrong, is worse
than useless.

**A pretrained model, not a research project.** `PhaseNet` (Zhu & Beroza,
2018) is a published, peer-reviewed picker, distributed pretrained through
`SeisBench` (Münchmeyer et al., 2022). We are not training a model from
scratch — the credible near-term value here is building the *pipeline and
product* around a model the field already trusts, not re-deriving seismic
ML research. See "Current state" below for exactly how far that
integration has actually gotten.

**Public earthquake catalogs standing in for live sensors.** There's no
deployed hardware sensor yet. Replaying real, licensed, publicly available
earthquake recordings through the full pipeline (ingest → clean → label →
classify → store → serve → display) is a realistic dress rehearsal — every
piece of infrastructure gets proven against real seismic waveforms, so that
swapping in a live sensor feed later is a data-source change, not an
architecture change.

**A module-agnostic API, on purpose.** `src/03_api_service/app/routers/events.py`
has no seismic-specific logic — the seismic pieces live under `modules/seismic/`.
This is Module 2 of a planned four (seismic/vibration, coastal visual,
infrastructure condition, plus a separate text-diagnostics product), all
meant to converge on the same governed-event shape and the same dashboard.
Module 2 is first because it has the most mature pretrained models and the
clearest path to a working demo — not because it's the only one that matters.

---

## Current state — honestly

Worth stating plainly rather than letting the architecture talk imply more
than what's true:

- **Live and verified**: the database schema, the FastAPI service
  (deployed, `/health` responding), the pipeline's test suite.
- **Not yet true**: no real model inference has ever produced a row in the
  database. `replay_pipeline.py`'s classification step is currently a
  deliberate stub — it echoes back a dataset's already-known label rather
  than calling PhaseNet. Wiring the real model into that write path is the
  next concrete milestone once the data pull itself is working end to end.
- **Data source in flux**: STEAD (the original target) turned out to
  require an all-or-nothing ~85GB download with no partial-fetch option in
  its SeisBench loader — not viable in an automated CI pipeline. Moving to
  Iquique (Woollam et al., 2019 — ~13,400 traces, two orders of magnitude
  smaller), a real, licensed, much smaller benchmark, so the full pipeline
  can actually be observed running end to end before scaling anything up.
- **One class genuinely unsolved**: `vehicle_human` has no labeled source
  anywhere in this pipeline yet — see the problem section above. Any demo
  built on current data is honestly a 3-class result, not 4.

None of this changes the vision. It's the difference between "the pipeline
exists" and "the pipeline has been proven to run" — this phase of work is
about closing that gap with real, observed evidence at each step, not about
skipping straight to a polished demo on unverified plumbing.

---

## References

- Zhu, W. & Beroza, G.C. (2018). *PhaseNet: A Deep-Neural-Network-Based
  Seismic Arrival Time Picking Method*. [arXiv:1803.03211](https://arxiv.org/abs/1803.03211)
- Münchmeyer, J. et al. (2022). *SeisBench — A Toolbox for Machine Learning
  in Seismology*. [arXiv:2111.00786](https://arxiv.org/abs/2111.00786)
- Münchmeyer, J. et al. (2022). *Which Picker Fits My Data? A Quantitative
  Evaluation of Deep Learning Based Seismic Pickers*. [JGR Solid Earth](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2021JB023499)
- Woollam, J. et al. (2019). *Convolutional Neural Network for Seismic
  Phase Classification, Performance Demonstration over a Local Seismic
  Network*. Seismological Research Letters 90(2A) — origin of the Iquique
  benchmark dataset.
- Mousavi, S.M. et al. — [STEAD dataset repository](https://github.com/smousavi05/STEAD),
  CC BY 4.0. Not currently used (see "Current state"), but the licensing
  verification and architecture decisions in this repo were built against it.
