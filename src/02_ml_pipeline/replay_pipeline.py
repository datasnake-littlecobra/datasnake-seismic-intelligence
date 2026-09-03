"""Idempotent replay pipeline: classify gold-layer windows and upsert into
vibration_classified_events.

This substitutes for a live sensor feed in Phase 1 (no hardware sensor yet —
see CLAUDE.md's phased scope). Re-running this script on the same gold data
must not create duplicate rows: it upserts on `event_id` (deterministic hash
of dataset+window_id), matching the idempotent-ingest SLA already established
elsewhere in this repo's ingestion scripts (usgs_seismic.py's
`ON CONFLICT (event_id) DO NOTHING`).

Follows this repo's existing DB-connection convention (see
src/01_data_ingestion/usgs_seismic.py) rather than introducing a new one.

MODEL: classify_window() below calls SeisBench's pretrained PhaseNet for
real (Stage 1 of docs/MODEL_STRATEGY.md's two-stage plan) — it is no longer
a stub. Loading the pretrained weights requires downloading them from
SeisBench's remote repository; that download is reachable from GitHub
Actions runners but blocked by this project's dev sandbox's network policy
(confirmed directly — the same class of restriction already documented for
STEAD/Iquique in docs/MODULE2_ARCHITECTURE.md's troubleshooting log, not a
new problem). The forward-pass logic and the preprocessing it depends on
were verified locally against a real window from data/stead_sample/ using
an untrained model instance (no download needed for that — see
classify_window()'s docstring for exactly what was and wasn't verified
this way) before being wired in here.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import torch
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

with open(ROOT / "config_vibration.yaml") as f:
    CFG = yaml.safe_load(f)

GOLD_DIR = ROOT / "data" / "module2_vibration" / "gold"
SILVER_DIR = ROOT / "data" / "module2_vibration" / "silver"

log_cfg = CFG["logging"]
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=getattr(logging, log_cfg["level"]),
    format=log_cfg["format"],
    datefmt=log_cfg["datefmt"],
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_cfg["file"])],
)
log = logging.getLogger(__name__)


def get_connection() -> psycopg2.extensions.connection:
    """Prefers individual DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD env vars
    over a single DATABASE_URL string, when the individual ones are present.

    Why: a password containing special characters (e.g. '@') breaks a
    pre-assembled connection-string URL unless it's percent-encoded by
    whoever sets it — an easy, easy-to-miss mistake (hit for real: a
    literal '@' in the password got parsed as part of the hostname,
    producing a "could not translate host name" error that had nothing to
    do with the actual hostname). Passing the password to psycopg2 as its
    own keyword argument sidesteps URL-encoding entirely — psycopg2 treats
    it as an opaque credential, not something needing escaping — so this
    class of bug can't recur for anyone using the individual vars.

    DATABASE_URL is still supported as a fallback for anyone who already
    has a correctly-encoded one.
    """
    host = os.getenv("DB_HOST")
    password = os.getenv("DB_PASSWORD")
    user = os.getenv("DB_USER")
    if host and password and user:
        # No default for DB_USER: Supabase's pooler requires the project-ref
        # suffix (e.g. "postgres.abcdefgh"), not plain "postgres" — a silent
        # default here would produce a wrong-but-plausible-looking value
        # instead of a clear error.
        return psycopg2.connect(
            host=host,
            port=os.getenv("DB_PORT", "6543"),
            dbname=os.getenv("DB_NAME", "postgres"),
            user=user,
            password=password,
        )

    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Neither DB_HOST+DB_USER+DB_PASSWORD nor DATABASE_URL is set — "
            "see .env.example. Prefer the individual DB_* variables: they "
            "avoid needing to percent-encode special characters in the "
            "password by hand."
        )
    return psycopg2.connect(url)


def deterministic_event_id(dataset: str, window_id: str) -> str:
    """Same (dataset, window_id) always produces the same event_id, so a
    rerun upserts the same row instead of inserting a duplicate."""
    digest = hashlib.sha256(f"{dataset}:{window_id}".encode()).hexdigest()[:32]
    return str(uuid.UUID(digest))


@lru_cache(maxsize=None)
def _load_silver_windows(dataset: str) -> np.lib.npyio.NpzFile:
    """Loads (and caches, once per dataset per process) the silver-layer
    window arrays classify_window() needs — the gold CSV alone only has
    labels/splits/ids, not the actual waveform. Cached so a 50+ row replay
    run opens this file once, not once per row."""
    path = SILVER_DIR / f"{dataset}_silver_windows.npz"
    if not path.exists():
        raise FileNotFoundError(f"Run silver_clean.py --dataset {dataset} first")
    return np.load(path)


@lru_cache(maxsize=1)
def _load_model():
    """Loads SeisBench's pretrained PhaseNet once per process. Deliberately
    lazy — only called from inside classify_window(), never at import time
    — so merely importing this module (e.g. from a test) never triggers a
    multi-MB weight download.

    "stead" here names which published, pretrained WEIGHT FILE to fetch —
    not a claim that STEAD itself is a trained model. See
    docs/MODEL_STRATEGY.md for the full explanation (written after this
    exact question came up for real).
    """
    import seisbench.models as sbm

    model = sbm.PhaseNet.from_pretrained("stead")
    model.eval()
    return model


def _phasenet_normalize(window: np.ndarray) -> np.ndarray:
    """Reproduces PhaseNet's own pre-inference normalization — its
    `annotate_batch_pre` under `norm="std"` (the pretrained "stead"
    weights' default): per-channel mean-subtract, then divide by
    per-channel std (+1e-10 to avoid a divide-by-zero on a dead channel).

    Silver-layer windows are already peak-normalized (unit max-abs) by
    silver_clean.py's normalize(), for reasons unrelated to any one model.
    That doesn't need undoing first: a z-score is invariant to any prior
    positive-scalar rescaling of the input, so running this on the
    already peak-normalized window produces the exact same result PhaseNet
    would compute from the raw trace itself.
    """
    mean = window.mean(axis=-1, keepdims=True)
    std = window.std(axis=-1, keepdims=True)
    return (window - mean) / (std + 1e-10)


def _peak_sustained_probability(prob_curve: np.ndarray, sustain_samples: int) -> float:
    """Smooths a per-timestep probability curve with a moving average over
    `sustain_samples` consecutive timesteps, then returns the highest value
    that smoothed curve ever reaches.

    WHY THIS EXISTS: the first real CI run of classify_window() (before
    this function existed) reported confidence ~1.000 on every single row,
    for both classes, with zero abstains — too uniform to be a real
    signal. Root cause: taking the single highest instantaneous
    probability anywhere in a 3000-sample window is close to a tautology
    for the "how sure are we this window is quiet" question — almost any
    30-second clip, earthquake or not, has at least one genuinely quiet
    instant, so that number is almost always going to be near 1 regardless
    of the window's actual content. It's like asking "was there ever a
    quiet half-second in this 30-second video" — nearly always yes, even
    during an action scene.

    A moving average fixes this by requiring the high probability to
    HOLD for a realistic arrival-length stretch (default: half a second,
    50 samples at 100Hz), not just one instant. A single stray high
    sample surrounded by low ones gets diluted by the average — e.g. one
    sample at 1.0 surrounded by 49 samples near 0 averages out to about
    1/50 = 0.02, nowhere near a detection threshold. A genuine phase
    arrival, in contrast, isn't a single flickering sample in the model's
    output — it naturally spans many consecutive samples — so it stays
    high even after averaging. See
    src/02_ml_pipeline/tests/test_phasenet_confidence.py for this exact
    behavior demonstrated on synthetic data.

    Falls back to a plain max if the window is shorter than the smoothing
    stretch (shouldn't happen with this project's fixed 30s windows, but a
    silent divide-by-near-nothing on a tiny array is worse than this).
    """
    if len(prob_curve) < sustain_samples:
        return float(prob_curve.max())
    smoothing_kernel = np.ones(sustain_samples) / sustain_samples
    smoothed = np.convolve(prob_curve, smoothing_kernel, mode="valid")
    return float(smoothed.max())


def classify_window(dataset: str, row: pd.Series) -> dict:
    """Runs SeisBench's pretrained PhaseNet on this window's real waveform
    and derives a window-level classification from its output — this is
    the seam between the pipeline and the model, kept isolated so a future
    fine-tuned/custom model (Stage 2 of docs/MODEL_STRATEGY.md) only needs
    to change what happens inside this function.

    WHY A DIRECT FORWARD PASS, NOT model.classify()/model.annotate():
    verified directly against a real seisbench==0.7.0 install (the version
    pinned in requirements.txt) — not assumed — that `classify()` expects
    an obspy.Stream and returns a ClassifyOutput exposing `.picks` (a list
    of arrival picks: phase, time, peak value), with no `event_type`,
    `confidence`, or `severity_score` attributes at all. That's a
    different, wrong interface than what an earlier speculative version of
    this code (and of app/modules/seismic/classify.py) assumed. Calling
    the model's forward pass directly on our already-filtered,
    already-windowed (channels, samples) array sidesteps needing to wrap
    our data in an obspy Stream, and was confirmed to work correctly on a
    real (3, 3000) window from data/stead_sample/ using an untrained
    PhaseNet instance (no weight download needed to check this — the
    interface and array shapes don't depend on which weights are loaded)
    — output shape (batch, 3, time), channels ordered N/P/S per the
    model's own `labels` attribute ("NPS"), confirmed the same way.

    WHAT THIS HEURISTIC IS AND ISN'T: PhaseNet is a phase-PICKING model —
    per timestep, it outputs a probability for Noise / P-wave / S-wave. It
    was never trained to emit one "is this an earthquake" label per
    window. The rule used here — "seismic" if the model's P or S
    probability stays high for a realistic arrival-length stretch anywhere
    in the window (see _peak_sustained_probability()) and clears
    `detection_threshold`, "environmental" otherwise — reuses PhaseNet's
    own detection convention (config's default of 0.3 matches SeisBench's
    own default pick threshold) rather than inventing a new one. It
    structurally cannot produce "vehicle_human": no dataset behind this
    pretrained model labels that class, so there's no signal for it to
    have learned — see gold_label_split.py's docstring and
    docs/MODEL_STRATEGY.md.

    model_version is a fixed label identifying OUR integration (pretrained
    "stead" weights, unmodified, no fine-tuning) — not a SeisBench-internal
    version string, since from_pretrained("stead") always resolves to the
    latest weights published under that name. A future fine-tuned or
    custom-trained model should get a visibly different model_version so
    rows produced by each are distinguishable in the database.
    """
    model = _load_model()
    windows = _load_silver_windows(dataset)
    window = windows[row["window_id"]].astype(np.float32)
    normalized = _phasenet_normalize(window)

    with torch.no_grad():
        probs = model(torch.from_numpy(normalized).unsqueeze(0))  # (1, 3, time); channels = N, P, S

    sustain_samples = int(CFG["model"]["sustain_window_sec"] * CFG["model"]["sampling_rate_hz"])
    noise_curve, p_curve, s_curve = (probs[0, i, :].numpy() for i in range(3))
    noise_score = _peak_sustained_probability(noise_curve, sustain_samples)
    seismic_score = max(
        _peak_sustained_probability(p_curve, sustain_samples),
        _peak_sustained_probability(s_curve, sustain_samples),
    )

    detection_threshold = CFG["model"]["detection_threshold"]
    review_threshold = CFG["model"]["review_threshold"]

    if seismic_score >= detection_threshold:
        event_type = "seismic"
        confidence = seismic_score
    else:
        event_type = "environmental"
        confidence = noise_score

    low_confidence = confidence < review_threshold
    return {
        "event_type": event_type,
        "confidence": confidence,
        # Severity/magnitude estimation isn't in scope yet — no model is
        # wired in for it. None here is an honest "not computed", not a
        # real zero-severity claim.
        "severity_score": None,
        "model_version": "phasenet-stead-pretrained-v1",
        "abstain": low_confidence,
        "requires_human_review": low_confidence,
    }


def upsert_events(conn: psycopg2.extensions.connection, rows: list[dict], pipeline_run_id: str) -> int:
    query = """
        INSERT INTO vibration_classified_events (
            event_id, sensor_id, event_time, event_type, confidence, severity_score,
            scenario_family_id, raw_waveform_ref, split, source_dataset,
            data_version, model_version, pipeline_run_id, evidence, abstain, requires_human_review
        ) VALUES %s
        ON CONFLICT (event_id) DO UPDATE SET
            confidence = EXCLUDED.confidence,
            severity_score = EXCLUDED.severity_score,
            evidence = EXCLUDED.evidence,
            abstain = EXCLUDED.abstain,
            requires_human_review = EXCLUDED.requires_human_review
    """
    values = [
        (
            r["event_id"],
            r["sensor_id"],
            r["event_time"],
            r["event_type"],
            r["confidence"],
            r["severity_score"],
            r["scenario_family_id"],
            r["raw_waveform_ref"],
            r["split"],
            r["source_dataset"],
            r["data_version"],
            r["model_version"],
            pipeline_run_id,
            json.dumps(r["evidence"]),
            r["abstain"],
            r["requires_human_review"],
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, query, values)
    conn.commit()
    return len(values)


def run(dataset: str, data_version: str = "v1") -> int:
    gold_path = GOLD_DIR / f"{dataset}_gold.csv"
    if not gold_path.exists():
        raise FileNotFoundError(f"Run gold_label_split.py --dataset {dataset} first")

    gold = pd.read_csv(gold_path)
    pipeline_run_id = str(uuid.uuid4())

    rows = []
    for _, row in gold.iterrows():
        classification = classify_window(dataset, row)
        rows.append(
            {
                "event_id": deterministic_event_id(dataset, row["window_id"]),
                "sensor_id": f"replay:{dataset}",
                "event_time": pd.Timestamp.utcnow().isoformat(),
                "event_type": classification["event_type"],
                "confidence": classification["confidence"],
                "severity_score": classification["severity_score"],
                "scenario_family_id": row["scenario_family_id"],
                "raw_waveform_ref": row["window_id"],
                "split": row["split"],
                "source_dataset": row["source_dataset"],
                "data_version": data_version,
                "model_version": classification["model_version"],
                "evidence": {
                    "window_id": row["window_id"],
                    "source_idx": int(row["source_idx"]),
                    # The known correct answer from gold_label_split.py's
                    # STEAD-vocabulary mapping — NOT the model's guess
                    # (that's the event_type column above). Stored here
                    # specifically so accuracy can be checked with one SQL
                    # query against the live table (compare this to
                    # event_type) instead of needing the CI run's
                    # downloaded gold-layer CSV artifact. See
                    # docs/TECHNICAL_DEBT.md item 5.
                    "ground_truth_event_type": row["event_type"],
                },
                "abstain": classification["abstain"],
                "requires_human_review": classification["requires_human_review"],
            }
        )

    conn = get_connection()
    try:
        n_written = upsert_events(conn, rows, pipeline_run_id)
    finally:
        conn.close()

    log.info(f"Replay run {pipeline_run_id}: upserted {n_written} rows for {dataset}")
    return n_written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Idempotent replay pipeline for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    parser.add_argument("--data-version", default="v1")
    args = parser.parse_args()
    run(args.dataset, args.data_version)
