"""Quick check: unit tests of the method and four consistency tests against the stored data.

    python -m unittest discover -s tests -v        (about 15 s)
"""
import json
import os
import sys
import unittest

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "experiments", "live"))

from fouroutcome.calibration import leave_one_out_thresholds, threshold_at_acceptance  # noqa: E402
from fouroutcome.copies import lose  # noqa: E402
from fouroutcome.dataonly import scan, stale_score, window_features  # noqa: E402
from fouroutcome.evidence import robust_support  # noqa: E402
from fouroutcome.labels import label_records, probe_limit  # noqa: E402
from fouroutcome.measures import auroc, policy_metrics  # noqa: E402
from fouroutcome.policy import decide, score_outcomes  # noqa: E402
from fouroutcome.rankers import column_scores, score_window  # noqa: E402

DATA = os.path.join(REPO, "data")


def synthetic_window(step_service="b", step_at=300, n=121, seed=0):
    """Exported-format window: services a, b, c on a 5-s grid; one CPU step at step_at."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 5.0
    cols = {"time": t}
    for s in ("a", "b", "c"):
        cpu = 0.1 + 0.01 * rng.standard_normal(n)
        if s == step_service:
            cpu = cpu + np.where(t >= step_at, 0.8, 0.0)
        cols[f"{s}_cpu_usage_seconds"] = cpu
        cols[f"{s}_memory_usage_bytes"] = 1e8 + 1e5 * rng.standard_normal(n)
        cols[f"{s}_latency_p90"] = 10 + rng.standard_normal(n) + (np.where(t >= step_at, 30.0, 0.0) if s == step_service else 0)
        cols[f"{s}_istio_requests"] = 5 + 0.2 * rng.standard_normal(n)
        cols[f"{s}_istio_errors"] = np.zeros(n)
    return pd.DataFrame(cols)


class Method(unittest.TestCase):
    def test_threshold_at_acceptance(self):
        scores = np.arange(100, dtype=float)
        tau = threshold_at_acceptance(scores, 0.05)
        self.assertLessEqual(np.mean(scores >= tau), 0.05)
        self.assertGreater(np.mean(scores >= np.nextafter(tau, -np.inf) - 1), 0.05)
        ties = [1.0, 1.0, 2.0, 3.0]
        self.assertLessEqual(np.mean(np.asarray(ties) >= threshold_at_acceptance(ties, 0.25)), 0.25)

    def test_leave_one_out(self):
        f = pd.DataFrame({"system": ["x"] * 20 + ["y"] * 20, "s": list(range(20)) + list(range(100, 120))})
        th = leave_one_out_thresholds(f, "s", targets=(0.05,))
        self.assertGreater(th["x"]["0.05"], 100)  # set on y only
        self.assertLess(th["y"]["0.05"], 20)      # set on x only

    def test_support(self):
        z, reason = robust_support([1, 1, 1, 1, 1, 2, 2, 2], 5)
        self.assertEqual(reason, "")
        self.assertGreater(z, 0)
        z, reason = robust_support([1, 1, np.nan, 1, 1, 2, 2, 2], 5)
        self.assertTrue(np.isnan(z) and reason == "nonfinite_nominee_signal")

    def test_measures(self):
        m = policy_metrics([1, 0, 1, 0], [True, True, False, False])
        self.assertEqual((m["coverage"], m["selective_top1"], m["correct_diagnosis_yield"]), (0.5, 0.5, 0.25))
        self.assertEqual(auroc([2, 3], [1, 1]), 1.0)

    def test_rankers_name_the_stepped_service(self):
        w = synthetic_window("b")
        for method in ("baro", "nsigma"):
            r = score_window(w, "toy", 300.0, method, truth={"b"})
            self.assertTrue(r["ranked"] and r["score_valid"])
            self.assertEqual(r["top1_service"], "b")
            self.assertTrue(0 <= r["service_margin"] <= 1)
            self.assertEqual(r["hit"], 1.0)

    def test_zero_iqr_gives_raw_units(self):
        w = synthetic_window("b")
        w["c_memory_usage_bytes"] = 1e8
        w.loc[w.time >= 300, "c_memory_usage_bytes"] = 1e8 + 5e6 + 1e4 * np.arange((w.time >= 300).sum())
        w.loc[w.time == 0, "c_memory_usage_bytes"] = 1e8 + 1.0   # not constant, but zero IQR
        scores = dict(column_scores(load(w), 300.0, "baro"))
        self.assertGreater(scores["c_mem"], 4.0)                   # MB deviation, not a z-score

    def test_staleness_and_copies(self):
        w = synthetic_window("b")
        self.assertLess(stale_score(load(w))[0], 30)
        for kind in ("full", "late", "intermittent", "family", "other"):
            copy, cols = lose(w, "b", kind)
            self.assertTrue(cols)
        full, _ = lose(w, "b", "full")
        self.assertGreaterEqual(stale_score(load(full))[0], 300)

    def test_scan_finds_onset_after_event(self):
        sc = scan(load(synthetic_window("b", step_at=300)))
        self.assertTrue(np.isfinite(sc["D_scan"]))
        self.assertTrue(250 <= sc["onset"] <= 360)

    def test_decide_and_score(self):
        th = {"stale": {"x": {"0.05": 60.0}}, "D_scan": {"x": {"0.05": 5.0}},
              "gates_onset60": {"nsigma": {"M": {"x": {"0.05": 0.2}}}}}
        base = {"system": "x", "stale": 0.0, "D_scan": 10.0, "nsigma_onset60_ranked": True,
                "nsigma_onset60_score_valid": True, "nsigma_onset60_top1_service": "b"}
        f = pd.DataFrame([{**base, "nsigma_onset60_service_margin": 0.5, "truth": "LOC", "target": "b"},
                          {**base, "nsigma_onset60_service_margin": 0.1, "truth": "UNR", "target": ""},
                          {**base, "D_scan": 1.0, "nsigma_onset60_service_margin": 0.9, "truth": "NI", "target": ""},
                          {**base, "stale": 90.0, "nsigma_onset60_service_margin": 0.9, "truth": "IE", "target": "b"}])
        out = decide(f, th, "nsigma", "M", "0.05", split="onset60")
        self.assertEqual(out, ["LOC", "UNR", "NI", "IE"])
        s = score_outcomes(f, out, "nsigma", "onset60")
        self.assertEqual((s["right"], s["wrong_loc"], s["loc_kept"]), (4, 0, 1))

    def test_probe_limit(self):
        self.assertAlmostEqual(probe_limit(0.05), 0.30)
        self.assertAlmostEqual(probe_limit(0.5), 1.5)


def load(frame):
    from fouroutcome.window import load_window
    return load_window(frame)


class StoredData(unittest.TestCase):
    def test_thresholds_are_the_locked_files(self):
        import hashlib

        def sha(*p):
            with open(os.path.join(DATA, *p), "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        with open(os.path.join(DATA, "e3", "protocol.json")) as f:
            p3 = json.load(f)
        with open(os.path.join(DATA, "e4", "protocol.json")) as f:
            p4 = json.load(f)
        self.assertEqual(sha("e3", "thresholds.json"), p3["thresholds_sha256"])
        self.assertEqual(sha("e3", "calibration.json"), p3["calibration_sha256"])
        self.assertEqual(sha("e4", "thresholds.json"), p4["thresholds_sha256"]["thresholds.json"])
        self.assertEqual(sha("data_only", "thresholds_blind.json"), p4["thresholds_sha256"]["thresholds_blind.json"])
        self.assertEqual(sha("e4", "calibration.json"), p4["calibration_sha256"])

    def test_labels_from_certificate_records(self):
        for arm in ("e3", "e4"):
            with open(os.path.join(DATA, arm, "records.jsonl")) as f:
                recs = [json.loads(ln) for ln in f if ln.strip()]
            mine = label_records(recs).set_index("case_id").label
            stored = pd.read_csv(os.path.join(DATA, arm, "labels.csv")).set_index("case_id").label
            self.assertTrue((mine.loc[stored.index] == stored).all(), arm)

    def test_schedule_matches_locked_protocol(self):
        import four_outcome
        for arm in ("e3", "e4"):
            with open(os.path.join(DATA, arm, "protocol.json")) as f:
                p = json.load(f)
            rows = four_outcome.schedule(p["t_start"], p["slots"], p["seed"],
                                         ["boutique", "deathstarbench", "otel-demo", "sock-shop"],
                                         p["fault"]["targets"], arm)
            keys = ("slot", "class", "system", "case_id", "target", "event")
            self.assertEqual([tuple(r[k] for k in keys) for r in rows],
                             [tuple(r[k] for k in keys) for r in p["schedule"]], arm)

    def test_one_window_reproduces_stored_features(self):
        lf = pd.read_csv(os.path.join(DATA, "e4", "live_features.csv"), float_precision="round_trip")
        r = lf[lf.case_id == "sock-shop_r7_s01_LOC"].iloc[0]
        path = os.path.join(DATA, "windows", "e4", r.system, f"{r.case_id}.csv.gz")
        f = window_features(path, r.system, ("nsigma", "baro"), (("event", 300.0),))
        for k, v in f.items():
            s = r[k]
            if isinstance(v, (bool, np.bool_)) or isinstance(s, (bool, np.bool_)):
                self.assertEqual(str(v).lower(), str(s).lower(), k)
            elif isinstance(v, str):
                self.assertEqual(v, "" if pd.isna(s) else s, k)
            else:
                self.assertTrue(np.isclose(float(v), float(s), rtol=1e-12, atol=0, equal_nan=True), k)


if __name__ == "__main__":
    unittest.main()
