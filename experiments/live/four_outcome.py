#!/usr/bin/env python3
"""Live four-outcome test (E3: CPU hog, E4: network delay): schedule, lock, collect and label.

Three slot classes, the same class in every deployment at the same time, in a seeded random order
spaced SPACING seconds apart:
  NI   nothing is done                              -> No-Incident if the certificate passes
  LOC  one probe-path service gets the fault        -> Localized(v) if the probe sees user impact
  UNR  the load generator is scaled up (no fault)   -> Unresolved if the probe sees user impact
                                                       and no container restarts
Windows span 300 s on each side of the event; every ranker splits at the event (oracle policy) or
60 s before the estimated onset (data-only policy). Labels: fouroutcome/labels.py.

Presets (the paper's designs; locked before any window existed):
  e3  slots NI 12 / LOC 12 / UNR 10, seed 20261007, fault cpu (128 busy loops, 300 s)
  e4  slots NI 8 / LOC 12 / UNR 6,   seed 20261008, fault delay (150 +- 50 ms, 300 s)
Fault targets and surge factors come from the config (config.example.json).

  four_outcome.py --arm e3 --config config.json --out runs/e3 show-schedule --t-start T
  four_outcome.py --arm e3 --config config.json --out runs/e3 calibrate --start S --end E
  four_outcome.py --arm e3 --config config.json --out runs/e3 lock --t-start T
  bash run_schedule.sh runs/e3 config.json            # fires the slots (driver)
  four_outcome.py --arm e3 --config config.json --out runs/e3 collect   # repeatable
  four_outcome.py --arm e3 --config config.json --out runs/e3 label     # -> labels.csv
The thresholds used by the analysis must be frozen before the lock (fouroutcome.calibration on
windows of other deployments) and copied into --out; lock hashes them with the code.
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import certificate as cc  # noqa: E402
from export_window import load_config  # noqa: E402
from fouroutcome.labels import IMPACT_SKIP, impact, label_records  # noqa: E402

PRESETS = {
    "e3": {"slots": {"NI": 12, "LOC": 12, "UNR": 10}, "seed": 20261007,
           "fault": {"kind": "cpu_saturation", "cpu_loops": 128, "tool": "faults/cpu_hog.sh"}},
    "e4": {"slots": {"NI": 8, "LOC": 12, "UNR": 6}, "seed": 20261008,
           "fault": {"kind": "net_delay", "delay_ms": 150, "jitter_ms": 50, "tool": "faults/net_delay.sh"}},
}
SPACING = 1260
PRE, POST, FAULT_S = 300, 300, 300
DEFAULT_SYSTEMS = "boutique,deathstarbench,otel-demo,sock-shop"
THRESHOLD_FILES = ("thresholds.json", "thresholds_blind.json")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def schedule(t_start, slots, seed, systems, targets, arm):
    rng = random.Random(seed)
    classes = [c for c, n in slots.items() for _ in range(n)]
    rng.shuffle(classes)
    rows, loc_i = [], {s: 0 for s in systems}
    tag = {"e3": "r5", "e4": "r7"}.get(arm, arm)
    for k, cls in enumerate(classes, start=1):
        ev = t_start + (k - 1) * SPACING
        for s in systems:
            target = ""
            if cls == "LOC":
                target = targets[s][loc_i[s] % len(targets[s])]
                loc_i[s] += 1
            rows.append({"slot": k, "class": cls, "system": s, "case_id": f"{s}_{tag}_s{k:02d}_{cls}",
                         "target": target, "event": ev, "start_time": ev - 210, "end_time": ev + 120,
                         "export_start": ev - PRE, "export_end": ev + POST,
                         "fault_start": ev, "fault_end": ev + FAULT_S})
    return rows


def lock(a, cfg, preset, systems):
    path = os.path.join(a.out, "protocol.json")
    if os.path.exists(path):
        raise SystemExit("protocol.json exists; refusing to overwrite a lock")
    files = ["calibration.json"] + [f for f in THRESHOLD_FILES if os.path.exists(os.path.join(a.out, f))]
    if not os.path.exists(os.path.join(a.out, "calibration.json")):
        raise SystemExit("missing calibration.json (run calibrate)")
    if a.t_start <= time.time() + 120:
        raise SystemExit("t_start must be at least two minutes in the future")
    targets = {s: cfg["systems"][s]["fault_targets"] for s in systems}
    code = [os.path.join(HERE, p) for p in ("four_outcome.py", "certificate.py", "export_window.py",
                                            "run_schedule.sh", "probe/health_probe.yaml", "faults/fault_lib.sh",
                                            "faults/cpu_hog.sh", "faults/net_delay.sh", "faults/load_surge.sh")]
    protocol = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "arm": a.arm, "t_start": a.t_start,
        "slots": preset["slots"], "spacing_s": SPACING, "seed": preset["seed"],
        "geometry": {"export_pre": PRE, "export_post": POST, "fault_s": FAULT_S, "impact_skip_s": IMPACT_SKIP},
        "fault": {**preset["fault"], "targets": targets},
        "surge": {"factor": {s: cfg["systems"][s]["surge_factor"] for s in systems},
                  "loadgen": {s: cfg["systems"][s]["loadgen_deployment"] for s in systems},
                  "tool": "faults/load_surge.sh"},
        "impact_rule": "non2xx > 0 or probe p95 > max(3 p, p + 0.25 s) over [ev+30, ev+300]",
        "file_sha256": {f: sha256(os.path.join(a.out, f)) for f in files},
        "code_sha256": {os.path.relpath(p, HERE): sha256(p) for p in code},
        "schedule": schedule(a.t_start, preset["slots"], preset["seed"], systems, targets, a.arm),
    }
    with open(path, "w") as f:
        json.dump(protocol, f, indent=1)
    # injection log of this test, so that the certificate's E6 sees every event
    for s in systems:
        with open(os.path.join(a.out, f"ground_truth_{s}.csv"), "w") as f:
            for r in protocol["schedule"]:
                if r["system"] != s or r["class"] == "NI":
                    continue
                kind = {"LOC": "cpu" if a.arm == "e3" else "delay"}.get(r["class"], "surge")
                f.write(f"{r['case_id']},{s},{r['target'] or '__loadgen__'},{kind},__none2__,none,0,{r['fault_start']}\n")
                f.write(f"{r['case_id']},end_time,{r['fault_end']}\n")
    print("LOCKED", path)


def check_lock(a, protocol):
    for f, h in protocol["file_sha256"].items():
        if sha256(os.path.join(a.out, f)) != h:
            raise SystemExit(f"{f} changed after lock")
    for p, h in protocol["code_sha256"].items():
        if sha256(os.path.join(HERE, p)) != h:
            raise SystemExit(f"locked file changed: {p}")


def collect(a, cfg):
    protocol = json.load(open(os.path.join(a.out, "protocol.json")))
    check_lock(a, protocol)
    cal = json.load(open(os.path.join(a.out, "calibration.json")))
    cc.fetch_probe(cfg, a.out)
    rec_path = os.path.join(a.out, "records.jsonl")
    done = {json.loads(ln)["case_id"] for ln in open(rec_path) if ln.strip()} if os.path.exists(rec_path) else set()
    gt_glob = a.ground_truth_glob or os.path.join(a.out, "ground_truth_*.csv")
    inj = cc.injections(gt_glob)
    events = {}
    ev_path = os.path.join(a.out, "events.jsonl")
    if os.path.exists(ev_path):
        for ln in open(ev_path):
            if ln.strip():
                e = json.loads(ln)
                events[e["case_id"]] = e
    prom = cc.Prom(cfg["prometheus_url"])
    for w in protocol["schedule"]:
        if w["case_id"] in done or w["export_end"] + 120 >= time.time():
            continue
        rec = cc.evaluate_window(w, cfg, cal, inj, a.out, os.path.join(a.out, "windows", w["system"]), prom)
        rec.update(slot=w["slot"], cls=w["class"], target=w["target"], event=w["event"])
        probe = cc.probe_lines(a.out, w["system"])
        rec.update(impact(probe, cal["systems"][w["system"]]["probe"]["p95"],
                          w["fault_start"] + IMPACT_SKIP, w["fault_end"]))
        e = events.get(w["case_id"])
        rec["fired"] = bool(e and e.get("fired")) if w["class"] != "NI" else None
        rec["event_log"] = e
        with open(rec_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"{rec['case_id']:<34} cert={rec['certified']} impact={rec['impact']} {';'.join(rec['reasons'])[:110]}")


def label(a):
    protocol = json.load(open(os.path.join(a.out, "protocol.json")))
    check_lock(a, protocol)
    recs = [json.loads(ln) for ln in open(os.path.join(a.out, "records.jsonl")) if ln.strip()]
    df = label_records(recs)
    df.to_csv(os.path.join(a.out, "labels.csv"), index=False)
    print(pd.crosstab(df.system, df.label, margins=True).to_string())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", choices=sorted(PRESETS), required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--systems", default=DEFAULT_SYSTEMS)
    ap.add_argument("--ground-truth-glob", default="", help="all injection logs (default: this test's)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("calibrate")
    c.add_argument("--start", type=int, required=True)
    c.add_argument("--end", type=int, required=True)
    for name in ("lock", "show-schedule"):
        p = sub.add_parser(name)
        p.add_argument("--t-start", type=int, required=True)
    sub.add_parser("collect")
    sub.add_parser("label")
    a = ap.parse_args()
    cfg = load_config(a.config)
    preset = PRESETS[a.arm]
    systems = [s.strip() for s in a.systems.split(",") if s.strip()]
    cfg = {**cfg, "systems": {s: cfg["systems"][s] for s in systems}}
    os.makedirs(a.out, exist_ok=True)
    if a.cmd == "calibrate":
        cc.calibrate(cfg, a.out, a.start, a.end)
    elif a.cmd == "lock":
        lock(a, cfg, preset, systems)
    elif a.cmd == "show-schedule":
        targets = {s: cfg["systems"][s]["fault_targets"] for s in systems}
        for r in schedule(a.t_start, preset["slots"], preset["seed"], systems, targets, a.arm):
            print(r["slot"], r["event"], r["class"], r["system"], r["target"] or "-", r["case_id"])
    elif a.cmd == "collect":
        collect(a, cfg)
    else:
        label(a)


if __name__ == "__main__":
    main()
