"""Table I (roadmap) and the setup of Sec. II: windows, cases, slots, faults and missing-data copies."""
import glob
import os

from _common import check, data, read_csv, read_json, write_checks


def main():
    print("Table I and Sec. II")
    # E1: candidate, screened, faulty and certified windows
    w = read_csv("e1", "screened_windows.csv")
    scr = (~w.dead_raw.astype(bool)) & w.restart_audit_present.astype(bool) & w.n_restarts.eq(0)
    check("E1 screened windows of the candidates (not dead, restart audit present, no restart)",
          f"{int(scr.sum())} of {len(w)}", "129 of 145", "Table I, Sec. II-C")
    check("E1 screening flag stored with the windows agrees", bool((scr == w.screened.astype(bool)).all()), True,
          "data/e1", printed=False)
    check("E1 screened-window calls (five rankers)",
          int(read_csv("e1", "screened_window_calls.csv").merge(
              w[scr][["system", "case_id"]].assign(window=lambda x: x.case_id + ".csv"),
              on=["system", "window"]).shape[0]), 645, "Abstract, Sec. II-C")
    logs = {os.path.basename(p): sum(1 for ln in open(p) if ln.strip() and ",end_time," not in ln)
            for p in glob.glob(data("e1", "injection_logs", "faulty_*.csv"))}
    check("E1 injected cases per deployment in the logs, then the DeathStarBench re-run after the repair",
          [logs[f"faulty_{s}.csv"] for s in ("boutique", "deathstarbench", "otel-demo", "sock-shop", "train-ticket")]
          + [logs["faulty_deathstarbench_rerun.csv"]], [30, 30, 30, 30, 30, 30], "Secs. II-E, III-A")
    calls = read_csv("e1", "calls.csv")
    faulty = calls[calls.set.isin(["faulty", "faulty_dsb_matched"]) & (calls.method == "baro")]
    check("E1 faulty windows", len(faulty), 150, "Table I, Sec. III-A")
    check("E1 faulty windows per deployment", sorted(faulty.groupby("system").size().unique().tolist()), [30],
          "Sec. II-E")
    cert = read_csv("e1", "certified_windows.csv")
    check("E1 scheduled windows per deployment", sorted(cert.groupby("system").size().unique().tolist()), [24],
          "Sec. II-D")
    check("E1 certified healthy windows of the scheduled windows", f"{int(cert.certified.sum())} of {len(cert)}",
          "88 of 120", "Table I, Sec. II-D")

    # E2: RCAEval cases and pre-injection segments
    r1 = read_csv("e2", "calls_re1.csv")
    r23 = read_csv("e2", "calls_re2_re3.csv")
    check("E2 RCAEval faults (RE1 + RE2 + RE3)", r1.case.nunique() + r23.case.nunique(), 735, "Sec. II-C")
    check("E2 RE3 code faults", r23[r23.suite == "RE3"].case.nunique(), 90, "Table I, Sec. III-B")
    pre = read_csv("e2", "re2_preinjection_calls.csv")
    seg = pre.groupby("dataset").case.nunique().to_dict()
    check("E2 RE2 pre-injection segments", sum(seg.values()), 218, "Table I, Sec. II-C")
    check("E2 segments per system (OB, SS, TT)", [seg["RE2-OB"], seg["RE2-SS"], seg["RE2-TT"]], [38, 90, 90],
          "Sec. II-C")
    check("E2 calls on pre-injection segments", len(pre), 910, "Abstract, Sec. II-C")

    # E3 and E4: slots, labelled windows, copies
    copies = 0
    for arm, slots, labelled, name in (("e3", [34, 12, 12, 10], 111, "E3"), ("e4", [26, 8, 12, 6], 88, "E4")):
        p = read_json(arm, "protocol.json")
        s = [p["slots"]["NI"], p["slots"]["LOC"], p["slots"]["UNR"]]
        check(f"{name} slots: all, quiet, fault, surge", [sum(s)] + s, slots, "Sec. II-E")
        check(f"{name} deployments", len({r["system"] for r in p["schedule"]}), 4, "Sec. II-E")
        lab = read_csv(arm, "labels.csv")
        check(f"{name} labelled windows", int(lab.label.isin(["NI", "LOC", "UNR", "IE_natural"]).sum()), labelled,
              "Table I, Sec. III-C")
        copies += len(read_csv(arm, "copy_features.csv"))
    check("Missing-data copies, E3 + E4", copies, 716, "Table I, Sec. III-D")
    check("E3 fault: CPU busy loops", read_json("e3", "protocol.json")["fault"]["cpu_loops"], 128, "Sec. II-E")
    f4 = read_json("e4", "protocol.json")["fault"]
    check("E4 delay (ms, +- ms)", [f4["delay_ms"], f4["jitter_ms"]], [150, 50], "Sec. II-E")
    fac = read_json("e3", "protocol.json")["surge"]["factor"]
    check("Surge factor range", [min(fac.values()), max(fac.values())], [8, 24], "Sec. II-E")
    check("Slot spacing (minutes)", read_json("e3", "protocol.json")["spacing_s"] // 60, 21, "Sec. II-E")
    return write_checks("table1")


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)