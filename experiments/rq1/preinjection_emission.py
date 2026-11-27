#!/usr/bin/env python3
"""RQ1: do rankers ever decline? Call RCAEval rankers on windows without an injected fault.

Every call gets a window (or an RCAEval pre-injection segment: the 600 s ending 120 s before the
injection) split at its midpoint, as if an alert had fired there, and records whether a ranking
came back. The paper made 645 calls on the 129 screened E1 windows (BARO, n-sigma, random,
Granger- and LiNGAM-randomwalk) and 910 on RCAEval RE2 pre-injection segments (all five on RE2-OB
and RE2-SS, three on RE2-TT); every call returned a ranking (data/e1/screened_window_calls.csv,
data/e2/re2_preinjection_calls.csv).

Requires RCAEval 1.6.0 (requirements-rcaeval.txt) for the random and random-walk methods.
usage: preinjection_emission.py (--windows windows.csv | --rcaeval-dir DIR --dataset re2-ob)
                                --out calls.csv [--methods baro,nsigma,dummy,granger_randomwalk,lingam_randomwalk]
"""
import argparse
import glob
import os
import sys
import zlib

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from fouroutcome.rcaeval_adapter import call_ranker  # noqa: E402
from fouroutcome.window import load_window, service_of, sli_for  # noqa: E402
from winning_column_scale import rcaeval_pre_injection  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--windows")
    ap.add_argument("--rcaeval-dir")
    ap.add_argument("--dataset", default="custom")
    ap.add_argument("--out", required=True)
    ap.add_argument("--methods", default="baro,nsigma,dummy,granger_randomwalk,lingam_randomwalk")
    a = ap.parse_args()
    cases = []
    if a.windows:
        for r in pd.read_csv(a.windows).itertuples():
            d = load_window(r.path)
            cases.append((r.system, os.path.basename(r.path), d, float(d["time"].values[len(d) // 2]),
                          sli_for(r.system, d)))
    else:
        for f in sorted(glob.glob(os.path.join(a.rcaeval_dir, "*", "*", "inject_time.txt"))):
            case_dir = os.path.dirname(f)
            d, t = rcaeval_pre_injection(case_dir)
            if d is not None:
                label = os.path.basename(os.path.dirname(case_dir))
                lat = [c for c in d.columns if c.endswith("_latency")]
                own = label.rsplit("_", 1)[0] + "_latency"
                cases.append((a.dataset, f"{label}/{os.path.basename(case_dir)}", d, t,
                              own if own in d.columns else (lat[0] if lat else None)))
    rows = []
    for system, key, d, t, sli in cases:
        for m in a.methods.split(","):
            np.random.seed(zlib.crc32(f"{system}|{key}|{m}".encode()) & 0xFFFFFFFF)
            r = call_ranker(m.strip(), d, t, sli, a.dataset)
            top = r["ranks"][0] if r["ranks"] else ""
            rows.append({"system": system, "case": key, "method": m, "ok": r["ok"] or r["fallback"],
                         "fallback": r["fallback"], "top1": top, "top1_service": service_of(top) if top else "",
                         "top5": "|".join(map(str, r["ranks"][:5])), "err": r["error"]})
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    print(f"{len(df)} calls, {int((df.top1 != '').sum())} returned a ranking")


if __name__ == "__main__":
    main()
