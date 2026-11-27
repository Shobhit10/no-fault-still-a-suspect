#!/usr/bin/env python3
"""Health certificate for quiet windows (E1 certified windows; reused by four_outcome.py).

A window is certified healthy (No-Incident) only if E1-E6 all hold; missing evidence fails it
(rule constants in fouroutcome/labels.py):
  E1 export      the exporter wrote the complete 5-s grid the rankers read;
  E2 raw         raw Prometheus samples of every series family the rankers read (container CPU and
                 memory, Istio requests and latency buckets) cover the window with no gap above twice
                 the scrape interval (cAdvisor 15 s, Istio 5 s): "raw coverage";
  E3 stability   kube-state-metrics: no container restart, unchanged pod set, every pod Ready;
  E4 probe       the out-of-mesh probe (probe/health_probe.yaml) has a request in every 10-s bin,
                 only 2xx responses, and p95 <= max(3 p, p + 0.25 s), p = calibration p95;
  E5 mesh SLO    every service that served during calibration still serves, error ratio <= 0.1%,
                 median p99 <= 3 x its calibration median p99;
  E6 quiet       no recorded injection (ground-truth files) within 300 s before or 600 s after.
No check reads a ranker's output, but some read the rankers' telemetry: the certificate is
independent of their output, not of their input.

Subcommands (run against a cluster with Prometheus, kube-state-metrics, Istio and the probe):
  calibrate --start S --end E      baselines over a quiet calibration period -> calibration.json
  lock --t-start T [--per-system N] schedule N quiet windows per application, 15 min apart, and
                                   hash the schedule, rule, calibration and code -> protocol.json
  fetch-probe                      append new probe log lines to <out>/probe_logs/<system>.log
  collect                          export and evaluate every finished window -> records.jsonl
  certify                          apply the rule -> certified.csv
Common options: --config config.json --out DIR --ground-truth-glob 'gt/*.csv'
"""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
from export_window import container_name, export_window, load_config, parse_ground_truth  # noqa: E402
from fouroutcome.labels import (FAMILY_INTERVAL, GUARD_AFTER, GUARD_BEFORE, RULE,  # noqa: E402
                                parse_probe_log, probe_check, probe_stats)

CASE_LEN, PRE, POST, SPACING = 300, 90, 180, 900


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Prom:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def query(self, q, at):
        url = self.url + "/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": at})
        with urllib.request.urlopen(url, timeout=120) as r:
            d = json.load(r)
        if d.get("status") != "success":
            raise RuntimeError(f"query failed: {q}")
        return d["data"]["result"]

    def raw_samples(self, selector, start, end):
        """Raw (unaggregated, unfilled) samples of every series matching selector in [start, end]."""
        res = self.query(f"{selector}[{int(end - start)}s]", end)
        return [(r["metric"], [(float(t), float(v)) for t, v in r["values"]]) for r in res]


def selectors(sys_cfg, service):
    ns, rep = sys_cfg["namespace"], sys_cfg.get("istio_reporter", "source")
    pod = f'namespace="{ns}", pod=~"{service}.*", container="{container_name(sys_cfg, service)}"'
    dst = f'destination_service_name="{service}", destination_workload_namespace="{ns}", reporter="{rep}"'
    return {"cpu": f"container_cpu_usage_seconds_total{{{pod}}}",
            "mem": f"container_memory_usage_bytes{{{pod}}}",
            "req": f"istio_requests_total{{{dst}}}",
            "lat": f'istio_request_duration_milliseconds_bucket{{{dst}, le="+Inf"}}'}


def max_gap(timestamps, start, end):
    ts = sorted(t for t in timestamps if start <= t <= end)
    if not ts:
        return float("inf")
    return float(max([ts[0] - start, end - ts[-1]] + (list(np.diff(ts)) if len(ts) > 1 else [])))


# --------------------------------------------------------------------------------------- probe
def probe_lines(out, system):
    path = os.path.join(out, "probe_logs", f"{system}.log")
    if not os.path.exists(path):
        return pd.DataFrame(columns=["t", "idx", "code", "latency"])
    with open(path) as f:
        return parse_probe_log(f)


def fetch_probe(cfg, out):
    os.makedirs(os.path.join(out, "probe_logs"), exist_ok=True)
    for system in cfg["systems"]:
        cmd = ["kubectl", "logs", "-n", cfg.get("probe_namespace", "rca-probe"),
               f"deploy/{cfg.get('probe_deployment', 'rca-health-probe')}", "-c", system]
        if os.environ.get("KUBE_CONTEXT"):
            cmd[1:1] = ["--context", os.environ["KUBE_CONTEXT"]]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print(f"probe log fetch failed for {system}: {r.stderr[:200]}")
            continue
        path = os.path.join(out, "probe_logs", f"{system}.log")
        old = set(open(path).read().splitlines()) if os.path.exists(path) else set()
        new = [ln for ln in r.stdout.splitlines() if ln.strip() and ln not in old]
        with open(path, "a") as f:
            f.writelines(ln + "\n" for ln in new)
        print(f"{system}: +{len(new)} probe lines")


# --------------------------------------------------------------------------------------- calibration
def calibrate(cfg, out, start, end):
    prom = Prom(cfg["prometheus_url"])
    fetch_probe(cfg, out)
    cal = {"start": start, "end": end, "systems": {}}
    span = end - start
    for system, sc in cfg["systems"].items():
        entry = {"expected_families": {}, "serving": [], "p99_median": {}, "error_ratio": {}}
        ns, rep = sc["namespace"], sc.get("istio_reporter", "source")
        for service in sc["services"]:
            entry["expected_families"][service] = [
                fam for fam, sel in selectors(sc, service).items()
                if any(len(v) for _, v in prom.raw_samples(sel, start, end))]
            dst = f'destination_service_name="{service}", destination_workload_namespace="{ns}", reporter="{rep}"'
            req = prom.query(f"sum(increase(istio_requests_total{{{dst}}}[{span}s]))", end)
            reqv = float(req[0]["value"][1]) if req else 0.0
            if reqv > 0:
                entry["serving"].append(service)
                err = prom.query(
                    f'(sum(increase(istio_requests_total{{{dst}, response_code=~"5.."}}[{span}s])) or vector(0)) + '
                    f'(sum(increase(istio_requests_total{{{dst}, grpc_response_status=~"[1-9].*"}}[{span}s])) or vector(0))', end)
                entry["error_ratio"][service] = float(err[0]["value"][1]) / reqv if err else 0.0
                p99 = prom.query(f"quantile_over_time(0.5, histogram_quantile(0.99, sum(rate("
                                 f"istio_request_duration_milliseconds_bucket{{{dst}}}[1m])) by (le))[{span}s:5s])", end)
                entry["p99_median"][service] = float(p99[0]["value"][1]) if p99 else float("nan")
        pl = probe_lines(out, system)
        entry["probe"] = probe_stats(pl[(pl.t >= start) & (pl.t <= end)])
        cal["systems"][system] = entry
        print(system, "serving", len(entry["serving"]), "probe", entry["probe"])
    with open(os.path.join(out, "calibration.json"), "w") as f:
        json.dump(cal, f, indent=1)


# --------------------------------------------------------------------------------------- lock
def quiet_schedule(cfg, t_start, per_system):
    rows = []
    for system in cfg["systems"]:
        for i in range(1, per_system + 1):
            st = t_start + PRE + (i - 1) * SPACING
            rows.append({"system": system, "case_id": f"{system}_cert_w{i:02d}", "start_time": st,
                         "end_time": st + CASE_LEN, "export_start": st - PRE, "export_end": st + CASE_LEN + POST})
    return rows


def lock(cfg, out, t_start, per_system, code_files):
    path = os.path.join(out, "protocol.json")
    if os.path.exists(path):
        raise SystemExit("protocol.json exists; refusing to overwrite a lock")
    cal = os.path.join(out, "calibration.json")
    if not os.path.exists(cal):
        raise SystemExit("run calibrate first")
    if t_start <= time.time():
        raise SystemExit("t_start must be in the future")
    protocol = {"created_utc": datetime.now(timezone.utc).isoformat(), "t_start": t_start,
                "per_system": per_system, "rule": RULE, "family_interval_s": FAMILY_INTERVAL,
                "geometry": {"case_len": CASE_LEN, "export_pre": PRE, "export_post": POST, "spacing": SPACING,
                             "injection_guard_before": GUARD_BEFORE, "injection_guard_after": GUARD_AFTER},
                "certificate": "E1-E6 all hold; missing evidence fails",
                "calibration_sha256": sha256(cal),
                "code_sha256": {os.path.basename(p): sha256(p) for p in code_files},
                "schedule": quiet_schedule(cfg, t_start, per_system)}
    with open(path, "w") as f:
        json.dump(protocol, f, indent=1)
    print("LOCKED", path)


# --------------------------------------------------------------------------------------- collect
def injections(gt_glob):
    """(start, end, case) of every recorded injection; an unreadable file blocks every window."""
    out = []
    for gt in glob.glob(gt_glob) if gt_glob else []:
        try:
            for cid, rec in parse_ground_truth(gt).items():
                if rec.get("start_time"):
                    out.append((rec["start_time"], rec.get("end_time") or rec["start_time"] + CASE_LEN, cid))
        except Exception as e:
            out.append((0, 2 ** 40, f"unreadable:{os.path.basename(gt)}:{type(e).__name__}"))
    return out


def evaluate_window(w, cfg, cal, inj, out, export_dir, prom=None):
    """Certificate record of one scheduled window w (system, case_id, start_time, end_time,
    export_start, export_end); exports the window into export_dir if it is not there yet."""
    prom = prom or Prom(cfg["prometheus_url"])
    system, s, e = w["system"], w["export_start"], w["export_end"]
    sc, cs = cfg["systems"][system], cal["systems"][system]
    rec = {"case_id": w["case_id"], "system": system, "export_start": s, "export_end": e,
           "evaluated_utc": datetime.now(timezone.utc).isoformat(), "reasons": []}
    path = os.path.join(export_dir, w["case_id"] + ".csv")
    if not os.path.exists(path):
        export_window(w["case_id"], sc, w["start_time"], w["end_time"], export_dir, cfg["prometheus_url"])
    frame = None
    if os.path.exists(path):  # E1
        frame = pd.read_csv(path)
        times = pd.to_numeric(frame["time"], errors="coerce").to_numpy()
        expected = np.arange(0, (e - s) + 1, 5)
        rec["export_rows"] = int(len(frame))
        if not (len(times) == len(expected) and np.array_equal(times, expected)):
            rec["reasons"].append("E1:time-grid")
        rec["export_sha256"] = sha256(path)
    else:
        rec["reasons"].append("E1:no-export")
    gaps = {}  # E2
    for service in sc["services"]:
        for fam in cs["expected_families"].get(service, []):
            series = prom.raw_samples(selectors(sc, service)[fam], s, e)
            g = max_gap([t for _, vals in series for t, _ in vals], s, e)
            gaps[f"{service}:{fam}"] = g
            if g > RULE["raw_gap_factor"] * FAMILY_INTERVAL[fam]:
                rec["reasons"].append(f"E2:{service}:{fam}:gap{g:.0f}s")
    rec["raw_max_gap"] = gaps
    ns = sc["namespace"]  # E3
    restarts = prom.raw_samples(f'kube_pod_container_status_restarts_total{{namespace="{ns}"}}', s, e)
    n_restart = sum(1 for _, v in restarts if v and max(x for _, x in v) > min(x for _, x in v))
    info = prom.raw_samples(f'kube_pod_info{{namespace="{ns}"}}', s, e)
    pods_start = {m.get("pod") for m, v in info if v and v[0][0] <= s + 60}
    pods_end = {m.get("pod") for m, v in info if v and v[-1][0] >= e - 60}
    ready = prom.raw_samples(f'kube_pod_status_ready{{namespace="{ns}", condition="true"}}', s, e)
    not_ready = sum(1 for _, v in ready if any(x < 1 for _, x in v))
    rec.update(restarted_containers=n_restart, pods_start=len(pods_start), pods_end=len(pods_end),
               pods_not_ready=not_ready)
    if not restarts or not info or not ready:
        rec["reasons"].append("E3:missing-ksm")
    if n_restart:
        rec["reasons"].append(f"E3:restarts{n_restart}")
    if pods_start != pods_end:
        rec["reasons"].append("E3:pod-churn")
    if not_ready:
        rec["reasons"].append(f"E3:not-ready{not_ready}")
    pl = probe_lines(out, system)  # E4
    st = probe_stats(pl[(pl.t >= s) & (pl.t <= e)])
    rec.update(probe_requests=st["requests"], probe_non2xx=st["non2xx"], probe_p95=st["p95"])
    rec["reasons"] += probe_check(pl, s, e, cs["probe"]["p95"])
    if frame is not None:  # E5
        errs, p99r = {}, {}
        for service in cs["serving"]:
            cols = [f"{service}_istio_requests", f"{service}_istio_errors", f"{service}_latency_p99"]
            if any(c not in frame for c in cols):
                rec["reasons"].append(f"E5:missing-columns:{service}")
                continue
            rq, er, p99 = (pd.to_numeric(frame[c], errors="coerce") for c in cols)
            if not (rq > 0).any():
                rec["reasons"].append(f"E5:not-serving:{service}")
                continue
            ratio = float(er[rq > 0].sum() / rq[rq > 0].sum())
            errs[service] = ratio
            base = cs["p99_median"].get(service)
            p99r[service] = float(p99[rq > 0].median()) / base if base and np.isfinite(base) and base > 0 else float("nan")
            if not np.isfinite(ratio) or ratio > RULE["mesh_error_ratio_max"]:
                rec["reasons"].append(f"E5:errors:{service}={ratio:.4f}")
            if not np.isfinite(p99r[service]) or p99r[service] > RULE["mesh_p99_factor"]:
                rec["reasons"].append(f"E5:p99:{service}")
        rec["mesh_error_ratio"], rec["mesh_p99_ratio"] = errs, p99r
    hits = [c for a, b, c in inj if a - GUARD_AFTER <= e and b + GUARD_BEFORE >= s]  # E6
    rec["injection_overlaps"] = hits
    if hits:
        rec["reasons"].append("E6:injection")
    rec["certified"] = not rec["reasons"]
    return rec


def collect(cfg, out, gt_glob, export_pattern):
    protocol = json.load(open(os.path.join(out, "protocol.json")))
    cal = json.load(open(os.path.join(out, "calibration.json")))
    if sha256(os.path.join(out, "calibration.json")) != protocol["calibration_sha256"]:
        raise SystemExit("calibration changed after lock")
    fetch_probe(cfg, out)
    rec_path = os.path.join(out, "records.jsonl")
    done = {json.loads(ln)["case_id"] for ln in open(rec_path) if ln.strip()} if os.path.exists(rec_path) else set()
    inj = injections(gt_glob)
    prom = Prom(cfg["prometheus_url"])
    for w in protocol["schedule"]:
        if w["case_id"] in done or w["export_end"] + 120 >= time.time():
            continue
        rec = evaluate_window(w, cfg, cal, inj, out, export_pattern.format(system=w["system"]), prom)
        with open(rec_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"{rec['case_id']:<32} certified={rec['certified']} {';'.join(rec['reasons'])[:150]}")


def certify(out):
    recs = [json.loads(ln) for ln in open(os.path.join(out, "records.jsonl")) if ln.strip()]
    df = pd.DataFrame(recs)
    df["reasons"] = df["reasons"].apply("|".join)
    df[["case_id", "system", "export_start", "export_end", "certified", "reasons", "probe_requests",
        "probe_non2xx", "probe_p95", "restarted_containers", "pods_not_ready"]].to_csv(
        os.path.join(out, "certified.csv"), index=False)
    print("CERTIFIED", int(df["certified"].sum()), "of", len(df))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True, help="output directory (calibration, protocol, records)")
    ap.add_argument("--ground-truth-glob", default="", help="injection logs used by E6, e.g. 'gt/*.csv'")
    ap.add_argument("--export-dir", default="data_{system}_cert", help="export folder pattern")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    lk = sub.add_parser("lock")
    lk.add_argument("--t-start", type=int, required=True)
    lk.add_argument("--per-system", type=int, default=24)
    sub.add_parser("fetch-probe")
    sub.add_parser("collect")
    sub.add_parser("certify")
    a = ap.parse_args()
    cfg = load_config(a.config)
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == "calibrate":
        calibrate(cfg, a.out, a.start, a.end)
    elif a.cmd == "lock":
        code = [os.path.join(HERE, n) for n in ("certificate.py", "export_window.py", "probe/health_probe.yaml")]
        lock(cfg, a.out, a.t_start, a.per_system, code)
    elif a.cmd == "fetch-probe":
        fetch_probe(cfg, a.out)
    elif a.cmd == "collect":
        collect(cfg, a.out, a.ground_truth_glob, a.export_dir)
    else:
        certify(a.out)


if __name__ == "__main__":
    main()
