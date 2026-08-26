# Module 2: Seismic/Vibration Intelligence — ML Pipeline

Bronze/silver/gold pipeline as inspectable, testable scripts. The notebooks
in `notebooks/module2_seismic/` are thin wrappers over these — run the
scripts directly for automation, or through the notebooks for EDA/visual
sanity checks.

---

## Files

| File | Purpose |
|---|---|
| `manifest.py` | Versioned dataset manifest read/write — dataset lineage/reproducibility |
| `local_sample.py` | Shared reader for `data/<dataset>_sample/` — the small, real, pre-extracted samples this pipeline actually runs against |
| `bronze_ingest.py` | Read the local STEAD sample (not a live SeisBench pull — see `docs/MODULE2_ARCHITECTURE.md`'s troubleshooting log for why) |
| `silver_clean.py` | Bandpass filter, normalize, window |
| `gold_label_split.py` | Label, group by `scenario_family_id`, split train/val/test |
| `validate.py` | Pipeline-level checks: schema, split leakage, duplicates |
| `model_registry.py` | Small metadata.json per trained model version (code sha, data version, eval metrics) |
| `replay_pipeline.py` | Idempotent: classifies gold-layer windows, upserts into `vibration_classified_events` |
| `tests/` | pytest suite for `validate.py`, runs without network access |

---

## Runs via CI, not locally

`.github/workflows/pipeline.yml` runs all four steps below on every push to
`main`, and on demand from the Actions tab. There's no need to run this on
your own machine — the commands are shown here for reference/debugging, not
as the normal way to operate this.

```bash
pip install -r requirements.txt
python src/02_ml_pipeline/bronze_ingest.py --dataset stead      # reads data/stead_sample/, no network needed
python src/02_ml_pipeline/silver_clean.py --dataset stead
python src/02_ml_pipeline/gold_label_split.py --dataset stead
python src/02_ml_pipeline/replay_pipeline.py --dataset stead    # needs DATABASE_URL — the one step that does need network
```

Verified working end to end against the real local sample: 50 STEAD traces
in, 100 labeled/split windows out, zero schema/leakage/duplicate issues.

## Tests

```bash
pytest src/02_ml_pipeline/tests/ -v
```

These run against synthetic fixtures, not the real local sample, so they
work without any data files present. `test_split_leakage.py` includes a
test that deliberately breaks a split and asserts the check catches it —
not just that the check exists.

## Naming note

`vibration_classified_events` (this module's output table, in terrawatchapp's
Supabase project) is unrelated to that project's other `seismic-*` model
(`seismic-insar`, satellite InSAR deformation) — see the header comment in
`data/schema/0049_vibration_classified_events.sql` for the full distinction.
