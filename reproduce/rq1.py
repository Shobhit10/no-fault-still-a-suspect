"""RQ1 (Sec. III-A): do rankers ever decline, and why do some keep naming the same service?"""
import numpy as np

from _common import check, every, pct, read_csv, write_checks

S = "Sec. III-A"


def main():
    print("RQ1")
    # rank emission on the 129 screened windows (E1) and the 218 RE2 pre-injection segments (E2)
    w = read_csv("e1", "screened_windows.csv")
    scr = w[w.screened].assign(window=lambda x: x.case_id + ".csv")[["system", "window"]]
    calls = read_csv("e1", "screened_window_calls.csv").merge(scr, on=["system", "window"])
    ranked = calls.ok & calls.top1.fillna("").astype(str).str.len().gt(0)
    check("E1 calls on screened windows that returned a ranking", f"{int(ranked.sum())} of {len(calls)}",
          "645 of 645", "Abstract, " + S)
    pre = read_csv("e2", "re2_preinjection_calls.csv")
    pre_ranked = pre.ok & pre.top1.fillna("").astype(str).str.len().gt(0)
    check("E2 calls on pre-injection segments that returned a ranking", f"{int(pre_ranked.sum())} of {len(pre)}",
          "910 of 910", "Abstract, " + S)
    check("Rank-emission rate (%)", pct(int(ranked.sum()) + int(pre_ranked.sum()), len(calls) + len(pre), 0), 100, S)
    ep = read_csv("rq1", "rcaeval_entry_points.csv")
    entry = ep[ep.role == "entry_point"]
    check("Ranking entry points of RCAEval.e2e", len(entry), 34, S)
    n_field = int(entry.score_like.fillna("").astype(str).str.len().gt(0).sum())
    check("Entry points returning a support, confidence or rejection field", "none" if n_field == 0 else n_field,
          "none", S)

    # certified healthy windows: all five methods rank all 88
    c = read_csv("e1", "calls.csv")
    cert = c[c.set == "certified"]
    check("Certified windows ranked by all five methods", int(cert.groupby("case_id").api_ranked.all().sum()), 88, S)
    check("Calls on certified windows that returned a ranking", int(cert.api_ranked.sum()), 440, "data/e1",
          printed=False)

    # BARO's own change-point detector fires on every screened window and valid pre-injection segment
    cpd = read_csv("e1", "baro_changepoint_screened.csv")
    h = cpd[cpd.kind == "healthy"].merge(scr.rename(columns={"window": "case"}), on=["system", "case"])
    check(f"BARO's change-point detector fires on the {len(h)} screened windows", every(int(h.fired.sum()), len(h)),
          "every", S)
    r2 = read_csv("e2", "baro_changepoint_re2.csv")
    valid = r2[(r2.segment == "pre_injection") & r2.segment_eligible]
    check(f"... and on the {len(valid)} valid RE2 pre-injection segments",
          every(int(valid.detector_fired.sum()), len(valid)), "every", S)

    # faulty E1 windows (top-1 naming an injected service)
    ft = read_csv("e1", "faulty_top1_campaign.csv")
    pooled = ft[ft.scope == "pooled"].set_index("method").correct
    check("Faulty E1 windows named by BARO, n-sigma, random ordering",
          [int(pooled["baro"]), int(pooled["nsigma"]), int(pooled["dummy"])], [143, 141, 29], S)
    fa = c[c.set.isin(["faulty", "faulty_dsb_matched"])]
    hits = fa.groupby("method").hit.sum()
    check("... by BARO and n-sigma once the DeathStarBench faults were rerun", [int(hits["baro"]), int(hits["nsigma"])],
          [147, 142], S)

    # zero reference IQR on RE2-OB (BARO, no-fault segments)
    m = read_csv("rq1", "winning_column_scale.csv")
    ob = m[(m.corpus == "re2ob") & (m.kind == "healthy") & (m.method == "baro") & m.base_top1.notna()]
    check("RE2-OB: BARO's named services resting on a zero IQR (%)", pct((ob.why == "scale").sum(), len(ob)), 94.7, S)
    conc = ob.base_svc.value_counts().iloc[0] / len(ob)
    check("RE2-OB: BARO's concentration (%)", round(100 * conc, 1), 94.7, S)

    # controlled scale test: BARO gives the same rank with and without a near-zero SD
    t = read_csv("rq1", "controlled_scale_test.csv")
    b = t[t.method == "baro"].pivot_table(index=["window", "target", "k_sigma"], columns="condition",
                                          values="new_rank")
    check("Controlled test: windows, systems", [t.window.nunique(), t.system.nunique()], [32, 4], S)
    same = int(np.isclose(b["iqr_only"], b["both"]).sum())
    check("Controlled test: BARO gives the zero-IQR column the same rank with or without a near-zero SD",
          f"{same} of {len(b)}", "380 of 384", S)
    return write_checks("rq1")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)