"""Gates on a public benchmark (E2): equal-length segments of RCAEval cases and the RE2 -> RE3 test.

For every RCAEval case two segments are cut from the 1-s metrics around the injection time t0:
  pre_injection        [t0 - 540, t0 - 180), split at t0 - 360 (no injected fault)
  benchmark_labelled   [t0 - 180, t0 + 180), split at t0 (the benchmark's fault)
A segment must be exactly 360 contiguous one-second samples. BARO and n-sigma rank each segment
(missing values forward-filled then zero-filled, as RCAEval loads data); the gate scores come from
the same call, and detector D from the raw segment's fully observed latency and error columns.

``summarize`` sets every gate threshold at 1, 5 and 10% on the RE2 pre-injection segments of the
OTHER two systems (never RE3) and reports, per dataset, ranker, gate and rate, how many
pre-injection segments and labelled cases each gate accepts and how many accepted answers are
right (coverage, selective top-1 accuracy, yield).
"""
import numpy as np
import pandas as pd

from .calibration import threshold_at_acceptance
from .evidence import robust_support, service_score_evidence
from .measures import policy_metrics
from .rankers import column_scores

HALF = 180
METHODS = ("baro", "nsigma")
RATES = (0.01, 0.05, 0.10)
GATES = {"S": "support", "T": "top_service_score", "M": "service_margin", "D": "detector_score"}


def normalise_columns(source):
    """RCAEval metric columns as the rankers read them (p90 latency renamed, p50 dropped)."""
    source = source.loc[:, ~source.columns.str.endswith("_latency-50")]
    return source.rename(columns={c: c.replace("_latency-90", "_latency") for c in source if c.endswith("_latency-90")})


def select_segment(source, injection, segment, half=HALF):
    times = source["time"].to_numpy(dtype=float)
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        return None, "invalid_source_timestamps"
    start = injection + (-3 * half if segment == "pre_injection" else -half)
    frame = source[(source.time >= start) & (source.time < start + 2 * half)].copy()
    if len(frame) != 2 * half:
        return None, "incomplete_segment"
    if not np.array_equal(frame.time.to_numpy(), start + np.arange(2 * half)):
        return None, "noncontiguous_segment"
    return frame.reset_index(drop=True), ""


def detector_evidence(raw, half=HALF):
    columns = [c for c in raw if "latency" in c or "_error" in c]
    observed = [c for c in columns if np.isfinite(raw[c].to_numpy(dtype=float)).all()]
    scores = [(c, robust_support(raw[c], half)[0]) for c in observed]
    if not scores:
        return {"detector_valid": False, "detector_score": None, "detector_signal": "",
                "detector_columns": len(columns), "detector_observed": 0}
    column, score = max(scores, key=lambda item: item[1])
    return {"detector_valid": True, "detector_score": score, "detector_signal": column,
            "detector_columns": len(columns), "detector_observed": len(observed)}


def evaluate_case(source, injection, case):
    """Decision rows (2 segments x 2 rankers) of one case; ``case`` holds case, dataset, suite,
    system, root_cause_service, fault."""
    source = normalise_columns(source)
    rows = []
    for segment in ("pre_injection", "benchmark_labelled"):
        raw, reason = select_segment(source, injection, segment)
        for method in METHODS:
            row = {k: case[k] for k in ("case", "dataset", "suite", "system", "root_cause_service", "fault")}
            row.update(segment=segment, method=method, eligible=raw is not None, reason=reason,
                       rank_emitted=False, hit=0, top1="", support=None, support_valid=False,
                       score_valid=False, score_parity=False, top_service_score=None, service_margin=None,
                       all_candidates_observed=False, detector_valid=False, detector_score=None,
                       detector_signal="", detector_columns=0, detector_observed=0)
            if raw is not None:
                clean = raw.replace([np.inf, -np.inf], np.nan).ffill().fillna(0)
                split_time = float(raw.time.iloc[HALF])
                scores = column_scores(clean, split_time, method, case["dataset"].lower())
                ranks = [c for c, _ in scores]
                row["rank_emitted"] = bool(ranks)
                if ranks:
                    row["top1"] = ranks[0]
                    row["hit"] = int(ranks[0].rsplit("_", 1)[0] == case["root_cause_service"])
                    row["support"], row["reason"] = robust_support(raw[ranks[0]], HALF)
                    row["support_valid"] = bool(np.isfinite(row["support"]))
                ev = service_score_evidence(scores, raw, ranks)
                ev.pop("candidate_scores")
                row.update(ev)
                row.update(detector_evidence(raw))
            rows.append(row)
    return rows


def _validity(frame):
    return frame.score_valid.astype(bool) & frame.support_valid.astype(bool)


def summarize(decisions, rates=RATES):
    """One policy row per dataset, ranker, gate (V = validity only, S, T, M, D) and rate."""
    rows = []
    for (dataset, method), target in decisions.groupby(["dataset", "method"], sort=True):
        system = target.system.iloc[0]
        source = decisions[(decisions.suite == "RE2") & (decisions.system != system)
                           & (decisions.segment == "pre_injection") & (decisions.method == method)]
        pre = target[target.segment == "pre_injection"].reset_index(drop=True)
        lab = target[target.segment == "benchmark_labelled"].reset_index(drop=True)
        valid = _validity(lab)
        for gate in ("V", *GATES):
            field = GATES.get(gate)
            for rate in ((None,) if gate == "V" else rates):
                if gate == "V":
                    thr, acc, pre_acc = None, valid, _validity(pre)
                else:
                    sv = _validity(source)
                    if gate == "D":
                        sv &= source.detector_valid.astype(bool)
                    thr = threshold_at_acceptance(source.loc[sv, field].to_numpy(dtype=float), rate)
                    acc = valid & (lab[field] >= thr)
                    pre_acc = _validity(pre) & (pre[field] >= thr)
                    if gate == "D":
                        acc &= lab.detector_valid.astype(bool)
                        pre_acc &= pre.detector_valid.astype(bool)
                m = policy_metrics(lab.hit.to_numpy(), acc.to_numpy())
                rows.append(dict(dataset=dataset, suite=dataset[:3], method=method, gate=gate, rate=rate,
                                 threshold=thr, pre_cases=len(pre), pre_accepted=int(pre_acc.sum()),
                                 accepted_cases="|".join(lab.case[acc]), **m))
    return pd.DataFrame(rows)
