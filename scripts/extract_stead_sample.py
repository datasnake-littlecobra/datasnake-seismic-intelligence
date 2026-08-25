"""One-time, LOCAL-ONLY bootstrap: extract a small real STEAD sample from
full downloaded chunk files into a small, committable dataset.

NOT part of the automated pipeline (src/02_ml_pipeline/) and not run by CI —
run this by hand, once, on a machine with enough disk/bandwidth to hold the
downloaded chunks (each ~14-16GB). The small output this produces is what
gets committed to the repo (or uploaded somewhere reachable); bronze_ingest.py
then gets rewritten to read from that small output directly, with no
SeisBench download call in the automated path at all.

Expects chunk files exactly as downloaded from
https://github.com/smousavi05/STEAD (one CSV + one HDF5 per chunk — no need
to merge chunks together, this reads each chunk's own pair directly).

Usage:
    pip install pandas h5py
    python scripts/extract_stead_sample.py \
        --noise-csv chunk1.csv --noise-hdf5 chunk1.hdf5 \
        --eq-csv chunk2.csv --eq-hdf5 chunk2.hdf5 \
        --n-per-class 25 \
        --out-dir stead_sample

CAVEAT: the raw (pre-SeisBench) STEAD HDF5 internal layout hasn't been
independently verified here — this tries the documented "data/<trace_name>"
group first, falls back to a flat top-level key, and prints the file's
actual top-level keys if neither matches, rather than failing silently.
"""

import argparse
from pathlib import Path

import h5py
import pandas as pd


def extract_sample(csv_path: Path, hdf5_path: Path, n: int, category_filter: str) -> tuple[pd.DataFrame, dict]:
    meta = pd.read_csv(csv_path)
    if "trace_category" not in meta.columns:
        raise ValueError(
            f"{csv_path} has no 'trace_category' column. Actual columns: {list(meta.columns)}"
        )

    subset = meta[meta["trace_category"] == category_filter].head(n)
    if len(subset) < n:
        print(
            f"  warning: only found {len(subset)} rows matching "
            f"trace_category == {category_filter!r} (asked for {n}) in {csv_path}"
        )

    waveforms = {}
    with h5py.File(hdf5_path, "r") as f:
        for trace_name in subset["trace_name"]:
            if "data" in f and trace_name in f["data"]:
                waveforms[trace_name] = f["data"][trace_name][()]
            elif trace_name in f:
                waveforms[trace_name] = f[trace_name][()]
            else:
                print(
                    f"  could not find trace {trace_name!r} in {hdf5_path}.\n"
                    f"  Top-level keys in this file: {list(f.keys())[:10]}\n"
                    f"  If one of those looks like it should contain the waveforms, "
                    f"report this back and the script's key-lookup logic needs adjusting."
                )
                raise KeyError(trace_name)

    return subset, waveforms


def main():
    parser = argparse.ArgumentParser(description="Extract a small STEAD sample from downloaded chunks")
    parser.add_argument("--noise-csv", type=Path, required=True)
    parser.add_argument("--noise-hdf5", type=Path, required=True)
    parser.add_argument("--eq-csv", type=Path, required=True)
    parser.add_argument("--eq-hdf5", type=Path, required=True)
    parser.add_argument("--n-per-class", type=int, default=25)
    parser.add_argument("--out-dir", type=Path, default=Path("stead_sample"))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Extracting {args.n_per_class} 'noise' examples from {args.noise_csv} / {args.noise_hdf5} ...")
    noise_meta, noise_waves = extract_sample(args.noise_csv, args.noise_hdf5, args.n_per_class, "noise")

    print(f"Extracting {args.n_per_class} 'earthquake_local' examples from {args.eq_csv} / {args.eq_hdf5} ...")
    eq_meta, eq_waves = extract_sample(args.eq_csv, args.eq_hdf5, args.n_per_class, "earthquake_local")

    combined_meta = pd.concat([noise_meta, eq_meta], ignore_index=True)
    meta_out = args.out_dir / "stead_sample_metadata.csv"
    combined_meta.to_csv(meta_out, index=False)

    waveforms_out = args.out_dir / "stead_sample_waveforms.hdf5"
    with h5py.File(waveforms_out, "w") as out_f:
        for trace_name, array in {**noise_waves, **eq_waves}.items():
            out_f.create_dataset(trace_name, data=array, compression="gzip")

    size_mb = waveforms_out.stat().st_size / (1024 * 1024)
    print("\nDone.")
    print(f"  metadata  -> {meta_out} ({len(combined_meta)} rows)")
    print(f"  waveforms -> {waveforms_out} ({size_mb:.1f} MB)")
    print("\nCommit both files (or tell me where you've uploaded them) — "
          "bronze_ingest.py will be rewritten to read from these directly, "
          "no SeisBench download call in the automated path.")


if __name__ == "__main__":
    main()
