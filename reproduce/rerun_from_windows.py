"""Recompute the E3 and E4 per-window features from the exported windows and compare.

    python reproduce/rerun_from_windows.py [--arm e3|e4|both] [--workers N] [--executor process|thread] [--limit N]

For every labelled live window in ``data/windows/<arm>/`` and for every missing-data copy (made
again here with ``fouroutcome.copies``), this runs the data-only rules and both rankers at the
event split, the estimated onset and 60 s before it (``fouroutcome.dataonly.window_features``),
and checks that every value equals the stored ``data/<arm>/live_features.csv`` and
``copy_features.csv`` (floats within a relative 1e-12). It then re-evaluates Figs. 5 and 6 from
the recomputed features. Under a second per window and core (E3: 136 windows and 389 copies, E4:
104 and 327; about 5 min for both tests with 6 workers); ``--limit N`` computes features only for
the first N live windows and their copies.
Copies are written to outputs/rerun/<arm>/copies/ (about 0.2 GB for both tests).
"""
import argparse
import json
import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")  # one BLAS thread per worker process

import shutil  # noqa: E402
import sys  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import check, data, out, read_csv, read_json, write_checks  # noqa: E402
from fouroutcome.copies import choose_lost_services, make_copies  # noqa: E402
from fouroutcome.dataonly import window_features  # noqa: E402
from fouroutcome.policy import LABEL_TO_TRUTH, evaluate, load_thresholds  # noqa: E402

METHODS = ("nsigma", "baro")
SPLITS = (("event", 300.0),)
SEEDS = {"e3": 20261007, "e4": 20261008}
COPY_SEED = 20261008


def window_path(arm, system, case_id):
    return data("windows", arm, system, f"{case_id}.csv.gz")


def _features(job):
    path, system = job
    return window_features(path, system, METHODS, SPLITS)


def lost_targets(arm, labels):
    """The deployment's fault targets in the order each test used for the seeded quiet-window choice."""
    if arm == "e3":
        return read_json("e3", "protocol.json")["fault"]["targets"]
    return {s: sorted(set(labels[(labels.system == s) & (labels.cls == "LOC")].target.dropna()) - {""})
            for s in labels.system.unique()}


def _equal(x, y):
    if isinstance(x, (bool, np.bool_)) or isinstance(y, (bool, np.bool_)):
        return str(x).lower() == str(y).lower()
    try:
        fx, fy = float(x), float(y)
        return bool((np.isnan(fx) and np.isnan(fy)) or np.isclose(fx, fy, rtol=1e-12, atol=0))
    except (TypeError, ValueError):
        return str(x if x == x else "") == str(y if y == y else "")


def compare(mine, stored, key, name):
    stored = stored.set_index(key)
    mine = mine.set_index(key)
    mine = mine.loc[stored.index.intersection(mine.index)]
    cols = [c for c in mine.columns if c in stored.columns]
    bad = sum(not _equal(x, y) for c in cols for x, y in zip(mine[c], stored.loc[mine.index, c]))
    check(f"{name}: recomputed features equal the stored ones ({len(mine)} windows x {len(cols)} columns)",
          bad, 0, "data/e3, data/e4", printed=False)
    return bad


def _map(ex, items, label):
    futures = {ex.submit(_features, it): i for i, it in enumerate(items)}
    out = [None] * len(items)
    for done, fut in enumerate(as_completed(futures), 1):
        out[futures[fut]] = fut.result()
        if done % 50 == 0 or done == len(items):
            print(f"  {label}: {done}/{len(items)}", flush=True)
    return out


def run_arm(arm, workers, limit, executor=ProcessPoolExecutor):
    labels = read_csv(arm, "labels.csv").sort_values(["slot", "system"])
    labels["path"] = [window_path(arm, r.system, r.case_id) for r in labels.itertuples()]
    labels = labels[[os.path.exists(p) for p in labels.path]].copy()
    labels["truth"] = labels.label.map(LABEL_TO_TRUTH)
    labels["target"] = labels.target.fillna("").astype(str)
    labels["e12_fail"] = labels.label.eq("IE_natural")
    labels["lost_service"] = choose_lost_services(labels, lost_targets(arm, labels), SEEDS[arm])
    stored_live = read_csv(arm, "live_features.csv")
    stored_copies = read_csv(arm, "copy_features.csv")
    # missing-data copies, made again with the seeded generator (always for every parent, so that
    # the seeded draws of the "other" kind follow the same sequence as in the paper's runs)
    parents = labels[labels.label.isin(["NI", "LOC"])][["case_id", "system", "label", "target", "lost_service", "path"]]
    copy_dir = out("rerun", arm, "copies")
    shutil.rmtree(copy_dir, ignore_errors=True)
    copies = make_copies(parents, copy_dir, seed=COPY_SEED)
    sc = stored_copies.set_index("case_id").loc[copies.case_id]
    check(f"{arm.upper()} copies: silenced service equals the stored copy index",
          int((copies.lost_service.to_numpy() != sc.lost_service.to_numpy()).sum()), 0, f"data/{arm}", printed=False)
    if limit:
        labels = labels.head(limit)
        copies = copies[copies.parent.isin(labels.case_id)]
    with executor(workers) as ex:
        lf = _map(ex, [(r.path, r.system) for r in labels.itertuples()], f"{arm} live windows")
        cf = _map(ex, [(r.path, r.system) for r in copies.itertuples()], f"{arm} copies")
    live = labels[["case_id", "system", "slot", "label", "truth", "target", "e12_fail", "lost_service"]] \
        .reset_index(drop=True).join(pd.DataFrame(lf))
    cop = copies.drop(columns=["path"]).reset_index(drop=True).join(pd.DataFrame(cf))
    cop["truth"] = "IE"
    live.to_csv(out("rerun", arm, "live_features.csv"), index=False, lineterminator="\n")
    cop.to_csv(out("rerun", arm, "copy_features.csv"), index=False, lineterminator="\n")
    compare(live.drop(columns=["slot", "lost_service"]), stored_live, "case_id", f"{arm.upper()} live windows")
    compare(cop, stored_copies, "case_id", f"{arm.upper()} copies")
    if not limit:
        th = load_thresholds(data("data_only", "thresholds_blind.json"), data(arm, "thresholds.json"))
        stored = read_json(*(("e3", "summary_locked.json") if arm == "e3" else ("e4", "report_locked.json")))
        res = json.loads(json.dumps(evaluate(pd.read_csv(out("rerun", arm, "live_features.csv")),
                                             pd.read_csv(out("rerun", arm, "copy_features.csv")), th), default=float))
        check(f"{arm.upper()} Fig. 5/6 tables from recomputed features equal the stored ones",
              all(res[k] == stored[k] for k in ("policies_live", "loss_patterns", "ranker_top1_on_LOC",
                                                 "stale_live", "detection", "onset_error_s")), True,
              f"data/{arm} (Figs. 5, 6)", printed=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=["e3", "e4", "both"], default="both")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--executor", choices=["process", "thread"], default="process",
                    help="thread workers avoid inter-process semaphore handles on Windows")
    ap.add_argument("--limit", type=int, default=0, help="only the first N live windows (and their copies)")
    a = ap.parse_args()
    for arm in (("e3", "e4") if a.arm == "both" else (a.arm,)):
        print(f"\n{arm.upper()}: recomputing features from the exported windows")
        executor = ThreadPoolExecutor if a.executor == "thread" else ProcessPoolExecutor
        run_arm(arm, a.workers, a.limit, executor)
    return write_checks("rerun_from_windows")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
