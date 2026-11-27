#!/usr/bin/env python3
"""Score exported windows with the rankers: one row per call with every gate score (E1 calls).

Input: an index CSV with columns set, system, case_id, path and optionally split (seconds from the
window start; empty = the window's midpoint, used for windows without a fault) and truth (injected
services separated by '|'). E1 used: set=historical (129 screened windows, midpoint), certified
(88 certified windows, midpoint), faulty / faulty_dsb_matched (fault windows, split 90 s, truth =
both injected services).

BARO and n-sigma run in fouroutcome (no RCAEval needed); other RCAEval methods (dummy,
granger_randomwalk, lingam_randomwalk) run through fouroutcome.rcaeval_adapter if RCAEval is
installed. Output columns match data/e1/calls.csv, from which reproduce/fig3_certified_gates.py
sets the leave-one-deployment-out thresholds and counts accepted certified windows.

usage: score_windows.py --index windows.csv --out calls.csv [--methods baro,nsigma,dummy,...]
"""
import argparse
import os
import sys
import zlib

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from fouroutcome.rankers import SCORER_METHODS, midpoint, score_window  # noqa: E402
from fouroutcome.window import load_window, service_of, sli_for  # noqa: E402


def call(row, method):
    split = midpoint(row.path) if pd.isna(row.split) or row.split == "" else float(row.split)
    truth = set(str(row.truth).split("|")) if isinstance(row.truth, str) and row.truth else None
    if method in SCORER_METHODS:
        return score_window(row.path, row.system, split, method, truth)
    from fouroutcome.rcaeval_adapter import call_ranker
    data = load_window(row.path)
    # RCAEval's random baseline draws from NumPy's global state; seed it per call for repeatability
    np.random.seed(zlib.crc32(f"{row.set}|{row.system}|{row.case_id}|{method}".encode()) & 0xFFFFFFFF)
    r = call_ranker(method, data, split, sli_for(row.system, data))
    top = service_of(r["ranks"][0]) if r["ranks"] else ""
    return {"system": row.system, "method": method, "split_time": split, "ok": r["ok"],
            "ranked": r["ok"] and bool(r["ranks"]), "api_ranked": r["api_ranked"], "fallback": r["fallback"],
            "top1_service": top, "hit": float(top in truth) if truth is not None else float("nan"),
            "error": r["error"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--index", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--methods", default="baro,nsigma")
    a = ap.parse_args()
    idx = pd.read_csv(a.index, dtype={"split": object, "truth": object})
    for c in ("split", "truth"):
        if c not in idx:
            idx[c] = ""
    rows = []
    for r in idx.itertuples():
        for m in a.methods.split(","):
            rows.append({"set": r.set, "case_id": r.case_id, **call(r, m.strip())})
    pd.DataFrame(rows).to_csv(a.out, index=False)
    print(f"{len(rows)} calls -> {a.out}")


if __name__ == "__main__":
    main()
