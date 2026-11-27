#!/usr/bin/env python3
"""RQ1: list the ranking entry points of RCAEval.e2e and the fields they return.

Reads the installed RCAEval source (no method is executed). An entry point is a public callable
that accepts ``inject_time`` (or a bare ``**kwargs``, for entry points wrapped by RCAEval's
exception-handling decorator); helpers imported into the module are reported separately. For each
entry point the literal keys of its returned dict are collected and any key that could carry a
support, confidence or rejection value is flagged. The paper found 34 entry points and none with
such a field (data/rq1/rcaeval_entry_points.csv, RCAEval 1.6.0).

Requires RCAEval (requirements-rcaeval.txt).  usage: rcaeval_entry_points.py --out entry_points.csv
"""
import argparse
import ast
import inspect
import textwrap

import pandas as pd

STRUCTURAL = {"ranks", "node_names", "adj"}
SCORE_WORDS = ("score", "conf", "prob", "pval", "p_value", "signif", "weight", "stat", "z", "severity", "anomaly")


def is_entry_point(fn):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return None
    return "inject_time" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def return_keys(fn):
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return None, None
    keys, shapes = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        val = node.value
        if isinstance(val, ast.Dict):
            shapes.add("dict")
            keys.update(k.value if isinstance(k, ast.Constant) and isinstance(k.value, str) else "<dynamic>"
                        for k in val.keys)
        elif isinstance(val, ast.Call):
            shapes.add("call:%s" % getattr(val.func, "id", getattr(val.func, "attr", "?")))
        elif isinstance(val, ast.Name):
            shapes.add("name:%s" % val.id)
        else:
            shapes.add(type(val).__name__)
    return keys, shapes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    from RCAEval import e2e
    names = sorted(n for n in dir(e2e) if not n.startswith("_") and callable(getattr(e2e, n))
                   and getattr(getattr(e2e, n), "__module__", "").startswith("RCAEval"))
    rows = []
    for name in names:
        fn = getattr(e2e, name)
        e = is_entry_point(fn)
        role = "entry_point" if e is True else "utility" if e is False else "unknown_signature"
        keys, shapes = return_keys(fn)
        if keys is None:
            rows.append({"method": name, "role": role, "source": "unavailable", "keys": "", "extra_keys": "",
                         "score_like": ""})
            continue
        rows.append({"method": name, "role": role, "source": "|".join(sorted(shapes)), "keys": "|".join(sorted(keys)),
                     "extra_keys": "|".join(sorted(k for k in keys if k not in STRUCTURAL)),
                     "score_like": "|".join(sorted(k for k in keys if any(w in k.lower() for w in SCORE_WORDS)))})
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    ent = df[df.role == "entry_point"]
    print(f"{len(ent)} ranking entry points; {int((ent.score_like != '').sum())} return a score-like field")


if __name__ == "__main__":
    main()
