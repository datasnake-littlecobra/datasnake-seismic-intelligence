"""Shared reader for the small, real dataset samples committed under
data/<dataset>_sample/ (produced once, locally, by scripts/extract_stead_sample.py
— see that script and docs/MODULE2_ARCHITECTURE.md's troubleshooting log for
why: SeisBench's own STEAD/Iquique loaders require an all-or-nothing
multi-GB download with no partial-fetch option, not viable in automated CI).

Both bronze_ingest.py and silver_clean.py need to look up a waveform by
trace_name from these files — kept in one place so there's a single source
of truth for the file layout and array orientation, rather than duplicating
(and risking drifting) the same lookup logic in two files.
"""

from pathlib import Path

import h5py
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]


def sample_dir(dataset: str) -> Path:
    return ROOT / "data" / f"{dataset}_sample"


def load_metadata(dataset: str) -> pd.DataFrame:
    path = sample_dir(dataset) / f"{dataset}_sample_metadata.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"No local sample metadata for {dataset!r} at {path}. "
            f"See scripts/extract_stead_sample.py to produce one — this "
            f"dataset hasn't had that done yet."
        )
    return pd.read_csv(path)


def get_waveform(dataset: str, trace_name: str) -> np.ndarray:
    """Returns a (channels, samples) array — transposed from the extracted
    file's native (samples, channels) layout (confirmed via direct
    inspection: STEAD's real shape here is (6000, 3)) so it matches the
    channel-first convention the rest of this pipeline (silver_clean.py's
    filtering/windowing, which operates on the last axis as time) expects.
    """
    path = sample_dir(dataset) / f"{dataset}_sample_waveforms.hdf5"
    with h5py.File(path, "r") as f:
        if trace_name not in f:
            raise KeyError(
                f"{trace_name!r} not found in {path}. "
                f"Available keys (first 5): {list(f.keys())[:5]}"
            )
        return f[trace_name][()].T
