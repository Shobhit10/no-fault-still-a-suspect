# E2 on the public RCAEval benchmark

RCAEval (L. Pham et al., "RCAEval: A benchmark for root cause analysis of microservice systems with
telemetry data", WWW 2025 companion) publishes 735 fault cases of Online Boutique, Sock Shop and
Train Ticket in three suites: RE1 (375, metrics only), RE2 (270, resource and network faults) and
RE3 (90, code faults). The data are MIT-licensed and hosted at
<https://huggingface.co/datasets/phamquiluan/RCAEval>; the paper used revision
`afeacb11bcc94dadfd1c8f483ee4377b2b8b614e` (accessed 2 Oct 2026). They are **not** redistributed
here: download them with the script below. Our per-call results on them are in `data/e2/`.

```bash
python experiments/rcaeval/e2_gates.py prepare   --root runs/rcaeval --suites RE1,RE2,RE3
python experiments/rcaeval/e2_gates.py run       --root runs/rcaeval --workers 4
python experiments/rcaeval/e2_gates.py summarize --root runs/rcaeval
```

`prepare` downloads `cases.parquet` and each case's `metrics.parquet` and `inject_time.txt` at the
pinned revision and compares every file with the SHA-256 values in
`data/e2/rcaeval_files_*.sha256.json`. `run` cuts the two equal 360-s segments of every case
(pre-injection and labelled), ranks them with BARO and n-sigma and records every gate score
(`fouroutcome/benchmark.py`); its output has the format of `data/e2/calls_*.csv`. `summarize` sets
the thresholds on RE2 pre-injection segments of the other two systems only (1, 5, 10%) and writes
every policy row; `reproduce/fig4_public_gates.py` does the same from the stored calls. Needs
`pyarrow` (in `requirements.txt`).

The RQ1 audits on RCAEval (910 calls on RE2 pre-injection segments, BARO's change-point detector,
the zero-IQR mechanism) are in `experiments/rq1/`. They read RE2 cases in RCAEval's own download
layout (`<dataset>/<service>_<fault>/<rep>/simple_metrics.csv` and `inject_time.txt`, as written by
RCAEval's download script) or the `metrics.parquet` files above.
