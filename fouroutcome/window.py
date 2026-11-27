"""Exported telemetry windows and the frame a ranker receives.

An exported window is one CSV per window on a 5-s grid: a ``time`` column (seconds from the window
start) and one column per ``<service>_<metric>`` (see ``experiments/live/export_window.py``).
Rankers read five of these metrics, renamed into RCAEval's ``<service>_<family>`` schema.
"""
import numpy as np
import pandas as pd

# exported column suffix -> the schema RCAEval methods expect
SUFFIX_MAP = [
    ("_cpu_usage_seconds", "_cpu"),
    ("_memory_usage_bytes", "_mem"),
    ("_latency_p90", "_latency"),
    ("_istio_requests", "_workload"),
    ("_istio_errors", "_error"),
]

# front-end latency column of each studied application (used only as the `sli` argument of
# RCAEval methods that take one; BARO and n-sigma ignore it)
SLI_MAP = {
    "boutique": "frontend_latency",
    "otel-demo": "frontend_latency",
    "deathstarbench": "frontend_latency",
    "sock-shop": "front-end_latency",
    "train-ticket": "ts-ui-dashboard_latency",
}


def to_ranker_frame(df):
    """Rename exported columns into RCAEval's <service>_<metric> schema, dropping the rest."""
    out = {"time": df["time"].values}
    for col in df.columns:
        for ours, theirs in SUFFIX_MAP:
            if col.endswith(ours):
                out[col[: -len(ours)] + theirs] = pd.to_numeric(df[col], errors="coerce").values
                break
    return pd.DataFrame(out)


def load_window(path_or_frame):
    """Ranker-visible frame of an exported window (mirrors RCAEval's own loading: inf -> NaN,
    forward fill, then zero fill)."""
    df = path_or_frame if isinstance(path_or_frame, pd.DataFrame) else pd.read_csv(path_or_frame)
    rc = to_ranker_frame(df)
    rc = rc.replace([np.inf, -np.inf], np.nan)
    return rc.ffill().fillna(0)


def sli_for(system, data):
    """Front-end latency column, falling back to any front-end-like latency present."""
    want = SLI_MAP.get(system)
    if want in data.columns:
        return want
    for c in data.columns:
        if c.endswith("_latency") and ("frontend" in c or "front-end" in c or "ui-dashboard" in c):
            return c
    cands = [c for c in data.columns if c.endswith("_latency")]
    return cands[0] if cands else None


def service_of(column):
    """Service part of a ranker column name (``cartservice_cpu`` -> ``cartservice``)."""
    return column.rsplit("_", 1)[0]


def services_of(path_or_frame):
    """Services present in an exported window (those with a CPU column)."""
    cols = (path_or_frame.columns if isinstance(path_or_frame, pd.DataFrame)
            else pd.read_csv(path_or_frame, nrows=0).columns)
    return sorted({c.rsplit("_", 2)[0] for c in cols if c.endswith("_cpu_usage_seconds")})
