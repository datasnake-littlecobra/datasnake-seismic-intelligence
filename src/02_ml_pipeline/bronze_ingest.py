"""Bronze layer: pull a small STEAD/INSTANCE sample via SeisBench, unmodified.

Bronze = raw, as-is data. No filtering, no windowing, no labeling here —
that's silver_clean.py and gold_label_split.py. This script's only job is
"pull a known-good sample and record exactly what was pulled" (manifest.py).

NOTE ON EXECUTION ENVIRONMENT: this script needs outbound network access to
SeisBench's data mirrors (zenodo.org / huggingface.co). It runs via
.github/workflows/pipeline.yml on GitHub-hosted runners, which have normal
outbound access — it will NOT run inside a network-restricted sandbox
(the environment this was originally built in had no such access, which is
why this moved to CI instead of staying a manual/local step).

NOTE ON SEISBENCH API: SeisBench's exact dataset class name for INSTANCE has
changed across versions (e.g. InstanceCountsCombined / InstanceGM / InstanceNoise
in more recent releases vs. a single InstanceCounts class in older ones). Verify
the class name against `import seisbench.data as sbd; dir(sbd)` for whatever
seisbench==0.7.0 (pinned in requirements.txt) actually ships, before relying
on the exact name used below.
"""

import argparse
import shutil
import time
from pathlib import Path

import yaml

import manifest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config_vibration.yaml"
BRONZE_DIR = ROOT / "data" / "module2_vibration" / "bronze"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _dir_size_mb(path: Path) -> float:
    """Best-effort recursive directory size, in MB. Used purely for the
    diagnostic logging below — not load-bearing for the pipeline logic."""
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def _log_download_diagnostics(cache_dir: Path, elapsed_sec: float) -> None:
    """Prints exactly what SeisBench actually downloaded and how long it took.

    Added because a prior CI run hit a 45-minute timeout on this exact step
    with no visibility into why — this instrumentation exists to answer that
    question empirically instead of guessing again. See the module docstring:
    the working theory is that SeisBench's dataset loader downloads its full
    backing archive on instantiation, before any `.metadata.iloc[:n]` slicing
    happens — meaning `sample_size` in config_vibration.yaml may currently
    have NO effect on how much gets downloaded, only on what gets used
    afterward. This log output is what will confirm or rule that out.
    """
    size_mb = _dir_size_mb(cache_dir)
    free_gb = shutil.disk_usage(cache_dir.parent if cache_dir.exists() else ROOT).free / (1024**3)
    print(
        f"[bronze diagnostics] cache_dir={cache_dir} downloaded={size_mb:.1f}MB "
        f"elapsed={elapsed_sec:.1f}s free_disk={free_gb:.2f}GB"
    )


def pull_stead_sample(sample_size: int) -> tuple[Path, int]:
    import seisbench.data as sbd

    cache_dir = BRONZE_DIR / "stead_cache"
    start = time.monotonic()
    data = sbd.STEAD(sampling_rate=100, cache=str(cache_dir))
    _log_download_diagnostics(cache_dir, time.monotonic() - start)

    sample = data.metadata.iloc[:sample_size]
    out_path = BRONZE_DIR / "stead_sample_metadata.csv"
    sample.to_csv(out_path, index=False)
    return out_path, len(sample)


def pull_instance_sample(sample_size: int) -> tuple[Path, int]:
    import seisbench.data as sbd

    # See module docstring — verify this class name against the installed
    # seisbench version before running.
    cache_dir = BRONZE_DIR / "instance_cache"
    start = time.monotonic()
    data = sbd.InstanceCountsCombined(sampling_rate=100, cache=str(cache_dir))
    _log_download_diagnostics(cache_dir, time.monotonic() - start)

    sample = data.metadata.iloc[:sample_size]
    out_path = BRONZE_DIR / "instance_sample_metadata.csv"
    sample.to_csv(out_path, index=False)
    return out_path, len(sample)


def run(dataset: str) -> Path:
    cfg = load_config()["datasets"][dataset]
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)

    if dataset == "stead":
        out_path, count = pull_stead_sample(cfg["sample_size"])
    elif dataset == "instance":
        out_path, count = pull_instance_sample(cfg["sample_size"])
    else:
        raise ValueError(f"Unknown dataset: {dataset}")

    checksum = manifest.checksum_file(out_path)
    manifest_path = manifest.write_manifest(
        dataset_name=cfg["name"],
        version="v1",
        source_url=cfg["source"],
        checksum=checksum,
        sample_count=count,
        license_name=cfg["license"],
    )
    print(f"Pulled {count} {cfg['name']} records -> {out_path}")
    print(f"Manifest written -> {manifest_path}")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bronze-layer ingest for Module 2")
    parser.add_argument("--dataset", choices=["stead", "instance"], required=True)
    args = parser.parse_args()
    run(args.dataset)
