"""Verifies _peak_sustained_probability() actually does what it's for:
telling a real, sustained detection apart from a single-sample fluke —
this is the fix for the first real CI run reporting confidence ~1.000 on
every row regardless of content (see docs/TECHNICAL_DEBT.md item 5). No
network/model download needed: this tests the smoothing math only.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from replay_pipeline import _peak_sustained_probability


def test_a_lone_spike_is_smoothed_away():
    """A single high-probability sample surrounded by near-zero samples —
    exactly what a spurious, meaningless blip looks like — should score
    far below any reasonable detection threshold once smoothed."""
    curve = np.zeros(3000, dtype=np.float32)
    curve[1500] = 1.0

    score = _peak_sustained_probability(curve, sustain_samples=50)

    assert score < 0.05  # ~1/50 from averaging one high sample into 50


def test_a_sustained_plateau_stays_high():
    """A genuine arrival isn't a single flickering sample — it spans many
    consecutive timesteps. That should survive smoothing almost intact."""
    curve = np.full(3000, 0.05, dtype=np.float32)
    curve[1000:1100] = 0.95  # 1 full second of sustained high probability

    score = _peak_sustained_probability(curve, sustain_samples=50)

    assert score > 0.9


def test_quiet_moment_in_an_otherwise_active_window_does_not_dominate():
    """This is the exact bug being fixed: a single quiet instant inside an
    otherwise noisy/active window used to make the 'environmental'
    confidence read as ~1.0 regardless of what else was in the window.
    A curve that's mostly at 0.3 (never truly quiet for long) with one
    isolated near-1.0 dip should NOT score high after smoothing."""
    curve = np.full(3000, 0.3, dtype=np.float32)
    curve[1500] = 0.99  # one isolated instant, not a sustained quiet stretch

    score = _peak_sustained_probability(curve, sustain_samples=50)

    assert score < 0.35  # close to the 0.3 baseline, not anywhere near 0.99


def test_falls_back_to_max_on_a_curve_shorter_than_the_sustain_window():
    curve = np.array([0.1, 0.9, 0.2], dtype=np.float32)

    score = _peak_sustained_probability(curve, sustain_samples=50)

    assert score == pytest.approx(0.9, abs=1e-5)
