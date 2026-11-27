"""The two scorer rankers of the paper, BARO and n-sigma (Eq. 1), without the RCAEval dependency.

Both split the window at a supplied time, drop the time column and every column that is constant
within the reference part or within the post part, convert memory columns to MB, and score each
remaining column by the largest standardised value of its post part against its reference part:

    s(c) = max_{x in post} (x - loc(ref)) / scale(ref)

with median / interquartile range (scikit-learn ``RobustScaler``) for BARO and mean / standard
deviation (``StandardScaler``) for n-sigma. Both scalers replace a zero (or numerically constant)
scale by one, which is the zero-IQR mechanism of RQ1. Columns are ranked by score, ties keep the
input column order.

This is the same computation as ``RCAEval.e2e.baro`` and ``RCAEval.e2e.nsigma`` (RCAEval 1.6.0,
MIT licence, see THIRD_PARTY_NOTICES.md) with ``dataset="custom"`` and ``dk_select_useful=False``,
the settings used throughout the paper. The paper's runs called RCAEval itself and checked that
this re-computation returns the identical ranking on every call (``score_parity``).
"""
import math

import pandas as pd
from sklearn.preprocessing import RobustScaler, StandardScaler

from .evidence import robust_support, service_score_evidence
from .window import load_window, service_of

SCORER_METHODS = ("baro", "nsigma")


def drop_time(df):
    if "time" in df:
        return df.drop(columns=["time"])
    if "Time" in df:
        return df.drop(columns=["Time"])
    return df


def drop_constant(df):
    return df.loc[:, (df != df.iloc[0]).any()]


def convert_mem_mb(df):
    def update_mem(x):
        if not x.name.endswith("_mem"):
            return x
        return x / 1e6
    return df.apply(update_mem)


def preprocess(data, dataset="custom"):
    """RCAEval's ``preprocess`` for any named dataset with ``dk_select_useful=False``."""
    if dataset is None:
        return data
    return convert_mem_mb(drop_constant(drop_time(data)))


def column_scores(data, split_time, method, dataset="custom"):
    """[(column, score)] of every scored column, highest first (stable for ties)."""
    if method not in SCORER_METHODS:
        raise ValueError(f"unknown scorer {method!r}; use one of {SCORER_METHODS}")
    reference = preprocess(data[data["time"] < split_time].copy(), dataset)
    post = preprocess(data[data["time"] >= split_time].copy(), dataset)
    candidates = [c for c in reference.columns if c in post.columns]
    scaler_type = RobustScaler if method == "baro" else StandardScaler
    scores = []
    for column in candidates:
        scaler = scaler_type().fit(reference[[column]].to_numpy())
        scores.append((column, float(max(scaler.transform(post[[column]].to_numpy())[:, 0]))))
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores


def rank(data, split_time, method, dataset="custom"):
    """Ranked list of columns, as RCAEval's ``baro`` / ``nsigma`` return it."""
    return [c for c, _ in column_scores(data, split_time, method, dataset)]


def score_window(window, system, split_time, method, truth=None, dataset="custom"):
    """One ranker call plus every gate score the paper defines, from the same call.

    ``window`` is an exported CSV path or an exported frame. Returns the fields of the paper's
    per-call records: ``ranked``, ``top1_service``, ``hit`` (if ``truth`` is a set of services),
    ``support`` / ``support_valid`` (Eq. 2 on the named column), ``top_service_score`` (s1) and
    ``service_margin`` (Table II) with ``score_valid``.
    """
    data = load_window(window)
    row = {"system": system, "method": method, "split_time": split_time, "ok": False,
           "ranked": False, "api_ranked": False, "fallback": False, "top1_service": "",
           "hit": float("nan"), "support": float("nan"), "support_valid": False,
           "top_service_score": float("nan"), "service_margin": float("nan"),
           "score_valid": False, "score_reason": "", "error": ""}
    try:
        scores = column_scores(data, split_time, method, dataset)
    except Exception as e:  # report, never hide, a failed call
        row["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        return row
    ranks = [c for c, _ in scores]
    row.update(ok=True, ranked=bool(ranks), api_ranked=bool(ranks))
    if not ranks:
        return row
    top = ranks[0]
    row["top1_service"] = service_of(top)
    if truth is not None:
        row["hit"] = float(row["top1_service"] in truth)
    split_index = int((data["time"] < split_time).sum())
    if top in data:
        support, reason = robust_support(data[top].to_numpy(dtype=float), split_index)
        row["support"], row["support_valid"] = support, math.isfinite(support)
        if reason:
            row["score_reason"] = reason
    ev = service_score_evidence(scores, data, ranks)
    row.update(top_service_score=ev["top_service_score"], service_margin=ev["service_margin"],
               score_valid=ev["score_valid"])
    if ev["score_reason"]:
        row["score_reason"] = (row["score_reason"] + "|" + ev["score_reason"]).strip("|")
    return row


def midpoint(window):
    """Split time used for windows without a fault: the middle sample of the window."""
    t = (window if isinstance(window, pd.DataFrame) else pd.read_csv(window, usecols=["time"]))["time"]
    t = t.to_numpy()
    return float(t[len(t) // 2])


__all__ = ["SCORER_METHODS", "preprocess", "column_scores", "rank", "score_window", "midpoint"]
