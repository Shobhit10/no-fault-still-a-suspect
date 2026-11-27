"""Oracle labels: the health certificate and the user-facing probe (labels no ranker sees).

Certificate of a quiet window (all must hold; missing evidence fails the window):
  E1 export      the exported window has the complete 5-s time grid;
  E2 raw         every raw series family the rankers read (container CPU and memory, Istio requests
                 and latency buckets) has raw samples over the whole window with no gap above twice
                 its scrape interval (cAdvisor 15 s -> 30 s, Istio 5 s -> 10 s)  ["raw coverage"];
  E3 stability   no container restarts or becomes unready, and the pod set does not change;
  E4 probe       an out-of-mesh probe has a request in every 10-s bin, only 2xx responses and a
                 window p95 of at most max(3 p, p + 0.25 s), p = calibration p95;
  E5 mesh SLO    every service that served during calibration still serves, with an Istio error
                 ratio <= 0.1% and a median p99 within 3x its calibration median p99;
  E6 quiet       no recorded injection within 300 s before or 600 s after the window.
E1-E6 are evaluated against Prometheus by ``experiments/live/certificate.py``; this module holds
the rule constants and everything that needs only the stored per-window records.

Labels of the live four-outcome tests (E3, E4):
  IE_natural   E1 or E2 failed (any class)                  -> Insufficient-Evidence
  NI           quiet slot and the certificate passed       -> No-Incident
  uncertified  quiet slot, certificate failed               (reported, not scored)
  not_fired    fault or surge that could not be fired       (reported, not scored)
  silent       fault or surge without user impact           (reported, not scored)
  LOC          fault with user impact                       -> Localized(faulty service)
  UNR          surge with user impact, no container restart -> Unresolved
  UNR_restart  surge with an application container restart  (excluded)
User impact: over [event + 30 s, event + 300 s], a non-2xx probe response or a probe p95 above
the E4 limit.
"""
import numpy as np
import pandas as pd

RULE = {"raw_gap_factor": 2.0, "probe_bin_s": 10, "probe_latency_factor": 3.0,
        "probe_latency_floor_add_s": 0.25, "mesh_error_ratio_max": 0.001, "mesh_p99_factor": 3.0}
FAMILY_INTERVAL = {"cpu": 15, "mem": 15, "req": 5, "lat": 5}
GUARD_BEFORE, GUARD_AFTER = 300, 600
IMPACT_SKIP = 30
SCORED_LABELS = ("NI", "LOC", "UNR", "IE_natural")


def probe_limit(calibration_p95):
    """E4 latency limit max(3 p, p + 0.25 s)."""
    p = calibration_p95
    return max(RULE["probe_latency_factor"] * p, p + RULE["probe_latency_floor_add_s"])


def parse_probe_log(lines):
    """Probe log lines '<unix_s> <endpoint_index> <http_code> <seconds>' -> DataFrame t, idx, code, latency."""
    rows = []
    for line in lines:
        parts = line.split()
        if len(parts) == 4 and parts[0].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], float(parts[3])))
    df = pd.DataFrame(rows, columns=["t", "idx", "code", "latency"]).drop_duplicates()
    return df.sort_values("t")


def probe_stats(df):
    ok = df["code"].astype(str).str.startswith("2")
    return {"requests": int(len(df)), "non2xx": int((~ok).sum()),
            "p95": float(np.percentile(df["latency"], 95)) if len(df) else float("nan")}


def impact(probe, calibration_p95, t0, t1):
    """User impact over [t0, t1] from probe lines (non-2xx or p95 above the E4 limit)."""
    pl = probe[(probe.t >= t0) & (probe.t <= t1)]
    st = probe_stats(pl)
    limit = probe_limit(calibration_p95)
    hit = bool(st["requests"] and (st["non2xx"] > 0 or st["p95"] > limit))
    return {"impact": hit, "impact_requests": st["requests"], "impact_non2xx": st["non2xx"],
            "impact_p95": st["p95"], "impact_limit": limit}


def probe_check(probe, start, end, calibration_p95):
    """E4 of the certificate on [start, end]: list of failure reasons (empty = pass)."""
    pl = probe[(probe.t >= start) & (probe.t <= end)]
    bins = np.arange(start, end, RULE["probe_bin_s"])
    covered = sum(1 for b in bins if ((pl.t >= b) & (pl.t < b + RULE["probe_bin_s"])).any())
    st = probe_stats(pl)
    limit = probe_limit(calibration_p95)
    reasons = []
    if covered < len(bins):
        reasons.append(f"E4:probe-bins{covered}/{len(bins)}")
    if st["non2xx"]:
        reasons.append(f"E4:non2xx{st['non2xx']}")
    if not np.isfinite(st["p95"]) or st["p95"] > limit:
        reasons.append("E4:probe-latency")
    return reasons


def label_record(r):
    """Label of one live window from its record (certificate reasons, class, fired, impact)."""
    e12 = not any(x.startswith(("E1:", "E2:")) for x in r["reasons"])
    if not e12:
        return "IE_natural"
    if r["cls"] == "NI":
        return "NI" if r["certified"] else "uncertified"
    if not r["fired"]:
        return "not_fired"
    if not r["impact"]:
        return "silent"
    if r["cls"] == "LOC":
        return "LOC"
    return "UNR" if not r.get("restarted_containers") else "UNR_restart"


def label_records(records):
    """labels.csv rows from per-window records (one dict per window)."""
    rows = []
    for r in records:
        rows.append({"case_id": r["case_id"], "system": r["system"], "slot": r["slot"],
                     "cls": r["cls"], "target": r["target"], "event": r["event"],
                     "label": label_record(r), "certified": r["certified"], "impact": r["impact"],
                     "impact_p95": r["impact_p95"], "impact_limit": r["impact_limit"],
                     "impact_non2xx": r["impact_non2xx"], "restarts": r.get("restarted_containers"),
                     "reasons": "|".join(r["reasons"])})
    return pd.DataFrame(rows).sort_values(["slot", "system"])
