"""Fig. 3 and the E1 part of RQ2 (Sec. III-B): gates on the 88 certified healthy windows.

Thresholds are recomputed from the per-call scores of the 129 screened windows: for each target
deployment, the smallest value accepting at most 5% of the OTHER four deployments' screened
windows. Every certified window a gate still accepts is a false alarm. The same thresholds are
applied to the 150 faulty E1 windows (DeathStarBench: the 30 re-run after the registry repair).
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from _common import check, out, pct, read_csv, write_checks  # noqa: E402
from fouroutcome.calibration import threshold_at_acceptance  # noqa: E402
from fouroutcome.policy import gate_scores  # noqa: E402

SYSTEMS = ("boutique", "deathstarbench", "otel-demo", "sock-shop", "train-ticket")
SHOWN = ("boutique", "deathstarbench", "otel-demo", "sock-shop")
SHORT = {"boutique": "OB", "deathstarbench": "DSB", "otel-demo": "OTel", "sock-shop": "SS"}
S = "Sec. III-B"


def certified_gates(calls, target=0.05):
    rows = []
    for m in ("baro", "nsigma"):
        for gate in ("S", "T", "M"):
            for system in SYSTEMS:
                cal = calls[(calls.set == "historical") & (calls.method == m) & (calls.system != system)]
                thr = threshold_at_acceptance(gate_scores(cal, gate).dropna().to_numpy(), target)
                cert = calls[(calls.set == "certified") & (calls.method == m) & (calls.system == system)]
                flt = calls[calls.set.isin(["faulty", "faulty_dsb_matched"]) & (calls.method == m)
                            & (calls.system == system)]
                if system == "deathstarbench":
                    flt = flt[flt.set == "faulty_dsb_matched"]
                acc = gate_scores(flt, gate) >= thr
                rows.append({"method": m, "gate": gate, "system": system, "threshold": thr,
                             "certified": len(cert), "accepted": int((gate_scores(cert, gate) >= thr).sum()),
                             "faulty": len(flt), "faulty_accepted": int(acc.sum()),
                             "faulty_kept_correct": int(flt.loc[acc, "hit"].fillna(0).sum())})
    return pd.DataFrame(rows)


def plot(t, path):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4), sharey=True)
    colours = {"S": "#1F4E79", "T": "#35774A", "M": "#B03A2E"}
    for ax, m, name in zip(axes, ("baro", "nsigma"), ("BARO", "n-sigma")):
        kept = t[t.method == m].groupby("gate").faulty_kept_correct.sum()
        sub = t[(t.method == m) & t.system.isin(SHOWN)]
        for i, gate in enumerate(("S", "T", "M")):
            g = sub[sub.gate == gate].set_index("system").loc[list(SHOWN)]
            xs = [j + (i - 1) * 0.25 for j in range(len(SHOWN))]
            vals = [100 * a / n for a, n in zip(g.accepted, g.certified)]
            ax.bar(xs, vals, width=0.25, color=colours[gate], alpha=0.75,
                   hatch={"S": "", "T": "//", "M": ".."}[gate],
                   label={"S": "S support", "T": "T top score", "M": "M margin"}[gate])
            for x, v, a in zip(xs, vals, g.accepted):
                if a:
                    ax.text(x, v + 0.5, str(a), ha="center", fontsize=7)
        ax.axhline(5, ls="--", color="grey", lw=0.8, label="5% target")
        ax.set_xticks(range(len(SHOWN)))
        ax.set_xticklabels([f"{SHORT[s]}/{int(sub[(sub.system == s) & (sub.gate == 'S')].certified.iloc[0])}"
                            for s in SHOWN], fontsize=8)
        ax.set_title(f"{name} keeps {kept['S']} / {kept['T']} / {kept['M']} of 150", fontsize=9)
        ax.set_ylim(0, 27)
    axes[0].set_ylabel("accepted healthy windows (%)", fontsize=8)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, ncol=4, frameon=False, loc="lower center")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    print("Fig. 3")
    calls = read_csv("e1", "calls.csv")
    t = certified_gates(calls)
    t.to_csv(out("fig3_certified_gates.csv"), index=False, lineterminator="\n")
    plot(t, out("fig3_certified_gates.png"))
    expected = {("baro", "S"): [0, 4, 4, 0], ("baro", "T"): [0, 0, 1, 1], ("baro", "M"): [4, 2, 3, 1],
                ("nsigma", "S"): [0, 2, 4, 0], ("nsigma", "T"): [3, 0, 0, 4], ("nsigma", "M"): [1, 0, 1, 1]}
    for (m, g), counts in expected.items():
        sub = t[(t.method == m) & (t.gate == g)].set_index("system").loc[list(SHOWN)]
        check(f"{m} {g}: accepted certified windows OB/DSB/OTel/SS", sub.accepted.tolist(), counts, "Fig. 3")
    check("Certified windows per deployment OB/DSB/OTel/SS",
          t[(t.method == "baro") & (t.gate == "S")].set_index("system").loc[list(SHOWN)].certified.tolist(),
          [18, 22, 24, 24], "Fig. 3")
    kept = t.groupby(["method", "gate"]).faulty_kept_correct.sum()
    check("BARO kept correct answers S / T / M (of 150)", [int(kept[("baro", g)]) for g in "STM"], [147, 147, 84],
          "Fig. 3, Sec. III-B")
    check("n-sigma kept correct answers S / T / M (of 150)", [int(kept[("nsigma", g)]) for g in "STM"],
          [140, 140, 64], "Fig. 3")
    ob = t[(t.method == "baro") & (t.gate == "M") & (t.system == "boutique")].iloc[0]
    check("BARO margin gate in Online Boutique (accepted of certified)", f"{ob.accepted} of {ob.certified}",
          "4 of 18", S)
    check("... as a percentage", round(pct(ob.accepted, ob.certified, 0)), 22, S)
    check("Largest share of one deployment's certified windows accepted (%)",
          round(max(100 * a / n for a, n in zip(t.accepted, t.certified) if n)), 22, S)

    # the same numbers as the locked analysis output
    locked = read_csv("e1", "gates_locked.csv")
    locked = locked[locked.target == 0.05]
    same = True
    for r in locked.itertuples():
        per = json.loads(r.per_system)
        for s, v in per.items():
            mine = t[(t.method == r.method) & (t.gate == r.gate) & (t.system == s)].iloc[0]
            same &= (v["cert_accepted"] == mine.accepted and v["faulty_correct"] == mine.faulty_kept_correct
                     and abs(v["threshold"] - mine.threshold) <= 1e-12 * abs(v["threshold"]))
    check("Counts identical and thresholds within 1e-12 of the locked analysis output (gates_locked.csv)",
          same, True, "data/e1", printed=False)
    return write_checks("fig3")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
