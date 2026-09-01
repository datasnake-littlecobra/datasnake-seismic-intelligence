"""Seismic-specific inference call: waveform window -> ClassificationResult.

This is the only place in the FastAPI service that imports SeisBench/PyTorch
— keeps the shared routers/ layer free of any seismic-specific dependency,
so a future Module 3/4 doesn't inherit a torch import it doesn't need.

NOT CURRENTLY CALLED BY ANY ROUTE. GET /events (routers/events.py) reads
already-classified rows straight out of vibration_classified_events —
classification happens offline, in src/02_ml_pipeline/replay_pipeline.py,
not on demand here. This function exists for a possible future on-demand
endpoint and intentionally mirrors replay_pipeline.py's classify_window()
logic exactly, rather than a service-specific approach, so the two don't
silently drift apart. Keep them in sync if PhaseNet's expected
preprocessing or the seismic/environmental heuristic changes — duplicated
rather than imported because this service (deploys to Railway) and the ML
pipeline (runs in GitHub Actions) aren't a shared Python package today.

An earlier version of this file called `model.classify(window)` and read
`event_type`/`confidence`/`severity_score` attributes off the result. That
was a guess, and verified wrong against a real seisbench==0.7.0 install
(the version pinned in requirements.txt): `classify()` expects an
obspy.Stream, not a raw array, and returns a ClassifyOutput exposing
`.picks` (arrival picks), not those attributes at all. See
replay_pipeline.py's classify_window() docstring for the full verified
rationale behind the direct-forward-pass approach used here instead, and
docs/MODEL_STRATEGY.md for why PhaseNet — a phase-picker — can't emit a
single "event_type" label on its own in the first place.
"""

from functools import lru_cache

import numpy as np
import torch

from .schemas import ClassificationResult

# Matches config_vibration.yaml's model.detection_threshold/review_threshold
# — duplicated here for the same cross-deployment reason noted above.
DETECTION_THRESHOLD = 0.3
REVIEW_THRESHOLD = 0.5


@lru_cache(maxsize=1)
def _load_model():
    import seisbench.models as sbm

    # "stead" names which published, pretrained WEIGHT FILE to fetch, not
    # a claim that STEAD itself is a trained model — see
    # docs/MODEL_STRATEGY.md.
    model = sbm.PhaseNet.from_pretrained("stead")
    model.eval()
    return model


def _phasenet_normalize(window: np.ndarray) -> np.ndarray:
    """PhaseNet's own pre-inference normalization (`annotate_batch_pre`
    under `norm="std"`): per-channel mean-subtract, then divide by
    per-channel std. See replay_pipeline.py's identical helper for why
    this is correct even on data that's already been normalized upstream
    by some other scheme (a z-score is invariant to prior positive-scalar
    rescaling)."""
    mean = window.mean(axis=-1, keepdims=True)
    std = window.std(axis=-1, keepdims=True)
    return (window - mean) / (std + 1e-10)


def classify_waveform(window: np.ndarray) -> ClassificationResult:
    """window: a (channels, samples) array — same shape convention as
    local_sample.get_waveform()/silver_clean.py's windows elsewhere in
    this project.

    PhaseNet outputs a per-timestep probability for Noise/P-wave/S-wave,
    not a single event-type label — "seismic" here means its peak P or S
    probability anywhere in the window cleared DETECTION_THRESHOLD (0.3,
    matching SeisBench's own default pick threshold). It cannot produce
    "vehicle_human": no dataset behind this pretrained model labels that
    class. See gold_label_split.py's docstring and docs/MODEL_STRATEGY.md.
    """
    model = _load_model()
    normalized = _phasenet_normalize(window.astype(np.float32))

    with torch.no_grad():
        probs = model(torch.from_numpy(normalized).unsqueeze(0))  # (1, 3, time); channels = N, P, S

    noise_score = float(probs[0, 0, :].max())
    seismic_score = float(probs[0, 1:, :].max())  # max over P and S channels, across time

    if seismic_score >= DETECTION_THRESHOLD:
        event_type = "seismic"
        confidence = seismic_score
    else:
        event_type = "environmental"
        confidence = noise_score

    low_confidence = confidence < REVIEW_THRESHOLD
    return ClassificationResult(
        event_type=event_type,
        confidence=confidence,
        # Severity/magnitude estimation isn't in scope yet — no model is
        # wired in for it. None is an honest "not computed".
        severity_score=None,
        abstain=low_confidence,
        requires_human_review=low_confidence,
    )
