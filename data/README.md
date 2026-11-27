# Data

Everything here was measured or computed by the authors and is licensed under CC BY 4.0 (see
`../DATA_LICENSE`), except that the E2 files contain per-call results computed on the public RCAEval
benchmark (case identifiers and metric names are RCAEval's; RCAEval is MIT-licensed, see
`../THIRD_PARTY_NOTICES.md`). No RCAEval telemetry is redistributed. Total size: 24 MB.

Conventions: one row per window or per ranker call; `system` is one of `boutique` (Online Boutique,
OB), `deathstarbench` (DeathStarBench hotel reservation, DSB), `otel-demo` (OpenTelemetry Demo,
OTel), `sock-shop` (Sock Shop, SS), `train-ticket` (Train Ticket, TT). Times are Unix seconds (UTC)
or seconds from the window start. Booleans are `True`/`False`. Files marked *locked* are outputs of
the original locked or recorded analyses, kept unchanged so that the reproduction scripts can
compare against them; protocol files are kept byte-identical (their SHA-256 values are the ones
hashed before the tests), so file names inside them refer to the authors' original project layout.

## E1 on five live deployments (RQ1, RQ2)

| File | Content |
|---|---|
| `e1/screened_windows.csv` | The 145 candidate windows without an injected fault (nine-day campaign): window start/end, `dead_raw` (every metric constant), `n_restarts` (container restarts in the window, from `kube_pod_container_status_restarts_total`), `screened` (= not dead, restart audit present, no restart; 129). |
| `e1/screened_window_calls.csv` | 725 ranker calls (5 RCAEval rankers x 145 candidates; 645 on the 129 screened windows), split at the midpoint: whether a ranking came back, named column and service, top five. |
| `e1/baro_changepoint_screened.csv` | BARO's own change-point detector (bocpd) on the screened and the faulty windows: `fired`, number of change points. |
| `e1/certified_windows.csv` | The 120 scheduled quiet windows with the certificate verdict (`certified`, 88) and the failed conditions (`reasons`, E1-E6; see `fouroutcome/labels.py`). |
| `e1/calls.csv` | Per-call gate scores, the input of Fig. 3: `set` = `historical` (129 screened windows, threshold source), `certified` (88 certified windows; all five rankers), `faulty` (120 fault windows of OB, OTel, SS, TT), `faulty_dsb_historical` / `faulty_dsb_matched` (DeathStarBench before / after the registry repair), `historical_rw_audit` (random-walk rankers without RCAEval's exception wrapper). Columns: `top1_service`, `hit` (named an injected service), `support` (Eq. 2), `top_service_score` (s1), `service_margin` (Table II), validity flags, `api_ranked`, `fallback` (ranking produced only by the wrapper's exception handler). |
| `e1/gates_locked.csv` | *Locked* output of the certified-window analysis (thresholds and counts per deployment, gate and target). |
| `e1/faulty_top1_campaign.csv` | Top-1 accuracy of the five rankers on the 150 campaign fault windows (143 / 141 / 29). |
| `e1/injection_logs/faulty_<system>.csv` | Injection log of the 30 E1 fault cases per deployment (CPU on one service, memory on another, 15-s stagger) in the layout of `experiments/live/faults/concurrent_faults.sh`; `faulty_deathstarbench_rerun.csv` is the re-run after the repair. |

## E2 on the RCAEval benchmark (RQ1, RQ2)

| File | Content |
|---|---|
| `e2/re2_preinjection_calls.csv` | 910 ranker calls on the 218 RE2 pre-injection segments (600 s ending 120 s before the injection, split at the midpoint). |
| `e2/baro_changepoint_re2.csv` | BARO's change-point detector on the RE2 pre-injection and fault segments. |
| `e2/calls_re2_re3.csv` | Per-call records of the RE2 -> RE3 gate test, 360 cases x 2 segments (pre-injection, labelled) x 2 rankers: named column, `hit`, gate scores (`support`, `top_service_score`, `service_margin`, `detector_score`) and validity. Input of Fig. 4. |
| `e2/calls_re1.csv` | The same for the 375 RE1 cases (thresholds frozen on RE2; used here for the AUROC of detector D). |
| `e2/policies_locked.csv` | *Locked* summary: every gate x rate x dataset policy row. |
| `e2/zero_iqr_nominations.csv` | For every BARO nomination: whether the named column has a zero reference IQR. |
| `e2/unit_rescaling_calls.csv` | Post-hoc unit audit: named service with every disk-I/O column divided by 1,024 (and multiplied). |
| `e2/rcaeval_files_*.sha256.json` | SHA-256 of every RCAEval file used (Hugging Face revision `afeacb11`); `experiments/rcaeval/e2_gates.py prepare` checks downloads against them. |

## RQ1 mechanism

| File | Content |
|---|---|
| `rq1/winning_column_scale.csv` | For each no-fault window or segment and ranker (corpora `own`, `re2ob`, `re2ss`, `re2tt`), the winning column and why it won (`why` = `scale`: zero reference scale; `drift`; `other`). `abl_*` columns: a first-difference ablation not used in the paper. |
| `rq1/controlled_scale_test.csv` | The controlled test: 2,304 trials (32 windows, 4 applications, 2 rankers, 3 columns, 3 conditions, 4 shift sizes) with the column's rank before and after. Not locked in advance. |
| `rq1/controlled_scale_test_windows.csv` | The 32 windows of the controlled test (in `windows/rq1_controlled/`). |
| `rq1/rcaeval_entry_points.csv` | The 34 ranking entry points of `RCAEval.e2e` (RCAEval 1.6.0) and the keys they return. |

## E3 (CPU hog) and E4 (network delay), the live four-outcome tests (RQ3, RQ4)

| File | Content |
|---|---|
| `e3|e4/protocol.json` | The locked design (hashed before the first window): slots, seed, schedule, fault, surge factors, label and impact rules, hashes of the code, calibration and thresholds. |
| `e3|e4/records.jsonl` | Per-window certificate evidence (E1-E6 reasons, raw-coverage gaps, restarts, probe statistics) and user impact over [event + 30 s, event + 300 s]. |
| `e3|e4/labels.csv` | Oracle label of every window (`fouroutcome.labels.label_records` re-derives it from the records): `NI`, `LOC`, `UNR`, `IE_natural` are scored; `uncertified`, `silent`, `not_fired`, `UNR_restart` are reported only. |
| `e3|e4/calibration.json` | Probe and mesh calibration of the test. |
| `e3|e4/thresholds.json` | Frozen thresholds of the layered (oracle) policy: D and the S/T/M gates per deployment and target, set on the certified E1 windows of the other deployments (`gates_probe_matched`; `gates_paper` = screened-window thresholds). |
| `e3|e4/live_features.csv` | Per live window: label, staleness (`stale`), scanned detector (`D_scan`, `onset`), and for each split (`event` = 300 s, `onset`, `onset60` = onset - 60 s) detector D and both rankers' named service and gate scores (`<ranker>_<split>_<field>`). Input of Figs. 5 and 6. |
| `e3|e4/copy_features.csv` | The same for every missing-data copy (`pattern` = full, late, intermittent, family [mesh-only], other; `lost_service`; parent label). |
| `e3/summary_locked.json`, `e4/report_locked.json` | Stored evaluations (E3: post-hoc data-only development run; E4: the one locked analysis run). |
| `e3/series_audit_windows.csv` | Post-hoc series-by-series raw-coverage audit of the 136 E3 windows (`per_series_lifetime` False for 10). |
| `e4/call_path_neighbours.json` | Callers and callees of each delay target (from the applications' public architectures; post hoc), used to classify n-sigma's wrong answers. |
| `data_only/thresholds_blind.json` | Frozen thresholds of the data-only policy (stale, D_scan and the gates at the estimated onset), set on the 88 certified E1 windows of the other deployments before E4. |

## Exported windows

`windows/e3/<system>/<case>.csv.gz` (136) and `windows/e4/<system>/<case>.csv.gz` (104): the
exported telemetry windows of the live tests (600 s on a 5-s grid, 15 metrics per service; see
`experiments/live/export_window.py`). `windows/rq1_controlled/` holds the 32 windows of the
controlled test. `reproduce/rerun_from_windows.py` and `reproduce/rerun_controlled_test.py`
recompute the stored features and trials from them.

Not included (size): the 145 E1 candidate windows (32 of them are in `windows/rq1_controlled/`), the
150 E1 fault windows, the 120 certified-window exports (together about 155 MB uncompressed) and the
probe logs; the per-call and per-window records above are what the paper's E1 numbers are computed
from. The RCAEval telemetry is public (see `experiments/rcaeval`).
