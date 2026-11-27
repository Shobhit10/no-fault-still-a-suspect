#!/usr/bin/env python3
"""Screen candidate no-fault windows (E1 "screened windows").

A candidate window is kept ("screened") only if
  * it is not dead: at least one exported metric column changes (a window in which every metric
    is constant means the export failed, not that the system is healthy);
  * the restart audit exists and found no container restart we had not caused: the increase of
    kube_pod_container_status_restarts_total over the window is zero in the application namespace.
Screening does not prove health, so screened windows are NOT labelled No-Incident (that needs the
certificate, certificate.py). Candidates themselves are spaced so that no window lies within 300 s
before or 600 s after any recorded injection (sample them with that guard and >= 900 s apart).

usage:
  screen_windows.py --config config.json --system boutique --windows-dir data_boutique_clean \
                    --ground-truth gt_clean_boutique.csv --out screened_boutique.csv [--offline]
--offline skips the Prometheus restart audit (n_restarts left empty, so nothing is screened in).
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from export_window import PRE, POST, load_config, parse_ground_truth  # noqa: E402


def restarts(prom, namespace, start, end):
    q = f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}"}}[{int(end - start)}s]))'
    url = prom.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": end})
    with urllib.request.urlopen(url, timeout=120) as r:
        res = json.load(r)["data"]["result"]
    return round(float(res[0]["value"][1])) if res else 0


def is_dead(frame):
    numeric = frame.drop(columns="time", errors="ignore").apply(pd.to_numeric, errors="coerce")
    return bool(numeric.nunique(dropna=True).le(1).all())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--windows-dir", required=True)
    ap.add_argument("--ground-truth", required=True, help="case rows of the candidate windows (start/end)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    cfg = load_config(a.config)
    ns = cfg["systems"][a.system]["namespace"]
    rows = []
    for cid, rec in sorted(parse_ground_truth(a.ground_truth).items()):
        path = os.path.join(a.windows_dir, f"{cid}.csv")
        if not os.path.exists(path) or "end_time" not in rec:
            continue
        start, end = rec["start_time"] - PRE, rec["end_time"] + POST
        dead = is_dead(pd.read_csv(path))
        n = None if a.offline else restarts(cfg["prometheus_url"], ns, start, end)
        rows.append({"system": a.system, "case_id": cid, "start_epoch": start, "end_epoch": end, "dead_raw": dead,
                     "n_restarts": n, "restart_audit_present": n is not None,
                     "screened": (not dead) and n is not None and n == 0})
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    print(f"{a.system}: {int(df.screened.sum())} of {len(df)} candidate windows screened")


if __name__ == "__main__":
    main()
