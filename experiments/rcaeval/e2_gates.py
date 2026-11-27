#!/usr/bin/env python3
"""E2: decline gates on the public RCAEval benchmark (RE2 -> RE3 code faults; RE1 confirmation).

  e2_gates.py prepare   --root DIR [--suites RE2,RE3]   download the pinned RCAEval files
  e2_gates.py run       --root DIR [--workers 4]        rank both segments of every case
  e2_gates.py summarize --root DIR                      gate policies -> DIR/policies.csv

Data: RCAEval public telemetry (L. Pham et al., WWW 2025 companion), Hugging Face dataset
``phamquiluan/RCAEval`` at revision afeacb11bcc94dadfd1c8f483ee4377b2b8b614e (MIT licence, see
THIRD_PARTY_NOTICES.md). It is downloaded here, not redistributed. ``prepare`` checks every
downloaded file against data/e2/rcaeval_files_*.sha256.json, the hashes of the files the paper
used. The per-call results of the paper's run are data/e2/calls_re2_re3.csv and calls_re1.csv;
``reproduce/fig4_public_gates.py`` summarizes them offline.

Segments, rankers, gates and thresholds: fouroutcome/benchmark.py. Thresholds come only from RE2
pre-injection segments of the other two systems; RE3 (code faults) and RE1 are never used to
calibrate.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
from fouroutcome.benchmark import evaluate_case, summarize  # noqa: E402

REVISION = "afeacb11bcc94dadfd1c8f483ee4377b2b8b614e"
BASE_URL = f"https://huggingface.co/datasets/phamquiluan/RCAEval/resolve/{REVISION}"
KNOWN = [os.path.join(REPO, "data", "e2", f) for f in ("rcaeval_files_re2_re3.sha256.json", "rcaeval_files_re1.sha256.json")]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(relative, data_dir):
    target = os.path.join(data_dir, relative)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.exists(target):
        for attempt in range(3):
            try:
                urllib.request.urlretrieve(f"{BASE_URL}/{relative}", target + ".download")
                os.replace(target + ".download", target)
                break
            except OSError as e:
                print(f"retry {relative} ({attempt + 1}): {e}", flush=True)
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
    return relative, sha256(target)


def prepare(root, suites):
    data_dir = os.path.join(root, "data")
    download("cases.parquet", data_dir)
    index = pd.read_parquet(os.path.join(data_dir, "cases.parquet"))
    cases = index[index.suite.isin(suites)].sort_values("case")
    cases.to_csv(os.path.join(root, "case_index.csv"), index=False)
    known = {}
    for p in KNOWN:
        if os.path.exists(p):
            known.update(json.load(open(p)))
    jobs = [f"{c}/{n}" for c in cases.case for n in ("metrics.parquet", "inject_time.txt")]
    got, differ = {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for fut in as_completed([pool.submit(download, j, data_dir) for j in jobs]):
            rel, digest = fut.result()
            got[rel] = digest
            if rel in known and known[rel] != digest:
                differ.append(rel)
    json.dump(got, open(os.path.join(root, "sources.json"), "w"), indent=1)
    print(f"{len(got)} files; {len(differ)} differ from the files the paper used", flush=True)
    if differ:
        print("WARNING: different input files, e.g.", differ[:3])


def _evaluate(job):
    root, case = job
    d = os.path.join(root, "data", case["case"])
    injection = float(open(os.path.join(d, "inject_time.txt")).read().strip())
    if injection != float(case["inject_time"]):
        raise ValueError(f"injection metadata mismatch: {case['case']}")
    source = pd.read_parquet(os.path.join(d, "metrics.parquet"))
    return evaluate_case(source, injection, case)


def run(root, workers):
    cases = pd.read_csv(os.path.join(root, "case_index.csv")).to_dict("records")
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, result in enumerate(pool.map(_evaluate, [(root, c) for c in cases], chunksize=4), 1):
            rows.extend(result)
            if i % 50 == 0 or i == len(cases):
                print(f"{i}/{len(cases)} cases", flush=True)
    out = pd.DataFrame(rows).sort_values(["dataset", "case", "segment", "method"])
    out.to_csv(os.path.join(root, "decisions.csv"), index=False)
    print("decisions:", len(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("prepare", "run", "summarize"))
    ap.add_argument("--root", required=True)
    ap.add_argument("--suites", default="RE2,RE3")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(a.root, exist_ok=True)
    if a.command == "prepare":
        prepare(a.root, [s.strip() for s in a.suites.split(",")])
    elif a.command == "run":
        run(a.root, a.workers)
    else:
        d = pd.read_csv(os.path.join(a.root, "decisions.csv"), float_precision="round_trip")
        for c in ("support_valid", "score_valid", "detector_valid"):
            d[c] = d[c].astype(str).str.lower().eq("true")
        pol = summarize(d)
        pol.drop(columns=["accepted_cases"]).to_csv(os.path.join(a.root, "policies.csv"), index=False)
        print(pol[pol.rate.isna() | (pol.rate == 0.05)].groupby(["suite", "method", "gate"])[
            ["localized", "correct", "cases"]].sum().to_string())


if __name__ == "__main__":
    main()
