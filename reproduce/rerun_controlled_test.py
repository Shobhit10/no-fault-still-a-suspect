"""Re-run the RQ1 controlled scale test from the 32 included windows and compare (about 6 min).

    python reproduce/rerun_controlled_test.py

Runs experiments/rq1/controlled_scale_test.py on data/windows/rq1_controlled/ and checks that all
2,304 trials equal data/rq1/controlled_scale_test.csv and that BARO gives the same rank in 380 of
384 trials. Not locked in advance (Sec. II-E of the paper).
"""
import os
import subprocess
import sys

import numpy as np
import pandas as pd

from _common import REPO, check, data, out, read_csv, write_checks


def main():
    print("RQ1 controlled test, re-run")
    trials = out("rerun", "controlled_scale_test.csv")
    subprocess.run([sys.executable, os.path.join(REPO, "experiments", "rq1", "controlled_scale_test.py"),
                    "--windows", data("rq1", "controlled_scale_test_windows.csv"), "--out", trials], check=True)
    a = pd.read_csv(trials)
    b = read_csv("rq1", "controlled_scale_test.csv")
    key = ["system", "window", "method", "target", "mag_class", "condition", "k_sigma"]
    m = a.merge(b, on=key, suffixes=("", "_stored"))
    diff = sum(int((~np.isclose(m[c].astype(float), m[c + "_stored"].astype(float), rtol=1e-9, atol=1e-12,
                                equal_nan=True)).sum()) for c in ("new_rank", "base_rank", "ref_iqr", "ref_sd"))
    check("Trials re-run equal to the stored trials", f"{len(m)} of {len(b)} matched, {diff} differing values",
          f"{len(b)} of {len(b)} matched, 0 differing values", "data/rq1", printed=False)
    p = a[a.method == "baro"].pivot_table(index=["window", "target", "k_sigma"], columns="condition", values="new_rank")
    check("BARO gives the zero-IQR column the same rank with or without a near-zero SD",
          f"{int(np.isclose(p['iqr_only'], p['both']).sum())} of {len(p)}", "380 of 384", "Sec. III-A")
    return write_checks("rerun_controlled_test")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
