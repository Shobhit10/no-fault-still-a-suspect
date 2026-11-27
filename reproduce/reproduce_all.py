"""Regenerate the paper's numbers, Table I and Figs. 3-6 from data/ and compare with the paper.

    python reproduce/reproduce_all.py

Writes outputs/ (figures, tables, one checks_<script>.csv per script and REPRODUCTION.md).
Exit code 0 only if every value matches the paper and the stored records.
"""
import glob
import os
import time

import pandas as pd

import fig3_certified_gates
import fig4_public_gates
import fig5_live_policies
import fig6_missing_data
import rq1
import table1
from _common import OUT, out

STEPS = [("table1", table1), ("rq1", rq1), ("fig3", fig3_certified_gates), ("fig4", fig4_public_gates),
         ("fig5", fig5_live_policies), ("fig6", fig6_missing_data)]


def main():
    t0 = time.time()
    bad = 0
    for name, mod in STEPS:
        print()
        bad += mod.main()
    frames = [pd.read_csv(out(f"checks_{name}.csv")) for name, _ in STEPS]
    allc = pd.concat(frames, ignore_index=True)
    allc.to_csv(out("checks_all.csv"), index=False, lineterminator="\n")
    n_paper = int((allc.kind == "paper").sum())
    lines = ["# Reproduction report", "",
             f"{len(allc)} checks ({n_paper} values printed in the paper, {len(allc) - n_paper} checks against "
             f"the stored records), {int((allc.match != 'yes').sum())} mismatches ({time.time() - t0:.0f} s).", "",
             "| script | item | computed | expected | kind | where | match |", "|---|---|---|---|---|---|---|"]
    for r in allc.itertuples():
        lines.append(f"| {r.script} | {r.item} | {r.computed} | {r.expected} | {r.kind} | {r.where} | {r.match} |")
    lines += ["", "Figures: " + ", ".join(sorted(os.path.basename(p) for p in glob.glob(os.path.join(OUT, "*.png"))))]
    with open(out("REPRODUCTION.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n{len(allc)} checks ({n_paper} paper values), {bad} mismatches; report: {out('REPRODUCTION.md')}")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
