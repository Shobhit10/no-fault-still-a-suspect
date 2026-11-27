#!/usr/bin/env python3
"""RQ1: does BARO's own change-point detector filter out healthy input?

Runs BARO's multivariate Bayesian online change-point detector (``baro.anomaly_detection.bocpd``,
the detector BARO uses before ranking) on windows without an injected fault and on RCAEval
pre-injection segments, and records whether it reports any change point. The paper found that it
fires on every screened E1 window and every valid RE2 pre-injection segment
(data/e1/baro_changepoint_screened.csv, data/e2/baro_changepoint_re2.csv).

Requires BARO: pip install "fse-baro @ git+https://github.com/phamquiluan/baro.git@e35f4ec1095e5cac891d52de9ad18a5b32a37ec8"
usage: baro_changepoint.py (--windows windows.csv | --rcaeval-dir DIR --dataset RE2-OB) --out fired.csv
"""
import argparse
import glob
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from fouroutcome.window import load_window  # noqa: E402
from winning_column_scale import rcaeval_pre_injection  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--windows")
    ap.add_argument("--rcaeval-dir")
    ap.add_argument("--dataset", default="custom")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from baro.anomaly_detection import bocpd
    frames = []
    if a.windows:
        frames = [(r.system, os.path.basename(r.path), load_window(r.path)) for r in pd.read_csv(a.windows).itertuples()]
    else:
        for f in sorted(glob.glob(os.path.join(a.rcaeval_dir, "*", "*", "inject_time.txt"))):
            d, _ = rcaeval_pre_injection(os.path.dirname(f))
            if d is not None:
                frames.append((a.dataset, os.path.relpath(os.path.dirname(f), a.rcaeval_dir), d))
    rows = []
    for system, key, d in frames:
        row = {"system": system, "case": key, "detector_ok": False, "detector_fired": False,
               "change_points": 0, "first_change_point": None, "error": ""}
        try:
            cps = list(bocpd(d.copy()) or [])
            row.update(detector_ok=True, detector_fired=bool(cps), change_points=len(cps),
                       first_change_point=float(cps[0]) if cps else None)
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    print(f"{int(df.detector_fired.sum())} of {len(df)} windows: BARO's detector reports a change point")


if __name__ == "__main__":
    main()
