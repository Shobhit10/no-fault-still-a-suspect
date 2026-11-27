"""Fig. 5, RQ3 and RQ4 (Secs. III-C and III-D): the four outcomes on the live tests E3 (CPU hog) and E4
(network delay).

Every value is recomputed with ``fouroutcome.policy.evaluate`` from the per-window features
(``data/e3|e4/live_features.csv`` and ``copy_features.csv``) and the thresholds frozen before each
test (``data/e3/thresholds.json`` for the layered policy, ``data/data_only/thresholds_blind.json``
for the data-only policy). ``rerun_from_windows.py`` recomputes those features from the exported
windows.

Status (as stated in the paper): the E3 design, labels and layered ("oracle") policy were locked
on 7 Oct 2026 before any E3 window existed; the data-only rules were developed on E3 afterwards,
so every data-only E3 number is post hoc. E4 (design, both policies and thresholds) was locked on
8 Oct 2026 before any E4 window existed, so its data-only results are prospective.
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from _common import check, data, every, out, read_csv, read_json, write_checks  # noqa: E402
from fouroutcome.policy import decide, evaluate, load_thresholds  # noqa: E402

ROWS = [("ranker alone", "oracle_cov_event|nsigma_ranker"), ("oracle V, D", "oracle_cov_event|nsigma_nogate"),
        ("oracle V, D, M", "oracle_cov_event|nsigma_M"), ("oracle V, D, S (BARO)", "oracle_cov_event|baro_S"),
        ("oracle V, D, M (BARO)", "oracle_cov_event|baro_M"), ("data-only V, D", "blind|nsigma_nogate"),
        ("data-only V, D, M", "blind|nsigma_M"), ("data-only V, D, M (BARO)", "blind|baro_M")]
PAPER = {  # (R, W, K) per row of Fig. 5; the ranker is n-sigma unless BARO is named
    "e3": [(39, 72, 39), (80, 31, 39), (84, 0, 21), (81, 27, 38), (90, 0, 27), (64, 23, 27), (74, 0, 18), (75, 0, 19)],
    "e4": [(29, 59, 29), (60, 28, 29), (45, 0, 5), (60, 27, 29), (50, 3, 10), (42, 32, 20), (34, 3, 5), (35, 0, 6)]}
F = "Fig. 5"


def load_arm(arm):
    live = read_csv(arm, "live_features.csv")
    copies = read_csv(arm, "copy_features.csv")
    th = load_thresholds(data("data_only", "thresholds_blind.json"), data(arm, "thresholds.json"))
    return live, copies, th


def plot(results, path):
    """Diverging bars as in the paper: wrong localizations W to the left, right answers R to the right
    with the kept correct answers K as their dark part; light bars span all windows."""
    fig, axes = plt.subplots(2, 1, figsize=(3.8, 4.8))
    for ax, (arm, title, n) in zip(axes, (("e3", "E3 CPU hog, 111 windows", 111),
                                          ("e4", "E4 network delay, 88 windows", 88))):
        pol = results[arm]["policies_live"]
        y = np.arange(len(ROWS))[::-1]
        for yi, (_, key) in zip(y, ROWS):
            r, w, k = pol[key]["right"], pol[key]["wrong_loc"], pol[key]["loc_kept"]
            ax.barh(yi, n, height=0.72, color="#EBEBEB")
            ax.barh(yi, r, height=0.72, color="#B1C1D0")
            ax.barh(yi, k, height=0.72, color="#1F4E79")
            if w:
                ax.barh(yi, -w, height=0.72, color="#963127")
            ax.text(-w - 2, yi, str(w), ha="right", va="center", fontsize=6.5)
            ax.text(n + 2, yi, f"{r} ({k})", ha="left", va="center", fontsize=6.5)
        ax.axvline(0, color="black", lw=0.6)
        ax.axhline(2.5, ls="--", color="grey", lw=0.6)
        ax.set_xlim(-86, 141)  # one scale for both tests, so the zero lines align
        ax.set_yticks(y)
        ax.set_yticklabels([lab for lab, _ in ROWS], fontsize=6.5)
        ax.tick_params(axis="y", length=0)
        ax.set_xticks([])
        for side in ("top", "right", "bottom", "left"):
            ax.spines[side].set_visible(False)
        ax.set_title(title, fontsize=8, loc="left", fontweight="bold", pad=20 if arm == "e3" else 4)
    zero = 86 / (86 + 141)
    axes[0].text(zero - 0.01, 1.01, "wrong\nlocalizations W", transform=axes[0].transAxes, ha="right", va="bottom",
                 fontsize=6.5)
    axes[0].text(zero + 0.01, 1.01, "right answers R,\nkept correct K (dark)", transform=axes[0].transAxes,
                 ha="left", va="bottom", fontsize=6.5)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)

def main():
    print("Fig. 5, RQ3, RQ4")
    results, frames = {}, {}
    for arm in ("e3", "e4"):
        live, copies, th = load_arm(arm)
        results[arm] = evaluate(live, copies, th)
        frames[arm] = (live, copies, th)
        with open(out(f"{arm}_evaluation.json"), "w") as f:
            json.dump(results[arm], f, indent=1, default=float)
    plot(results, out("fig5_live_policies.png"))
    table = []
    for arm in ("e3", "e4"):
        pol = results[arm]["policies_live"]
        for (row, key), exp in zip(ROWS, PAPER[arm]):
            got = (pol[key]["right"], pol[key]["wrong_loc"], pol[key]["loc_kept"])
            table.append({"test": arm.upper(), "policy": row, "R": got[0], "W": got[1], "K": got[2]})
            check(f"{arm.upper()} {row}: R, W, K", list(got), list(exp), F)
    pd.DataFrame(table).to_csv(out("fig5_live_policies.csv"), index=False, lineterminator="\n")

    # stored locked outputs are reproduced as a whole
    check("E3 evaluation identical to the stored post-hoc summary (summary_locked.json)",
          _same_tables(results["e3"], read_json("e3", "summary_locked.json")), True, "data/e3", printed=False)
    check("E4 evaluation identical to the locked analysis report (report_locked.json)",
          _same_tables(results["e4"], read_json("e4", "report_locked.json")), True, "data/e4", printed=False)

    # ---------------------------------------------------------------- RQ3 (Sec. III-C)
    R = "Sec. III-C"
    lab3 = read_csv("e3", "labels.csv")
    by = lab3.groupby("cls").label.value_counts().unstack(fill_value=0)
    check("E3 CPU faults that affected users", f"{by.loc['LOC', 'LOC']} of {by.loc['LOC'].sum()}", "45 of 48", R)
    check("E3 quiet windows certified", f"{by.loc['NI', 'NI']} of {by.loc['NI'].sum()}", "41 of 48", R)
    check("E3 surges: Unresolved; excluded for a restart; lost raw coverage",
          f"{by.loc['UNR', 'UNR']} of {by.loc['UNR'].sum()}; {by.loc['UNR', 'UNR_restart']}; {by.loc['UNR', 'IE_natural']}",
          "22 of 40; 15; 3", R)
    e3, e4 = results["e3"]["policies_live"], results["e4"]["policies_live"]
    r3, r4a = e3["oracle_cov_event|nsigma_ranker"], e4["oracle_cov_event|nsigma_ranker"]
    check("Windows without a fault where the ranker alone names a service, E3 | E4",
          f"{r3['n'] - r3['LOC_n']} | {r4a['n'] - r4a['LOC_n']}", "66 | 41", R)
    vd = e3["oracle_cov_event|nsigma_nogate"]
    check("E3 V+D: No-Incident on quiet windows; correct answers kept",
          f"{vd['NI_right']} of {vd['NI_n']}; {vd['loc_kept']}", "38 of 41; 39", R)
    live3, _, th3 = frames["e3"]
    sc = live3[live3.truth.isin(["NI", "IE", "UNR", "LOC"])]
    o = np.array(decide(sc, th3, "nsigma", None, "0.05", coverage_from="e12_fail", split="event",
                        d_col="D_event", d_th=th3["D_r5"]))
    wrong = (o == "LOC") & ~((sc.truth == "LOC") & (sc.nsigma_event_top1_service.fillna("") == sc.target)).to_numpy()
    tr = sc.truth.to_numpy()
    check("E3 V+D wrong localizations: total = surges + quiet windows where D fired + faults with the wrong service",
          f"{int(wrong.sum())} = {int((wrong & (tr == 'UNR')).sum())} + {int((wrong & (tr == 'NI')).sum())} + "
          f"{int((wrong & (tr == 'LOC')).sum())}", "31 = 22 + 3 + 6", R)
    check("Detector D AUROC, incidents vs quiet windows, E3 | E4",
          f"{results['e3']['detection']['auroc_event']:.2f} | {results['e4']['detection']['auroc_event']:.2f}",
          "1.00 | 1.00", R)
    m3 = e3["oracle_cov_event|nsigma_M"]
    check("E3 V+D+M: wrong localizations; surges answered Unresolved",
          f"{m3['wrong_loc']}; {every(m3['UNR_right'], m3['UNR_n'], 'every surge')}", "0; every surge", R)
    check("E3 correct answers withheld by M (of those kept by V+D)",
          f"{vd['loc_kept'] - m3['loc_kept']} of {vd['loc_kept']}", "18 of 39", R)
    check("E3 right answers, V+D to V+D+M", f"from {vd['right']} to {m3['right']} of {vd['n']}", "from 80 to 84 of 111", R)
    s = np.array(decide(sc, th3, "baro", "S", "0.05", coverage_from="e12_fail", split="event", d_col="D_event",
                        d_th=th3["D_r5"]))
    check("E3 BARO with S names one service on surges",
          f"{int(((s == 'LOC') & (tr == 'UNR')).sum())} of {int((tr == 'UNR').sum())}", "20 of 22", R)
    r4 = results["e4"]["ranker_top1_on_LOC"]
    check("E4 faults where n-sigma | BARO names the delayed service",
          f"{r4['nsigma_event']} | {r4['baro_event']} of {r4['n']}", "29 | 29 of 47", R)
    check("E4 n-sigma wrong answers naming a caller or callee", _neighbours(frames["e4"][0]), "17 of 18", R)
    vd4, m4 = e4["oracle_cov_event|nsigma_nogate"], e4["oracle_cov_event|nsigma_M"]
    check("E4 correct answers withheld by M", f"{vd4['loc_kept'] - m4['loc_kept']} of {vd4['loc_kept']}", "24 of 29",
          R)
    check("E4 right answers, V+D to V+D+M", f"from {vd4['right']} to {m4['right']} of {vd4['n']}", "from 60 to 45 of 88", R)

    # ---------------------------------------------------------------- RQ4 (Sec. III-D)
    Q = "Sec. III-D"
    flagged = sum(v["flagged"] for a in ("e3", "e4") for v in results[a]["loss_patterns"].values())
    copies_n = sum(v["n"] for a in ("e3", "e4") for v in results[a]["loss_patterns"].values())
    check("Missing-data copies flagged by the staleness check", every(flagged, copies_n, f"all {copies_n}"), "all 716",
          "Sec. III-D, Fig. 6")
    sa = read_csv("e3", "series_audit_windows.csv")
    fail = sa[~sa.per_series_lifetime.astype(bool)][["case_id"]]
    f = fail.merge(live3, on="case_id")
    stale_flag = sum(r.stale >= th3["stale"][r.system]["0.05"] for r in f.itertuples())
    check("E3 windows failing the series-by-series coverage audit that the check flags", f"{stale_flag} of {len(fail)}",
          "9 of 10", Q)
    s4 = results["e4"]["stale_live"]["IE_natural"]
    check("E4 windows that lost coverage flagged", f"{s4['flagged']} of {s4['n']}", "5 of 9", Q)
    s3 = results["e3"]["stale_live"]
    check("E3 quiet windows | faults flagged", f"{s3['NI']['flagged']} of {s3['NI']['n']} | {s3['LOC']['flagged']} of {s3['LOC']['n']}",
          "6 of 41 | 15 of 45", Q)
    check("Intact E3 quiet and fault windows flagged",
          f"{s3['NI']['flagged'] + s3['LOC']['flagged']} of {s3['NI']['n'] + s3['LOC']['n']}",
          "21 of 86", Q)
    check("E4 quiet windows flagged", f"{results['e4']['stale_live']['NI']['flagged']} of {results['e4']['stale_live']['NI']['n']}",
          "3 of 23", Q)
    check("Staleness threshold in Online Boutique (s, 5% target)", round(th3["stale"]["boutique"]["0.05"], 6), 30, Q)
    ob = []
    for arm in ("e3", "e4"):
        lv, _, th = frames[arm]
        q = lv[lv.label == "NI"]
        fl = q[[r.stale >= th["stale"][r.system]["0.05"] for r in q.itertuples()]]
        ob.append(f"{int((fl.system == 'boutique').sum())} of {len(fl)}")
    check("Flagged quiet windows in Online Boutique, E3 | E4", " | ".join(ob), "5 of 6 | 3 of 3",
          Q + " (mostly in Online Boutique)", printed=False)
    b3, b4 = e3["blind|nsigma_M"], e4["blind|nsigma_M"]
    check("Data-only margin policy right answers, E3 | E4", f"{b3['right']} of 111 | {b4['right']} of 88",
          "74 of 111 | 34 of 88", Q)
    check("Data-only margin policy wrong localizations, E3 | E4", f"{b3['wrong_loc']} | {b4['wrong_loc']}", "0 | 3",
          Q)
    check("Layered (oracle) margin policy right answers, E3 | E4", f"{m3['right']} | {m4['right']}", "84 | 45", Q)
    check("E3 right answers, oracle coverage, split 60 s before the estimated onset instead of at the event",
          f"from {m3['right']} to {e3['oracle_cov_onset60|nsigma_M']['right']}", "from 84 to 88", Q)
    check("E4 delayed services n-sigma names at onset - 60 s (of those it names at the event time)",
          f"{r4['nsigma_onset60']} of {r4['nsigma_event']}", "27 of 29", Q)

    # ---------------------------------------------------------------- abstract and threats
    check("Live labelled windows E3 + E4", len(sc) + int(frames["e4"][0].truth.isin(["NI", "IE", "UNR", "LOC"]).sum()),
          199, "data/e3, data/e4 (no longer printed)", printed=False)
    lab4 = read_csv("e4", "labels.csv")
    unr = pd.concat([lab3[lab3.label == "UNR"], lab4[lab4.label == "UNR"]])
    check("Unresolved surges (E3 + E4); from Online Boutique and Sock Shop",
          f"{len(unr)}; {int(unr.system.isin(['boutique', 'sock-shop']).sum())}", "31; 29", "Sec. IV")
    check("Unresolved surges, E3 | E4",
          f"{int((lab3.label == 'UNR').sum())} | {int((lab4.label == 'UNR').sum())}", "22 | 9", "Sec. IV")
    check("Certified healthy windows E1 | E3 | E4",
          f"{int(read_csv('e1', 'certified_windows.csv').certified.sum())} | {int((lab3.label == 'NI').sum())} | "
          f"{int((lab4.label == 'NI').sum())}", "88 | 41 | 23", "Sec. IV")
    return write_checks("fig5")

def _neighbours(live4):
    graph = read_json("e4", "call_path_neighbours.json")["targets"]
    loc = live4[live4.truth == "LOC"]
    w = loc[loc.nsigma_event_top1_service != loc.target]
    near = sum(r.nsigma_event_top1_service in set(graph[r.system][r.target]["callers"]) |
               set(graph[r.system][r.target]["callees"]) for r in w.itertuples())
    return f"{near} of {len(w)}"


def _same_tables(mine, stored):
    keys = ("detection", "onset_error_s", "ranker_top1_on_LOC", "stale_live", "policies_live", "loss_patterns")
    a = json.loads(json.dumps({k: mine[k] for k in keys}, default=float))
    b = {k: stored[k] for k in keys}
    return a == b


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
