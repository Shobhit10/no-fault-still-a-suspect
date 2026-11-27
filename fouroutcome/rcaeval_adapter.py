"""Optional adapter to the rankers of the RCAEval library (needed only for the RQ1 audits).

BARO and n-sigma are implemented in ``fouroutcome.rankers``; the random baseline ("dummy") and the
random-walk methods (granger_randomwalk, lingam_randomwalk) of RQ1 come from RCAEval itself:
    pip install -r requirements-rcaeval.txt     (Python 3.10, RCAEval 1.6.0)

RCAEval wraps most entry points so that an exception inside the method is replaced by a ranking
of the input columns in their original order. ``call_ranker`` calls the unwrapped method first
and, only if that raises, the public (wrapped) entry point, so that a ranking that exists only
because the wrapper caught an exception is marked ``fallback=True``.
"""
import inspect


def _strict(function):
    if function.__name__ != "wrapper":
        return function
    closure = inspect.getclosurevars(function).nonlocals
    if set(closure) != {"func"} or not callable(closure["func"]):
        raise ValueError("unrecognised ranking wrapper")
    return closure["func"]


def call_ranker(method, data, split_time, sli=None, dataset="custom"):
    """Return dict(ok, ranks, api_ranked, fallback, error) for one RCAEval ranker call."""
    from RCAEval import e2e
    kwargs = dict(inject_time=split_time, dataset=dataset, sli=sli, anomalies=None,
                  dk_select_useful=False, verbose=False, n_iter=len(data.columns) - 1)
    out = {"ok": False, "ranks": [], "api_ranked": False, "fallback": False, "error": ""}
    try:
        res = _strict(getattr(e2e, method))(data.copy(), **kwargs)
        ranks = list((res.get("ranks") if isinstance(res, dict) else res) or [])
        out.update(ok=True, ranks=ranks, api_ranked=bool(ranks))
    except Exception as e:  # the method failed: record it, then ask the public entry point
        out["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        try:
            res = getattr(e2e, method)(data.copy(), **kwargs)
            ranks = list((res.get("ranks") if isinstance(res, dict) else res) or [])
            out.update(ranks=ranks, api_ranked=bool(ranks), fallback=bool(ranks))
        except Exception as e2:
            out["error"] += f" | wrapped: {type(e2).__name__}"
    return out
