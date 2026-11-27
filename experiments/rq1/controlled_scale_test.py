#!/usr/bin/env python3
"""RQ1 controlled test: does a zero reference IQR make BARO's score depend on raw units?

For each window (no injected fault, split at the midpoint) and ranker, three candidate columns
that the ranker scores but does not rank first are picked: the lowest, middle and highest
reference-half standard deviation. One column at a time, only its reference half is rewritten:
  control    Gaussian with the column's own standard deviation sigma around its median;
  iqr_only   80% of the samples at the median and 20% spiked, so the IQR is exactly zero while
             the standard deviation stays sigma;
  both       flat except one sample perturbed by 1e-6 sigma: zero IQR and near-zero SD.
The post half is shifted to k reference sigmas above the median, k in {1, 3, 10, 30}, keeping its
own variation. The outcome is the column's rank in the full ranking. If BARO's rank is the same
under iqr_only and both, its score is the raw deviation (the scale was replaced by one), not a
standardised one. The paper reports 380 of 384 BARO trials with the same rank (32 windows from
four applications). This test was not locked in advance.

usage: controlled_scale_test.py --windows windows.csv --out trials.csv [--per-system 10]
windows.csv: columns system, path (exported quiet windows; relative paths are resolved against the
repository root). The paper used the first windows in name order that passed the September
screening's SLO check, in the four applications other than DeathStarBench (8 per application);
data/rq1/controlled_scale_test_windows.csv lists them and data/windows/rq1_controlled/ holds them.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from fouroutcome.rankers import rank  # noqa: E402
from fouroutcome.window import load_window  # noqa: E402

CONDITIONS = ("control", "iqr_only", "both")


def rewrite_reference(data, split, target, condition, k, rng):
    out = data.copy()
    t = out["time"].values
    ref, post = t < split, t >= split
    vals = out[target].values.astype(float)
    loc = float(np.median(vals[ref]))
    sigma = float(np.std(vals[ref]))
    if sigma <= 0:
        return None, None, None
    new = vals.copy()
    idx = np.flatnonzero(ref)
    if condition == "iqr_only":
        p = 0.2
        new[idx] = loc
        n_spike = max(1, int(round(p * len(idx))))
        new[idx[-n_spike:]] = loc + sigma / np.sqrt(p * (1.0 - p))
    elif condition == "both":
        new[ref] = loc
        new[idx[len(idx) // 2]] = loc + sigma * 1e-6
    else:
        new[ref] = loc + rng.normal(0.0, sigma, size=int(ref.sum()))
    post_vals = vals[post]
    new[post] = post_vals - float(np.median(post_vals)) + loc + k * sigma
    out[target] = new
    q1, q3 = np.percentile(new[ref], [25, 75])
    return out, float(q3 - q1), float(np.std(new[ref]))


def full_rank(method, data, split):
    try:
        return rank(data, split, method)
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--windows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-system", type=int, default=10)
    ap.add_argument("--ks", default="1,3,10,30")
    ap.add_argument("--methods", default="baro,nsigma")
    a = ap.parse_args()
    ks = [float(x) for x in a.ks.split(",")]
    methods = [m.strip() for m in a.methods.split(",")]
    w = pd.read_csv(a.windows)
    w["path"] = [p if os.path.isabs(p) or os.path.exists(p) else os.path.join(REPO, p) for p in w.path]
    cases = []
    for system, g in w.groupby("system"):
        for p in sorted(g.path, key=os.path.basename)[: a.per_system]:
            cases.append((system, p))
    rng = np.random.default_rng(0)
    rows = []
    for system, path in cases:
        data = load_window(path)
        split = float(data["time"].values[len(data) // 2])
        for m in methods:
            base = full_rank(m, data.copy(), split)
            if not base:
                continue
            cands = [c for c in base[1:] if float(np.std(data[c].values)) > 0]
            if not cands:
                continue

            def ref_sigma(c):
                v = data[c].values.astype(float)
                return float(np.std(v[: len(v) // 2]))
            by = sorted(cands, key=ref_sigma)
            for mag, target in {"low": by[0], "mid": by[len(by) // 2], "high": by[-1]}.items():
                base_rank = base.index(target) + 1
                for cond in CONDITIONS:
                    for k in ks:
                        inj, iqr, sd = rewrite_reference(data, split, target, cond, k, rng)
                        if inj is None:
                            continue
                        ranks = full_rank(m, inj, split)
                        new_rank = ranks.index(target) + 1 if target in ranks else np.nan
                        rows.append({"system": system, "window": os.path.basename(path).removesuffix(".gz"), "method": m,
                                     "target": target, "mag_class": mag,
                                     "magnitude": float(np.nanmax(np.abs(data[target].values))),
                                     "ref_sigma": ref_sigma(target), "condition": cond, "k_sigma": k,
                                     "ref_iqr": iqr, "ref_sd": sd, "n_ranked": len(ranks), "base_rank": base_rank,
                                     "new_rank": new_rank, "rank_gain": base_rank - new_rank,
                                     "reached_top1": int(new_rank == 1), "reached_top5": int(new_rank <= 5)})
    out = pd.DataFrame(rows)
    out.to_csv(a.out, index=False)
    b = out[out.method == "baro"].pivot_table(index=["window", "target", "k_sigma"], columns="condition",
                                              values="new_rank")
    print(f"{len(out)} trials; BARO same rank under iqr_only and both: "
          f"{int(np.isclose(b['iqr_only'], b['both']).sum())} of {len(b)}")


if __name__ == "__main__":
    main()
