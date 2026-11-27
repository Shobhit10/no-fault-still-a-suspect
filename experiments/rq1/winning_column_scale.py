#!/usr/bin/env python3
"""RQ1: why does a ranker keep naming the same service? Classify the winning column of each call.

For every window without an injected fault (split at the midpoint) and for BARO and n-sigma, the
top-ranked column is classified by the reference-half scale statistic its ranker divides by:
  scale   the scale is zero (IQR for BARO, standard deviation for n-sigma), so the scaler replaced
          it by one and the score is a raw deviation in the column's own units;
  drift   the reference half rises or falls monotonically (|Spearman rho with time| > 0.9);
  other   anything else.
Concentration is the share of a deployment's windows in which the ranker names its most frequent
service. The paper reports, for BARO on RE2-OB pre-injection segments, 94.7% of nominations on a
zero IQR and a concentration of 94.7% (data/rq1/winning_column_scale.csv, corpus re2ob).

Inputs (either):
  --windows windows.csv        exported windows (columns system, path)
  --rcaeval-dir DIR            RCAEval case folders <label>/<rep>/ holding simple_metrics.csv (or
                               metrics.parquet) and inject_time.txt; the 600 s ending 120 s before
                               the injection is used (RCAEval RE2 download, see experiments/rcaeval)
usage: winning_column_scale.py (--windows W | --rcaeval-dir D --corpus re2ob) --out calls.csv
"""
import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fouroutcome.rankers import rank  # noqa: E402
from fouroutcome.window import load_window, service_of  # noqa: E402

METHODS = ("baro", "nsigma")


def classify(d, col, split, method):
    if col not in d.columns:
        return "unknown", np.nan, np.nan
    ref = d[d["time"] < split][col].to_numpy(dtype=float)
    if len(ref) < 5:
        return "unknown", np.nan, np.nan
    q75, q25 = np.percentile(ref, [75, 25])
    scale = float(q75 - q25) if method == "baro" else float(ref.std(ddof=0))
    rr = pd.Series(ref).rank().to_numpy()
    ii = pd.Series(np.arange(len(ref))).rank().to_numpy()
    rho = 0.0 if rr.std() == 0 or ii.std() == 0 else float(np.corrcoef(rr, ii)[0, 1])
    if scale == 0.0:
        return "scale", rho, scale
    if abs(rho) > 0.9:
        return "drift", rho, scale
    return "other", rho, scale


def rcaeval_pre_injection(case_dir, win=600, guard=120):
    """The fault-free segment ending ``guard`` samples before the injection, split at its middle."""
    f = os.path.join(case_dir, "simple_metrics.csv")
    d = pd.read_csv(f) if os.path.exists(f) else pd.read_parquet(os.path.join(case_dir, "metrics.parquet"))
    d = d.loc[:, ~d.columns.str.endswith("_latency-50")]
    d = d.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
    t_inj = float(open(os.path.join(case_dir, "inject_time.txt")).readline().strip())
    pre = d[d["time"] < t_inj]
    if len(pre) < win + guard:
        return None, None
    seg = pre.iloc[-(win + guard):-guard].reset_index(drop=True)
    seg = seg.rename(columns={c: c.replace("_latency-90", "_latency") for c in seg.columns if c.endswith("_latency-90")})
    return seg, float(seg["time"].values[len(seg) // 2])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--windows")
    ap.add_argument("--rcaeval-dir")
    ap.add_argument("--corpus", default="own")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    cases = []
    if a.windows:
        for r in pd.read_csv(a.windows).itertuples():
            d = load_window(r.path)
            cases.append((r.system, os.path.basename(r.path), d, float(d["time"].values[len(d) // 2])))
    else:
        for f in sorted(glob.glob(os.path.join(a.rcaeval_dir, "*", "*", "inject_time.txt"))):
            case_dir = os.path.dirname(f)
            d, t = rcaeval_pre_injection(case_dir)
            if d is not None:
                key = f"{os.path.basename(os.path.dirname(case_dir))}/{os.path.basename(case_dir)}"
                cases.append((a.corpus, key, d, t))
    rows = []
    for system, key, d, t in cases:
        for m in METHODS:
            ranks = rank(d, t, m)
            top = ranks[0] if ranks else ""
            why, rho, scale = classify(d, top, t, m)
            rows.append({"corpus": a.corpus, "system": system, "case": key, "kind": "healthy", "method": m,
                         "base_top1": top, "base_svc": service_of(top) if top else "",
                         "base_fam": top.rsplit("_", 1)[-1] if top else "", "why": why, "rho": rho, "ref_scale": scale})
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    for m in METHODS:
        s = df[(df.method == m) & (df.base_top1 != "")]
        conc = np.mean([g.base_svc.value_counts().iloc[0] / len(g) for _, g in s.groupby("system")])
        print(f"{m}: {len(s)} calls, zero scale {100 * (s.why == 'scale').mean():.1f}%, concentration {100 * conc:.1f}%")


if __name__ == "__main__":
    main()
