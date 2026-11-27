"""Shared helpers of the reproduction scripts: paths, number checks and the report."""
import json
import os
import sys

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
OUT = os.environ.get("ICOIN_OUT", os.path.join(REPO, "outputs"))
sys.path.insert(0, REPO)

_CHECKS = []


def data(*parts):
    return os.path.join(DATA, *parts)


def out(*parts):
    path = os.path.join(OUT, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def read_csv(*parts, **kw):
    kw.setdefault("low_memory", False)
    kw.setdefault("float_precision", "round_trip")
    return pd.read_csv(data(*parts), **kw)


def read_json(*parts):
    with open(data(*parts)) as f:
        return json.load(f)


def _same(a, b, tol):
    if isinstance(b, (list, tuple)):
        return isinstance(a, (list, tuple)) and len(a) == len(b) and all(_same(x, y, tol) for x, y in zip(a, b))
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        try:
            return abs(float(a) - float(b)) <= tol + 1e-12
        except (TypeError, ValueError):
            return False
    return str(a) == str(b)


def _plain(v):
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if hasattr(v, "item"):
        return v.item()
    return v


def check(item, computed, expected, where, tol=0.0, printed=True):
    """Record one check. With ``printed`` the expected value is printed in the paper at ``where``;
    otherwise it is a consistency check against the stored records. Numbers compare within ``tol``."""
    computed = _plain(computed)
    ok = _same(computed, expected, tol)
    _CHECKS.append({"item": item, "computed": computed, "expected": expected, "where": where,
                    "kind": "paper" if printed else "stored", "match": "yes" if ok else "NO"})
    mark = "ok " if ok else "MISMATCH"
    print(f"  [{mark}] {item}: {computed} ({'paper' if printed else 'stored'}: {expected}; {where})")
    return ok


def every(k, n, word="every"):
    """``word`` when all ``n`` qualify (as the paper words it), else "k of n"."""
    return word if k == n else f"{k} of {n}"


def checks():
    return list(_CHECKS)


def pct(k, n, digits=1):
    return round(100.0 * k / n, digits)


def write_checks(name):
    frame = pd.DataFrame(_CHECKS)
    frame.insert(0, "script", name)
    frame.to_csv(out(f"checks_{name}.csv"), index=False, lineterminator="\n")
    bad = int((frame.match != "yes").sum()) if len(frame) else 0
    n_paper = int((frame.kind == "paper").sum()) if len(frame) else 0
    print(f"{name}: {len(frame)} checks ({n_paper} paper values, {len(frame) - n_paper} stored-record checks), "
          f"{bad} mismatches -> {out(f'checks_{name}.csv')}")
    _CHECKS.clear()
    return bad
