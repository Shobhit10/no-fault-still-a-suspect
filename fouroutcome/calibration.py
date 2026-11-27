"""Threshold calibration: a source acceptance target, frozen on other deployments.

Each gate threshold is the smallest value that accepts at most a target share (1, 5 or 10%; 5% in
the paper's headline results) of the finite scores of a source set of windows without an injected
fault. The source never contains the deployment the threshold is used on ("leave one deployment
out"). A source target tests transfer; it does not bound false positives on the new deployment.
"""
import numpy as np

TARGETS = (0.01, 0.05, 0.10)


def threshold_at_acceptance(scores, target):
    """Smallest threshold tau with mean(score >= tau) <= target over the finite source scores.

    Candidates are 0 and the next float above every observed score, so ties are accepted or
    rejected together."""
    numeric = np.asarray(scores, dtype=float)
    numeric = numeric[np.isfinite(numeric)]
    if not len(numeric) or not 0.0 <= target <= 1.0:
        raise ValueError("threshold selection requires finite scores and target in [0,1]")
    candidates = np.unique(np.concatenate(([0.0], np.nextafter(numeric, np.inf))))
    for threshold in candidates:
        if float(np.mean(numeric >= threshold)) <= target:
            return float(threshold)
    return float(candidates[-1])


def leave_one_out_thresholds(frame, score_col, group_col="system", targets=TARGETS, groups=None,
                             valid=None):
    """{group: {str(target): tau}} with each group's tau set on the OTHER groups' rows only.

    ``valid`` is an optional boolean mask; rows where it is False are not used as source scores."""
    groups = sorted(frame[group_col].unique()) if groups is None else groups
    out = {}
    for g in groups:
        src = frame[frame[group_col] != g]
        vals = src[score_col].astype(float)
        if valid is not None:
            vals = vals.where(valid.loc[src.index])
        out[g] = {str(t): threshold_at_acceptance(vals.to_numpy(dtype=float), t) for t in targets}
    return out
