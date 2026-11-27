"""Evidence scores read by the gates: support z (Eq. 2), top score s1, margin m (Table II), detector D."""
import json

import numpy as np
import pandas as pd

EPSILON = 1e-9
SUPPORT_ALPHA = 0.01


def robust_support(values, split_index, alpha=SUPPORT_ALPHA):
    """Eq. 2: |med(post) - med(ref)| / (max(MAD(ref), alpha |med(ref)|) + eps).

    Returns (z, reason). z is NaN, with a reason, when either part is too short or holds a
    non-finite value."""
    numeric = np.asarray(values, dtype=float)
    reference = numeric[:split_index]
    post = numeric[split_index:]
    if len(reference) < 5 or len(post) < 3:
        return float("nan"), "insufficient_rows"
    if not np.isfinite(reference).all() or not np.isfinite(post).all():
        return float("nan"), "nonfinite_nominee_signal"
    median = float(np.median(reference))
    mad = float(np.median(np.abs(reference - median)))
    denominator = max(mad, alpha * abs(median)) + EPSILON
    return float(abs(float(np.median(post)) - median) / denominator), ""


def service_score_evidence(scores, raw, ranks):
    """Top service score s1 and normalised margin m = (s1 - s2) / (|s1| + |s2| + 1e-9) of a scorer
    ranking. ``scores`` is the [(column, score)] list behind ``ranks``; a service's score is its
    best column score. ``raw`` is the frame the ranker read (validity of the named column)."""
    candidates = [c for c, _ in scores]
    parity = candidates == list(ranks)
    result = {"score_parity": parity, "score_valid": False,
              "top_service_score": float("nan"), "service_margin": float("nan"),
              "score_reason": "", "all_candidates_observed": False,
              "candidate_scores": json.dumps(scores)}
    if not parity:
        result["score_reason"] = "ranking_mismatch"
        return result
    if not scores or not np.isfinite([s for _, s in scores]).all():
        result["score_reason"] = "missing_or_nonfinite_scores"
        return result
    result["all_candidates_observed"] = bool(
        all(c in raw for c in candidates)
        and np.isfinite(raw[candidates].apply(pd.to_numeric, errors="coerce").to_numpy()).all())
    if ranks[0] not in raw or not np.isfinite(pd.to_numeric(raw[ranks[0]], errors="coerce")).all():
        result["score_reason"] = "nonfinite_nominee_signal"
        return result
    services = {}
    for column, score in scores:
        services.setdefault(column.rsplit("_", 1)[0], score)
    if len(services) < 2:
        result["score_reason"] = "fewer_than_two_services"
        return result
    first, second = list(services.values())[:2]
    result.update(score_valid=True, top_service_score=first,
                  service_margin=(first - second) / (abs(first) + abs(second) + EPSILON))
    return result


def detector_columns(data):
    """Fully observed latency and error columns (the user-facing symptom columns of detector D)."""
    cols = [c for c in data if c != "time" and ("latency" in c or "_error" in c)]
    return [c for c in cols if np.isfinite(data[c].to_numpy(dtype=float)).all()]


def detector_at(data, split_time, cols=None):
    """Detector D at one split: the largest support z (Eq. 2) over ``detector_columns``.

    Returns (D, column). D asks whether a user-facing symptom changed at the split, not which
    service caused it."""
    split_index = int((data["time"] < split_time).sum())
    best, sig = float("nan"), ""
    for c in (cols if cols is not None else detector_columns(data)):
        s, _ = robust_support(data[c].to_numpy(dtype=float), split_index)
        if np.isfinite(s) and (not np.isfinite(best) or s > best):
            best, sig = float(s), c
    return best, sig
