# Parametric Insurance, Basis Risk, and EP Curves — A Working Primer

Written for reference, not as legal or actuarial advice. This doc exists so
you have a place to come back to when the vocabulary gets fuzzy, and
something concrete to hand an investor or an insurance-firm contact who
wants the real mechanics, not a pitch-deck gloss. It also states plainly
where our project's job ends and a licensed insurer's/actuary's job begins
— that boundary matters, and blurring it would undercut credibility with
anyone who actually knows this space.

---

## 1. Traditional (indemnity) insurance, briefly, for contrast

The insurance you're used to — home, auto, most commercial coverage — is
**indemnity insurance**: after a loss happens, an adjuster assesses the
actual damage, and the payout is sized to match that damage (up to policy
limits). This is accurate but slow — claims adjustment after a major
disaster can take weeks to months, and it requires someone to physically
inspect what happened.

## 2. Parametric insurance — what it actually is

A **parametric** (or "index-based") policy pays out based on whether a
predefined, objectively measurable **trigger** was crossed — not based on
assessed damage. Example structure:

> "If SAR-measured flood extent covers more than 30% of this parcel
> during a single event, pay out $50,000. If it covers more than 60%,
> pay out $150,000."

No adjuster visits the property. No dispute over "how bad was it, really."
The index crossed the line, or it didn't — the payout follows automatically
and fast (days, not months). This speed is the entire commercial selling
point: for a farmer or a small property owner in a disaster, cash in days
versus cash in months is transformative.

**What we are NOT doing**: setting the actual premium a customer pays. That's
actuarial pricing — a separate, licensed discipline involving capital
reserves, regulatory approval, reinsurance treaties, and company-specific
risk appetite. Our job is narrower and, we'd argue, more foundational:
**building the trustworthy index and trigger-design evidence an
insurer/actuary would need** to design and price a product responsibly.
Think of us as the data/signal layer underneath their pricing decision, not
a replacement for it.

## 3. Basis risk — the central problem this whole project exists to address

**Basis risk** is the mismatch between what the trigger measures and what
the policyholder actually experienced. Two failure directions, both bad:

- **False negative (worse for the customer)**: real, serious flood damage
  occurred, but the index didn't cross the trigger threshold — no payout,
  despite a real loss. This is the scenario that kills trust in parametric
  products and gets them abandoned by the communities they're meant to
  serve.
- **False positive (worse for the insurer)**: the index crossed the
  trigger, payout is owed, but the actual property damage was minor or
  nonexistent. Expensive and erodes the insurer's confidence in the
  product.

**Why existing solutions don't solve this well**, per the original framing
of this project: coarse satellite/rainfall reanalysis products (e.g. ERA5)
average over large grid cells and lag real-time by hours to days — too
blunt for a flash flood that hits one neighborhood and misses the next.
Sensor-based products (FloodFlash, Descartes Underwriting) solve this
precisely, but only where a physical sensor is already installed on a
known, developed property. **Nobody is solving this for remote or
underserved terrain that has no existing sensor coverage** — which is
exactly the gap a satellite-based (SAR), no-hardware-required index can
fill, if it's accurate enough to keep basis risk low.

## 4. EP curves — what they are, and why they're the actual deliverable

An **EP curve** (exceedance probability curve) answers: *"in any given
year, what's the probability that losses (or, here, our index value) will
exceed X?"* Plotted, it's a curve of index/loss magnitude on one axis and
probability-of-exceedance (or its inverse, **return period** — "a 1-in-100-
year event") on the other.

**Why this is the artifact that actually matters to an underwriter**,
more than a single "risk score": a bare score (e.g. "72/100") answers "is
this risky," but an EP curve answers the question underwriting and
reinsurance capital planning actually need answered: *"how often, and how
severely, would this trigger have fired historically — and is that
frequency/severity something we can safely underwrite and reinsure
against?"* Setting the trigger threshold itself is a negotiation informed
directly by this curve: set it too low, and the product pays out too often
(uneconomical for the insurer); set it too high, and real losses go
uncompensated (basis risk hits the policyholder, and the product loses
trust).

## 5. Backtesting — why it's the credibility proof, not a nice-to-have

**Backtesting** means running our index against real historical flood
events, at that same location, and checking: did the index cross the
trigger when real, documented flooding occurred, and stay below it when
it didn't? This is the single most convincing thing we can show an
investor or an insurance-firm contact, because it's falsifiable and
concrete — not "trust our model," but "here is exactly what our index
would have said during Hurricane Harvey, and here's the real, independently
documented flood extent from that event to compare it against."

This is also precisely why picking a well-documented historical event for
v1 (see the geography discussion elsewhere) matters so much: a backtest is
only as credible as the ground truth you're checking against.

## 6. How our system's pieces map onto this vocabulary

| Our output | What it is, in this framing |
|---|---|
| The index value at a location/time | The measured, objective signal (analogous to a rainfall gauge reading, but derived from SAR flood-extent detection) |
| `confidence` / `abstain` / `requires_human_review` | Our honesty layer — the same governance fields used in Module 2, now applied here: don't claim certainty the underlying detection doesn't support |
| The EP curve, built from many historical index values | The actual artifact an underwriter uses to reason about trigger placement |
| The backtest report | The evidence that the index and the EP curve derived from it are trustworthy, checked against real, independently documented flood events |
| `scenario_family_id` (reused from Module 2's pattern) | Groups readings belonging to the same real-world flood event, so backtesting one event doesn't get diluted/confused with another |

## 7. Quick glossary

- **Trigger**: the predefined condition that causes a payout (e.g. "index
  > threshold").
- **Payout structure**: how much is paid, and how it scales with how far
  the trigger was exceeded (binary, tiered, or continuous).
- **Basis risk**: mismatch between the trigger and real policyholder loss
  (Section 3).
- **Indemnity vs. parametric**: damage-assessed payout vs. trigger-based
  payout (Section 1–2).
- **EP curve / exceedance probability**: probability that a given
  magnitude is exceeded in a period (Section 4).
- **Return period**: the inverse framing of the same curve — "a 1-in-N-year
  event."
- **Backtest**: replaying real historical events through the index/trigger
  to check it would have behaved correctly (Section 5).

## 8. Where this could go if we do talk to real insurance firms later

Not needed for the MVP, but worth having in mind: a real conversation with
an insurer or reinsurer would likely ask about (a) the historical sample
size behind our EP curve (more events = more statistically credible — the
same "how much data is enough" question we already ran into with Module 2),
(b) our SAR detection method's own false-positive/false-negative rate
independent of any specific trigger threshold, and (c) how the index would
be delivered operationally (API, on what latency, at what SLA) if it were
actually underwriting a live product. None of this blocks starting — it's
what "more prominent and trustworthy" (your words) looks like a few
iterations out.
