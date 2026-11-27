"""Measures: coverage, selective top-1 accuracy and yield (Sec. II-B of the paper), plus helpers."""
import numpy as np


def policy_metrics(hits, accepted):
    """Cov = |L|/|C|, SelTop1 = |K|/|L|, Yield = |K|/|C| for one gate on labelled fault cases.

    ``hits``: 1 if the named service is an injected one (NaN counts as 0); ``accepted``: the gate
    answered (did not decline). Failed calls stay in the denominator."""
    hits = np.nan_to_num(np.asarray(hits, dtype=float), nan=0.0)
    accepted = np.asarray(accepted, dtype=bool)
    if len(hits) != len(accepted):
        raise ValueError("decision mask is not aligned with cases")
    total = len(hits)
    localized = int(accepted.sum())
    correct = int(hits[accepted].sum()) if localized else 0
    sel = correct / localized if localized else float("nan")
    return {"cases": total, "localized": localized, "correct": correct,
            "coverage": localized / total if total else float("nan"),
            "selective_top1": sel, "risk": 1.0 - sel if localized else float("nan"),
            "correct_diagnosis_yield": correct / total if total else float("nan")}


def auroc(pos, neg):
    """Area under the ROC curve of scores ``pos`` against ``neg`` (ties count one half)."""
    p, n = np.asarray(pos, float), np.asarray(neg, float)
    p, n = p[np.isfinite(p)], n[np.isfinite(n)]
    if not len(p) or not len(n):
        return float("nan")
    return float(((p[:, None] > n[None, :]).sum() + 0.5 * (p[:, None] == n[None, :]).sum())
                 / (len(p) * len(n)))


def clopper_pearson(k, n, alpha=0.05):
    """Exact two-sided (1 - alpha) interval for a binomial proportion k / n."""
    from scipy.stats import beta
    if n == 0:
        return (float("nan"), float("nan"))
    lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
    return (lo, hi)


def wilson(correct, accepted, z=1.959963984540054):
    """Wilson score interval for correct / accepted (descriptive only)."""
    if accepted == 0:
        return None, None
    p = correct / accepted
    center = (p + z * z / (2 * accepted)) / (1 + z * z / accepted)
    radius = z * np.sqrt(p * (1 - p) / accepted + z * z / (4 * accepted ** 2))
    radius /= 1 + z * z / accepted
    return center - radius, center + radius


def concentration(named):
    """Share of calls naming the most frequent service (one deployment's list of named services)."""
    import pandas as pd
    s = pd.Series(named).replace("", np.nan).dropna()
    return float(s.value_counts().iloc[0] / len(s)) if len(s) else float("nan")
