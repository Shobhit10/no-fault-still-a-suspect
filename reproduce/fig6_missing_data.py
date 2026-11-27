"""Fig. 6 and RQ4 (Sec. III-D): what rankers do when one service's data stop.

For every kind of loss, the number of fault windows in which each ranker still names the faulty
service after the copy is made (the ranker splits at the event time), next to the intact windows.
Recomputed from ``data/e3|e4/copy_features.csv`` with ``fouroutcome.policy.evaluate``.
The data-only rules were designed on E3, so the E3 staleness results are post hoc and the E4
ones prospective. See ``fouroutcome/copies.py`` for how the "other" kind is made (Sec. II-E).
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from _common import check, data, out, read_csv, write_checks  # noqa: E402
from fouroutcome.policy import evaluate, load_thresholds  # noqa: E402

KINDS = [("intact", None), ("all data", "full"), ("late", "late"), ("intermittent", "intermittent"),
         ("mesh only", "family"), ("another service", "other")]
PAPER = {("e3", "nsigma"): [39, 0, 39, 39, 26, 38], ("e3", "baro"): [38, 0, 38, 38, 32, 38],
         ("e4", "nsigma"): [29, 0, 29, 29, 0, 29], ("e4", "baro"): [29, 0, 29, 29, 0, 29]}
F = "Fig. 6"


def main():
    print("Fig. 6")
    rows = []
    res = {}
    for arm in ("e3", "e4"):
        live, copies = read_csv(arm, "live_features.csv"), read_csv(arm, "copy_features.csv")
        th = load_thresholds(data("data_only", "thresholds_blind.json"), data(arm, "thresholds.json"))
        r = evaluate(live, copies, th)
        res[arm] = r
        for m in ("nsigma", "baro"):
            vals = []
            for name, kind in KINDS:
                v = r["ranker_top1_on_LOC"][f"{m}_event"] if kind is None else \
                    r["loss_patterns"][kind][f"{m}_names_culprit_LOCparent"]
                vals.append(v)
                rows.append({"test": arm.upper(), "ranker": m, "kind": name, "faults_named": v,
                             "faults": r["ranker_top1_on_LOC"]["n"]})
            check(f"{arm.upper()} {m}: faulty service named, intact/all/late/intermittent/mesh/other",
                  vals, PAPER[(arm, m)], F)
        lp = r["loss_patterns"]
        check(f"{arm.upper()} copies per kind (all, late, intermittent, mesh, other)",
              [lp[k]["n"] for k in ("full", "late", "intermittent", "family", "other")],
              [86, 86, 86, 86, 45] if arm == "e3" else [70, 70, 70, 70, 47], f"data/{arm}", printed=False)
        o = copies[copies.pattern == "other"]
        own = int((o.lost_service == o.target.astype(str) + "_cpu").sum())
        check(f"{arm.upper()} other copies that froze the faulty service's own CPU columns", f"{own} of {len(o)}",
              "1 of 45" if arm == "e3" else "4 of 47", "Sec. II-E")
        ranked = all(lp[k][f"{m}_ranked"] == lp[k]["n"] for k in lp for m in ("nsigma", "baro"))
        check(f"{arm.upper()}: both rankers return a ranked list on every copy", ranked, True, "Sec. III-D",
              printed=False)
        check(f"{arm.upper()}: copies flagged by the staleness check", sum(v["flagged"] for v in lp.values()),
              sum(v["n"] for v in lp.values()), f"data/{arm}", printed=False)
        check(f"{arm.upper()}: rankers never name the silenced service when all its data stop",
              [lp["full"]["nsigma_names_lost"], lp["full"]["baro_names_lost"]], [0, 0], "Sec. III-D", printed=False)
    t = pd.DataFrame(rows)
    t.to_csv(out("fig6_missing_data.csv"), index=False, lineterminator="\n")

    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.2), sharey=True)
    for ax, arm, title in zip(axes, ("E3", "E4"), ("E3 CPU hog, 45 faults", "E4 delay, 47 faults")):
        x = np.arange(len(KINDS))
        for i, (m, colour, lab) in enumerate((("nsigma", "#1F4E79", "n-sigma"), ("baro", "#6E6E6E", "BARO"))):
            v = t[(t.test == arm) & (t.ranker == m)].faults_named.to_numpy()
            ax.bar(x + (i - 0.5) * 0.35, v, width=0.35, color=colour, alpha=0.7,
                   hatch="" if m == "nsigma" else "//", label=lab)
            for xi, vi in zip(x + (i - 0.5) * 0.35, v):
                ax.text(xi, vi + 0.8, str(vi), ha="center", fontsize=6, rotation=90)
        ax.set_xticks(x)
        ax.set_xticklabels([n.replace(" ", "\n").replace("intermittent", "inter-\nmittent") for n, _ in KINDS],
                           fontsize=6)
        ax.set_title(title, fontsize=9)
        ax.set_ylim(0, 58)
    axes[0].set_ylabel("faults where the faulty\nservice is named", fontsize=8)
    axes[1].legend(fontsize=7, frameon=False, loc="lower right", bbox_to_anchor=(1, 1.12), ncol=2)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    fig.savefig(out("fig6_missing_data.png"), dpi=200)
    plt.close(fig)
    return write_checks("fig6")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
