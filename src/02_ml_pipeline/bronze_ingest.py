"""Bronze layer: read the small, locally-extracted real STEAD sample,
unmodified, and record exactly what was used.

Bronze = raw, as-is data. No filtering, no windowing, no labeling here —
that's silver_clean.py and gold_label_split.py.

DATA SOURCE: reads data/<dataset>_sample/ — a small (tens of examples),
real, licensed sample extracted from the full dataset by
scripts/extract_stead_sample.py, run once, locally, by hand. This is real
STEAD data (CC BY 4.0), just pre-extracted rather than pulled fresh on
every run.

WHY NOT PULL LIVE VIA SEISBENCH: verified directly (not assumed) that
SeisBench's STEAD/Iquique loaders require an all-or-nothing multi-GB
download with no partial-fetch option — confirmed by an actual CI run that
hit an 84.9GB download target regardless of any sample-size setting, and
by reading SeisBench's own source (STEAD's loader has no `chunks`
parameter; Iquique's `_download_dataset` isn't even implemented). Not
viable in an automated job. See docs/MODULE2_ARCHITECTURE.md's
troubleshooting log for the full investigation.
"""

import argparse
from pathlib import Path

import yaml

import local_sample
import manifest

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config_vibration.yaml"
BRONZE_DIR = ROOT / "data" / "module2_vibration" / "bronze"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def pull_sample(dataset: str, sample_size: int) -> tuple[Path, int]:
    meta = local_sample.load_metadata(dataset)
    sample = meta.iloc[:sample_size]
    out_path = BRONZE_DIR / f"{dataset}_sample_metadata.csv"
    sample.to_csv(out_path, index=False)
    return out_path, len(sample)


def run(dataset: str) -> Path:
    cfg = load_config()["datasets"][dataset]
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)

    out_path, count = pull_sample(dataset, cfg["sample_size"])

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
