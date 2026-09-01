"""Verifies _phasenet_normalize() actually reproduces PhaseNet's own
pre-inference normalization (its `annotate_batch_pre` under `norm="std"`:
per-channel mean-subtract, then divide by per-channel std) — this is
duplicated logic (also present, deliberately, in
app/modules/seismic/classify.py — see that file's docstring for why), and
getting the formula wrong would silently degrade every real classification
without raising any error. No network/model download needed: this tests
the preprocessing math only, not the model itself.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replay_pipeline import _phasenet_normalize


def test_output_is_zero_mean_unit_std_per_channel():
    rng = np.random.default_rng(42)
    window = rng.normal(loc=5.0, scale=3.0, size=(3, 3000)).astype(np.float32)

    normalized = _phasenet_normalize(window)

    assert np.allclose(normalized.mean(axis=-1), 0.0, atol=1e-5)
    assert np.allclose(normalized.std(axis=-1), 1.0, atol=1e-5)


def test_invariant_to_prior_positive_scalar_rescaling():
    """silver_clean.py peak-normalizes windows before they ever reach this
    function. A z-score is invariant to any prior positive-scalar rescale
    of the input, so normalizing a peak-normalized window must produce the
    same result as normalizing the raw (unscaled) window directly — this
    is the exact property replay_pipeline.py's docstring relies on to
    justify not "undoing" silver's normalization first."""
    rng = np.random.default_rng(7)
    raw = rng.normal(loc=-2.0, scale=10.0, size=(3, 3000)).astype(np.float32)
    peak_normalized = raw / np.max(np.abs(raw))

    assert np.allclose(_phasenet_normalize(raw), _phasenet_normalize(peak_normalized), atol=1e-4)


def test_handles_a_dead_flat_channel_without_dividing_by_zero():
    window = np.zeros((3, 3000), dtype=np.float32)
    window[0] = 1.0  # channel 0 is a nonzero constant -> std is exactly 0

    normalized = _phasenet_normalize(window)

    assert np.all(np.isfinite(normalized))
