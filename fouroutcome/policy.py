"""Gates, the four-outcome policies and how they are scored.

Outcomes: NI (No-Incident), IE (Insufficient-Evidence), UNR (Unresolved), LOC (Localized(v)).

Gates, each passing the named service only when its score reaches a frozen threshold tau:
  V  validity check: missing or non-finite evidence (or failed raw coverage) -> IE
  D  detector: largest support z over fully observed latency and error columns
  S  support: z of the named service's top column (Eq. 2)
  T  top score: best service score s1
  M  margin: (s1 - s2) / (|s1| + |s2| + 1e-9) (Table II)

Layered policy (V, then D, then a gate):  IE if V fails; NI if D < tau_D; LOC(top-1) if the gate
passes; UNR otherwise. With the oracles, V uses the certificate's raw-coverage verdict and every
ranker splits at the supplied event time. The data-only policy replaces V by the staleness check,
D by the scanned detector, and splits 60 s before the CUSUM onset estimate (``dataonly``).

A gate on its own (gate-only) answers LOC or DEFER; DEFER leaves open whether there is no incident
or an unresolved one. A ranker alone answers LOC on every call.

Scoring: an output is right if it equals the label, and LOC is right only with the injected
service. R = right answers, W = wrong localizations (LOC on a window whose label does not support
the named service), K = kept correct answers (right LOC).
"""
import json

import numpy as np
import pandas as pd

OUTCOMES = ("NI", "IE", "UNR", "LOC")
GATE_COL = {"S": ("support", "support_valid"), "T": ("top_service_score", "score_valid"),
            "M": ("service_margin", "score_valid")}
METHODS = ("nsigma", "baro")
SYSTEMS = ("boutique", "deathstarbench", "otel-demo", "sock-shop")
LABEL_TO_TRUTH = {"NI": "NI", "LOC": "LOC", "UNR": "UNR", "IE_natural": "IE"}


def truthy(v):
    return v is True or (isinstance(v, (bool, np.bool_)) and bool(v)) or str(v).strip().lower() == "true"


def load_thresholds(data_only_path, layered_path):
    """Thresholds of both policies in one dict.

    ``data_only_path``: stale, D_scan, gates_onset, gates_onset60 (``thresholds_blind.json``);
    ``layered_path``: D and gates_probe_matched of the oracle policy (``thresholds.json``)."""
    with open(data_only_path) as f:
        th = json.load(f)
    with open(layered_path) as f:
        lay = json.load(f)
    th["gates_supplied"] = lay["gates_probe_matched"]
    th["D_r5"] = lay["D"]
    return th


def decide(features, th, method="nsigma", gate="M", t="0.05", coverage_from=None, split="onset60",
           d_col="D_scan", d_th=None):
    """Four-outcome decision for every row of a per-window feature frame.

    coverage_from  column holding an oracle coverage verdict (True = coverage failed) used instead
                   of the data-only staleness check; None = data-only check.
    split          'event' (supplied event time), 'onset' or 'onset60' (data-only).
    d_col, d_th    detector column and its thresholds ({system: {target: tau}}); default D_scan
                   with th['D_scan'].
    gate           'S', 'T', 'M', or None for no gate (validity + detector + ranker)."""
    col, valid = GATE_COL[gate or "M"]
    out = []
    for r in features.to_dict("records"):
        s = r["system"]
        ie = truthy(r[coverage_from]) if coverage_from is not None else r["stale"] >= th["stale"][s][t]
        dth = (d_th or th["D_scan"])[s][t]
        d = float(r[d_col])
        score = r.get(f"{method}_{split}_{col}")
        score = float(score) if score is not None and score != "" else float("nan")
        ok = truthy(r.get(f"{method}_{split}_{valid}")) and truthy(r.get(f"{method}_{split}_ranked"))
        gth = -np.inf if gate is None else \
            th["gates_supplied" if split == "event" else f"gates_{split}"][method][gate][s][t]
        if ie or not np.isfinite(d):
            out.append("IE")
        elif d < dth:
            out.append("NI")
        elif not ok or not np.isfinite(score):
            out.append("IE")
        elif score >= gth:
            out.append("LOC")
        else:
            out.append("UNR")
    return out


def score_outcomes(features, outcome, method, split):
    """R / W / K and per-label right answers for one list of outcomes."""
    f = features.assign(_out=list(outcome))
    top = f[f"{method}_{split}_top1_service"].fillna("")
    right_loc = (f._out == "LOC") & (f.truth == "LOC") & (top == f.target)
    ok = (f._out == f.truth) & ((f.truth != "LOC") | right_loc)
    res = {"n": int(len(f)), "right": int(ok.sum()),
           "wrong_loc": int(((f._out == "LOC") & ~right_loc).sum()), "loc_kept": int(right_loc.sum())}
    for tr in OUTCOMES:
        h = f.truth == tr
        res[f"{tr}_n"], res[f"{tr}_right"] = int(h.sum()), int((ok & h).sum())
    return res


# policy variants of the paper (Fig. 5): name -> keyword arguments of `decide`
VARIANTS = {
    "oracle_cov_event": dict(coverage_from="e12_fail", split="event", d_col="D_event", d_th="layered"),
    "data_cov_event": dict(split="event", d_col="D_event", d_th="layered"),
    "oracle_cov_onset": dict(coverage_from="e12_fail", split="onset"),
    "oracle_cov_onset60": dict(coverage_from="e12_fail", split="onset60"),
    "blind_onset": dict(split="onset"),
    "blind": dict(split="onset60"),
}


def _kw(th, kw):
    kw = dict(kw)
    if kw.get("d_th") == "layered":
        kw["d_th"] = th["D_r5"]
    return kw


def evaluate(live, copies, th, t="0.05"):
    """Every table the paper derives from one live test (E3 or E4).

    ``live``: per-window features of the labelled live windows (columns case_id, system, label,
    truth, target, e12_fail, plus ``dataonly.window_features`` with the ``event`` split);
    ``copies``: the same features for the missing-data copies (plus pattern, parent_label,
    lost_service). Returns detection, onset error, ranker accuracy, staleness flags, policy R/W/K
    and the per-kind loss table (Fig. 6)."""
    from .measures import auroc
    res = {}
    scored = live[live.truth.isin(list(OUTCOMES))].copy()
    inc = scored[scored.truth.isin(["LOC", "UNR"])]
    ni = scored[scored.truth == "NI"]
    res["detection"] = {
        "auroc_scan": auroc(inc.D_scan, ni.D_scan), "auroc_event": auroc(inc.D_event, ni.D_event),
        "incident": int(len(inc)), "ni": int(len(ni)),
        "ni_over_scan_threshold": int(sum(r.D_scan >= th["D_scan"][r.system][t] for r in ni.itertuples())),
        "incident_under_scan_threshold": int(sum(r.D_scan < th["D_scan"][r.system][t] for r in inc.itertuples()))}
    err = (inc.onset - 300.0).abs()
    res["onset_error_s"] = {"median": float(err.median()), "p75": float(err.quantile(0.75)),
                            "within_30s": int((err <= 30).sum()), "within_60s": int((err <= 60).sum()),
                            "n": int(len(err))}
    loc = scored[scored.truth == "LOC"]
    res["ranker_top1_on_LOC"] = {f"{m}_{sp}": int((loc[f"{m}_{sp}_top1_service"] == loc.target).sum())
                                 for m in METHODS for sp in ("event", "onset", "onset60")}
    res["ranker_top1_on_LOC"]["n"] = int(len(loc))
    res["stale_live"] = {lab: {"n": int(len(g)),
                               "flagged": int(sum(r.stale >= th["stale"][r.system][t] for r in g.itertuples()))}
                         for lab, g in live.groupby("label")}
    pol = {}
    for name, kw in VARIANTS.items():
        kw2 = _kw(th, kw)
        for m, g in (("nsigma", "M"), ("baro", "S"), ("baro", "M")):
            pol[f"{name}|{m}_{g}"] = score_outcomes(scored, decide(scored, th, m, g, t, **kw2), m, kw["split"])
        for m in METHODS:
            ranked = scored[f"{m}_{kw['split']}_ranked"].map(truthy)
            pol[f"{name}|{m}_ranker"] = score_outcomes(scored, np.where(ranked, "LOC", "NONE"), m, kw["split"])
            pol[f"{name}|{m}_nogate"] = score_outcomes(scored, decide(scored, th, m, None, t, **kw2), m, kw["split"])
    res["policies_live"] = pol
    pat = {}
    for p, g in copies.groupby("pattern"):
        d = {"n": int(len(g)), "flagged": int(sum(r.stale >= th["stale"][r.system][t] for r in g.itertuples()))}
        lp = g[g.parent_label == "LOC"]
        for m in METHODS:
            d[f"{m}_ranked"] = int(g[f"{m}_event_ranked"].map(truthy).sum())
            d[f"{m}_names_lost"] = int((g[f"{m}_event_top1_service"] == g.lost_service).sum())
            d[f"{m}_names_culprit_LOCparent"] = int((lp[f"{m}_event_top1_service"] == lp.target).sum())
        d["LOC_parents"] = int(len(lp))
        out = decide(g, th, "nsigma", "M", t, split="onset60")
        d["blind_nsigma_M_IE"] = int(sum(o == "IE" for o in out))
        d["blind_nsigma_M_LOC"] = int(sum(o == "LOC" for o in out))
        pat[p] = d
    res["loss_patterns"] = pat
    return res


def gate_scores(frame, gate):
    """Gate score of every call, NaN where the score is invalid or the call did not rank."""
    col, valid = GATE_COL[gate]
    v = frame[valid].map(truthy) if frame[valid].dtype == object else frame[valid].astype(bool)
    r = frame["ranked"].map(truthy) if frame["ranked"].dtype == object else frame["ranked"].astype(bool)
    return pd.to_numeric(frame[col], errors="coerce").where(v & r)
