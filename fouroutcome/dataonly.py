"""The data-only (oracle-free) rules of the paper: staleness check and scanned onset.

The layered policy needs two things an operator does not have: the certificate's raw-coverage
verdict and the event time at which every ranker splits the window. The data-only policy replaces
both with rules that read only the exported window, i.e. the frame a ranker receives.

stale     Lost telemetry reaches the ranker as a run of identical values, because the exporter fills
          a missing sample with the last one. ``stale_score`` is the longest run, in seconds, over
          which a CPU or request-rate column holds one identical non-zero value. Columns with fewer
          than three distinct values are skipped (the ranker's preprocessing drops most of them).
          Memory, error and latency columns are not used: they legitimately hold one value for
          minutes (no allocation, no errors, histogram steps at low traffic).
scan      Detector D evaluated at every candidate split from 120 s after the window start to 120 s
          before its end, every 15 s; D_scan is the largest value. The onset estimate is the CUSUM
          change point argmax_k sqrt(k (n-k) / n) |mean(x[:k]) - mean(x[k:])| of the column that
          gave D_scan, over the same range on the 5-s grid.
onset60   The exporter computes rates and latency quantiles over 60-s windows, so a step at t0 is
          spread over [t0, t0 + 60] and the estimate lands inside that ramp. Rankers therefore split
          one look-back (60 s) before the estimated onset.

Thresholds for stale and D_scan are set like every other threshold (``calibration``), on the
certified healthy windows of the other deployments.
"""
import numpy as np
import pandas as pd

from .evidence import detector_at, detector_columns
from .rankers import SCORER_METHODS, score_window
from .window import load_window

EDGE, GRID = 120.0, 15.0
LOOKBACK = 60.0
STALE_SUFFIXES = ("_cpu", "_workload")
FEATURE_KEYS = ("ranked", "top1_service", "support", "support_valid", "top_service_score",
                "service_margin", "score_valid")


def stale_score(data):
    """(seconds, column) of the longest identical non-zero run in a CPU or request-rate column."""
    t = data["time"].to_numpy(dtype=float)
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 5.0
    best, where = 0.0, ""
    for c in data.columns:
        if not c.endswith(STALE_SUFFIXES):
            continue
        x = data[c].to_numpy(dtype=float)
        if not np.isfinite(x).all() or len(np.unique(x)) < 3:
            continue
        start = np.flatnonzero(np.r_[True, x[1:] != x[:-1]])
        length = np.diff(np.r_[start, len(x)]) * dt
        nonzero = x[start] != 0
        if nonzero.any() and length[nonzero].max() > best:
            best, where = float(length[nonzero].max()), c
    return best, where


def scan(data, edge=EDGE, grid=GRID):
    """Scanned detector and CUSUM onset: {D_scan, scan_signal, scan_split, onset}."""
    t = data["time"].to_numpy(dtype=float)
    lo, hi = t.min() + edge, t.max() - edge
    cols = detector_columns(data)
    best, col, at = float("nan"), "", float("nan")
    for g in np.arange(lo, hi + 1e-9, grid):
        v, c = detector_at(data, g, cols)
        if np.isfinite(v) and (not np.isfinite(best) or v > best):
            best, col, at = v, c, float(g)
    if not col:
        return {"D_scan": float("nan"), "scan_signal": "", "scan_split": float("nan"),
                "onset": float("nan")}
    x = data[col].to_numpy(dtype=float)
    n = len(x)
    ks = [k for k in range(1, n) if lo <= t[k] <= hi]
    csum = np.cumsum(x)
    stat = [np.sqrt(k * (n - k) / n) * abs(csum[k - 1] / k - (csum[-1] - csum[k - 1]) / (n - k))
            for k in ks]
    onset = float(t[ks[int(np.argmax(stat))]]) if ks else float("nan")
    return {"D_scan": best, "scan_signal": col, "scan_split": at, "onset": onset}


def window_features(window, system, methods=SCORER_METHODS, splits=()):
    """Every per-window feature the policies read.

    stale / stale_col, D_scan / scan_signal / scan_split / onset, and for each split in
    ``onset``, ``onset60`` (onset - 60 s) and any supplied ``(name, time)`` pair (the paper uses
    ``("event", 300.0)``): D_<split> and, per method, <method>_<split>_<key> for the keys in
    ``FEATURE_KEYS``. ``window`` is an exported CSV path or frame."""
    raw = window if isinstance(window, pd.DataFrame) else pd.read_csv(window)
    data = load_window(raw)
    st, st_col = stale_score(data)
    sc = scan(data)
    row = {"stale": st, "stale_col": st_col, **sc}
    for split_name, split in [("onset", sc["onset"]), ("onset60", sc["onset"] - LOOKBACK)] + list(splits):
        row[f"D_{split_name}"] = detector_at(data, split)[0] if np.isfinite(split) else float("nan")
        for m in methods:
            if not np.isfinite(split):
                continue
            r = score_window(raw, system, split, m)
            for k in FEATURE_KEYS:
                row[f"{m}_{split_name}_{k}"] = r[k]
    return row
