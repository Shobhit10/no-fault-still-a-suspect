"""Fig. 4 and the E2 part of RQ2 (Sec. III-B): gates and validity check V on held-out RE3 code faults.

Recomputes every policy row of the locked RE2 -> RE3 evaluation from the per-call records
(``data/e2/calls_re2_re3.csv``): for each RCAEval dataset and ranker, gate thresholds are set at
1, 5 and 10% on the RE2 pre-injection segments of the OTHER two systems, then applied to the
dataset's labelled (fault) segments and its own pre-injection segments. Fig. 4 pools the three RE3
datasets at the 5% target.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from _common import check, every, out, read_csv, write_checks  # noqa: E402
from fouroutcome.benchmark import RATES, summarize  # noqa: E402
from fouroutcome.measures import auroc  # noqa: E402

S = "Sec. III-B"


def _bool(frame, cols):
    for c in cols:
        frame[c] = frame[c].astype(str).str.lower().eq("true")
    return frame


def load_calls(name):
    d = read_csv("e2", name)
    return _bool(d, ["eligible", "rank_emitted", "support_valid", "score_valid", "score_parity",
                     "all_candidates_observed", "detector_valid"])


def pooled(pol, suite, method, gate, rate):
    p = pol[(pol.suite == suite) & (pol.method == method) & (pol.gate == gate)]
    p = p[p.rate.isna()] if rate is None else p[np.isclose(p.rate.astype(float), rate)]
    return {"pre_accepted_pct": round(100 * p.pre_accepted.sum() / p.pre_cases.sum(), 1),
            "selective_top1_pct": round(100 * p.correct.sum() / p.localized.sum(), 1) if p.localized.sum() else 0.0,
            "yield_pct": round(100 * p.correct.sum() / p.cases.sum(), 1),
            "localized": int(p.localized.sum()), "correct": int(p.correct.sum())}


def plot(fig_rows, path):
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4), sharey=True)
    for ax, m, name in zip(axes, ("baro", "nsigma"), ("BARO", "n-sigma")):
        sub = fig_rows[fig_rows.method == m].set_index("gate").loc[["V", "S", "T", "M", "D"]]
        x = np.arange(5)
        for i, (col, colour, lab) in enumerate((("pre_accepted_pct", "#B03A2E", "pre-injection segments accepted"),
                                                ("selective_top1_pct", "#1F4E79", "selective top-1"),
                                                ("yield_pct", "#35774A", "yield"))):
            ax.bar(x + (i - 1) * 0.27, sub[col], width=0.27, color=colour, alpha=0.75,
                   hatch=("", "//", "..")[i], label=lab)
            if m == "baro" and col in ("pre_accepted_pct", "selective_top1_pct"):
                ax.text(2 + (i - 1) * 0.27, sub.loc["T", col] + 1, f"{sub.loc['T', col]:.1f}",
                        ha="center", va="bottom", fontsize=6)
        ax.set_xticks(x)
        ax.set_xticklabels(["V", "S", "T", "M", "D"])
        ax.set_title(name, fontsize=9)
        ax.set_ylim(0, 120)
    axes[0].set_ylabel("percent", fontsize=8)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main():
    print("Fig. 4")
    d = load_calls("calls_re2_re3.csv")
    pol = summarize(d)
    pol.drop(columns=["accepted_cases"]).to_csv(out("e2_policies.csv"), index=False, lineterminator="\n")

    # identical to the locked policies
    locked = read_csv("e2", "policies_locked.csv")
    key = ["dataset", "method", "gate"]
    a = pol.assign(rate=pol.rate.astype(float)).sort_values(key + ["rate"]).reset_index(drop=True)
    b = locked.sort_values(key + ["rate"]).reset_index(drop=True)
    cols = ["pre_accepted", "localized", "correct", "cases"]
    check("E2 policy rows identical to the locked summary (156 rows)",
          bool(len(a) == len(b) == 156 and (a[cols].values == b[cols].values).all()), True, "data/e2",
          printed=False)

    expected = {"baro": {"V": (88.9, 59.8, 57.8), "S": (5.6, 92.5, 54.4), "T": (18.9, 3.3, 1.1),
                         "M": (14.4, 0.0, 0.0), "D": (5.6, 55.8, 26.7)},
                "nsigma": {"V": (94.4, 84.8, 74.4), "S": (10.0, 88.6, 68.9), "T": (4.4, 87.9, 64.4),
                           "M": (7.8, 98.0, 53.3), "D": (6.7, 74.4, 32.2)}}
    rows = []
    for m, gates in expected.items():
        for g, vals in gates.items():
            p = pooled(pol, "RE3", m, g, None if g == "V" else 0.05)
            rows.append({"method": m, "gate": g, **p})
            check(f"RE3 {m} {g}: pre-injection accepted / selective top-1 / yield (%)",
                  [p["pre_accepted_pct"], p["selective_top1_pct"], p["yield_pct"]], list(vals),
                  "Fig. 4 bar heights, data/e2", printed=False)
    fig_rows = pd.DataFrame(rows)
    fig_rows.to_csv(out("fig4_public_gates.csv"), index=False, lineterminator="\n")
    plot(fig_rows, out("fig4_public_gates.png"))
    top = fig_rows[(fig_rows.method == "baro") & (fig_rows.gate == "T")].iloc[0]
    check("BARO T: pre-injection segments accepted (%)", top.pre_accepted_pct, 18.9, "Fig. 4")
    check("BARO T: selective top-1 (%)", top.selective_top1_pct, 3.3, "Fig. 4")

    # BARO top-score gate: RE2 at 5%, RE3 at each source target
    e2 = pooled(pol, "RE2", "baro", "T", 0.05)
    check("BARO T at 5%: right of accepted RE2 cases", f"{e2['correct']} of {e2['localized']}", "37 of 63", S)
    for r in RATES:
        e3 = pooled(pol, "RE3", "baro", "T", r)
        check(f"BARO T at {int(r * 100)}%: right of accepted RE3 code faults",
              f"{e3['correct']} of {e3['localized']}", "1 of 30", "Fig. 4, Sec. III-B")

    # the 29 wrong RE3 answers of BARO's top-score gate rest on disk-I/O columns with a zero IQR
    t5 = pol[(pol.suite == "RE3") & (pol.method == "baro") & (pol.gate == "T") & np.isclose(pol.rate.astype(float), 0.05)]
    accepted = {(r.dataset, c) for r in t5.itertuples() for c in r.accepted_cases.split("|") if c}
    lab = d[(d.method == "baro") & (d.segment == "benchmark_labelled")]
    in_acc = pd.Series([(r.dataset, r.case) in accepted for r in lab.itertuples()], index=lab.index)
    wrong = lab[in_acc & lab.hit.eq(0)]
    z = read_csv("e2", "zero_iqr_nominations.csv")
    z = z[z.segment == "benchmark_labelled"].astype({"zero_iqr": str})
    w = wrong.merge(z[["dataset", "case", "zero_iqr", "top1"]], on=["dataset", "case"], suffixes=("", "_z"))
    diskio_zero = int((w.top1.str.endswith("_diskio") & w.zero_iqr.str.lower().eq("true")).sum())
    check("BARO T wrong RE3 answers naming a disk-I/O column with zero reference IQR",
          every(diskio_zero, len(wrong), f"all {len(wrong)}"), "all 29", S)

    # units leak into the score: dividing every disk-I/O column by 1,024
    u = read_csv("e2", "unit_rescaling_calls.csv")
    u = u[np.isclose(u.factor, 1 / 1024)]
    ch = u.groupby("method").service_changed.apply(lambda s: int(s.astype(str).str.lower().eq("true").sum()))
    n_u = int((u.method == "baro").sum())
    check("Named service changes after /1,024 rescaling, BARO | n-sigma",
          f"{ch['baro']} of {n_u} | {'none' if ch['nsigma'] == 0 else ch['nsigma']}", "21 of 90 | none", S)

    # detector D: detection task (paired) and as evidence that the named service is right
    r1 = load_calls("calls_re1.csv")
    for suite, n, share in (("RE2", 269, 95), ("RE3", 87, 83)):
        b = d[(d.suite == suite) & (d.method == "baro") & d.detector_valid].copy()
        b["score"] = pd.to_numeric(b.detector_score, errors="coerce")
        b = b[np.isfinite(b.score)]
        wide = b.pivot_table(index=["dataset", "case"], columns="segment", values="score").dropna()
        paired = ((wide.benchmark_labelled > wide.pre_injection)
                  + 0.5 * (wide.benchmark_labelled == wide.pre_injection)).mean()
        check(f"D scores the faulty above the pre-injection segment, {suite} (% of complete cases)",
              f"{round(100 * paired)}% of {len(wide)}", f"{share}% of {n}", S)
    best = 0.0
    for suite, frame in (("RE1", r1), ("RE2", d[d.suite == "RE2"]), ("RE3", d[d.suite == "RE3"])):
        for m in ("baro", "nsigma"):
            g = frame[(frame.segment == "benchmark_labelled") & frame.score_valid & frame.support_valid
                      & frame.detector_valid & (frame.method == m)]
            g = g[pd.to_numeric(g.detector_score, errors="coerce").notna()]
            hit = g.hit.astype(int).eq(1)
            s = pd.to_numeric(g.detector_score)
            best = max(best, auroc(s[hit], s[~hit]))
    check("Largest AUROC of D as evidence that the named service is right (RE1-RE3, both rankers)",
          f"{best:.2f}", "0.61", S)
    return write_checks("fig4")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
