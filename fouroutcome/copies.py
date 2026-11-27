"""Missing-data copies for RQ4: Insufficient-Evidence windows in which one service's data stop.

Every No-Incident and Localized window gets copies in which one service's columns stop and are
frozen at their last value, which is how the exporter fills missing samples. The service is the
faulty one (Localized parents) or a seeded choice among the deployment's fault targets (quiet
parents). Five kinds of loss (paper names in brackets):

  full          [all]           every column of the service stops at the split
  late          [late]          every column stops 120 s after the split
  intermittent  [intermittent]  every column stops in three 60-s gaps (split + 0, 120, 240 s)
  family        [mesh-only]     only its mesh columns (latency, istio, tcp) stop at the split
  other         [other]         Localized parents only: the CPU columns of a randomly drawn service
                                stop at the split

A fault copy still holds the fault; its label says only that the data no longer support a
localization.

The "other" kind, as Sec. II-E of the paper states it: the pool of services is built from column
prefixes such as ``cartservice_cpu``, so an "other" copy freezes only that service's CPU columns
(``*_cpu_usage_seconds`` and ``*_cpu_throttling``), and the pool also holds the faulty service's
own ``<target>_cpu`` prefix (drawn in 1 of 45 E3 and 4 of 47 E4 "other" copies). This is
``legacy_other=True`` (default; reproduces the stored copies exactly). ``legacy_other=False``
instead freezes every column of a different service, which was the original intent.
"""
import os

import numpy as np
import pandas as pd

from .window import services_of

PATTERNS = ("full", "late", "intermittent", "family", "other")
PAPER_NAMES = {"full": "all", "late": "late", "intermittent": "intermittent",
               "family": "mesh-only", "other": "other"}
MESH_KEYS = ("latency", "istio", "tcp")
SEED_E3, SEED_E4 = 20261007, 20261008
COPY_SEED = 20261008


def lose(window, service, pattern, split=300.0):
    """Return (copy, frozen_columns): ``service`` loses telemetry as ``pattern`` describes."""
    frame = (window if isinstance(window, pd.DataFrame) else pd.read_csv(window)).copy()
    t = frame["time"].to_numpy(dtype=float)
    cols = [c for c in frame.columns if c.startswith(service + "_")]
    if pattern == "family":
        cols = [c for c in cols if any(k in c[len(service) + 1:] for k in MESH_KEYS)]
    if not cols:
        raise ValueError(f"no columns for {service} ({pattern})")
    if pattern in ("full", "family", "other"):
        blocks = [(split, np.inf)]
    elif pattern == "late":
        blocks = [(split + 120.0, np.inf)]
    elif pattern == "intermittent":
        blocks = [(split + a, split + a + 60.0) for a in (0.0, 120.0, 240.0)]
    else:
        raise ValueError(pattern)
    for a, b in blocks:
        before = t < a
        if not before.any():
            continue
        last = frame.loc[before, cols].iloc[-1]
        inside = (t >= a) & (t < b)
        frame.loc[inside, cols] = last.values
    return frame, cols


def other_pool(window, target, legacy_other=True):
    """Candidate services for an "other" copy of a Localized window (see module docstring)."""
    cols = (window.columns if isinstance(window, pd.DataFrame)
            else pd.read_csv(window, nrows=0).columns)
    if legacy_other:
        names = sorted({c.rsplit("_", 2)[0] for c in cols if c.endswith("_cpu_usage_seconds")})
    else:
        names = services_of(pd.DataFrame(columns=cols))
    return [s for s in names if s != target]


def make_copies(parents, out_dir, seed=COPY_SEED, split=300.0, legacy_other=True, base_dir=""):
    """Write every copy of every parent and return the copy index.

    ``parents``: DataFrame with case_id, system, label (NI or LOC), target, lost_service, path
    (relative paths are resolved against ``base_dir``). Copies are written to
    ``out_dir/<pattern>/<case_id>_<pattern>.csv``."""
    rng = np.random.default_rng(seed)
    rows = []
    for r in parents.sort_values("case_id").itertuples():
        src = r.path if os.path.isabs(r.path) else os.path.join(base_dir, r.path)
        frame = pd.read_csv(src)
        for pattern in PATTERNS:
            if pattern == "other":
                if r.label != "LOC":
                    continue
                lost = str(rng.choice(other_pool(frame, r.target, legacy_other)))
            else:
                lost = r.lost_service
            copy, _ = lose(frame, lost, pattern, split)
            dst = os.path.join(out_dir, pattern, f"{r.case_id}_{pattern}.csv")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            copy.to_csv(dst, index=False)
            rows.append({"case_id": f"{r.case_id}_{pattern}", "parent": r.case_id,
                         "parent_label": r.label, "system": r.system, "target": r.target,
                         "lost_service": lost, "pattern": pattern, "path": dst})
    return pd.DataFrame(rows)


def choose_lost_services(labels, targets, seed):
    """Service silenced in each parent's copies: the faulty one for LOC, a seeded choice among the
    deployment's ``targets[system]`` for NI (in label order: slot, then system)."""
    rng = np.random.default_rng(seed)
    lost = []
    for r in labels.sort_values(["slot", "system"]).itertuples():
        if r.label == "LOC":
            lost.append(r.target)
        elif r.label == "NI":
            lost.append(str(rng.choice(targets[r.system])))
        else:
            lost.append("")
    return lost
