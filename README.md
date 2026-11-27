# No Fault Still a Suspect

Code and data for the paper "No Fault Still a Suspect: A Four-Outcome Evaluation of Metric Root Cause Analysis in
Microservices" by Shobhit Gupta and Suchi Kumari (Shiv Nadar Institution of Eminence).
**Status: accepted at ICOIN 2027 (IEEE).**

Paper PDF checked against this release: six pages, SHA-256
`87AC4E112D90442CCFA0FF36AC2A89AA68D4080BD509565A43DBD395A208CE78`.

## What the paper does

Metric root cause analysis (RCA) rankers always name a suspect service, even when there is no fault, when data
are missing, or when no single service is at fault. The paper scores unchanged rankers on four outcomes
(No-Incident, Insufficient-Evidence, Unresolved, Localized) with oracle labels that no ranker sees, adds decline
rules ("gates") to them, and measures what declining costs on live deployments and on the public RCAEval benchmark.

## Install

Python 3.10 to 3.12 (checked on 3.12) and the pinned packages:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
```

## Quick test

```bash
python -m unittest discover -s tests -v          # 14 tests, under a minute
```

Unit tests of the gates, calibration, staleness check, onset scan, copies and scoring, plus checks that the
schedule generator gives both locked schedules, that the labels follow from the certificate records, that the
frozen thresholds are byte-identical to the files hashed in the locked protocols, and that one exported window
gives exactly its stored features.

## Reproduce the paper

```bash
python reproduce/reproduce_all.py                # about 10 s
```

This recomputes every number of the table below from `data/`, checks 112 values printed in the paper and 26
values against the stored records (including all Fig. 4 bar heights, of which only two have printed labels),
redraws Figs. 3 to 6 into `outputs/`, writes
`outputs/REPRODUCTION.md` and exits non-zero on any mismatch. The figures are drawn with matplotlib from the same
numbers (the paper's figures use pgfplots).

Two longer re-runs start from the exported telemetry windows instead of the stored per-window results:

```bash
python reproduce/rerun_from_windows.py --workers 2 --executor thread # 240 windows and 716 copies
python reproduce/rerun_controlled_test.py        # RQ1 controlled test from its 32 windows, about 6 min
```

The first re-run takes about 5 min with 6 process workers; two workers take longer.
The command above uses two in-process threads, avoiding inter-process semaphore-handle errors on Windows.
Use `--executor process` (the default) for separate worker processes. Both modes compute and check the same
features and policy results. The controlled test runs sequentially.

## Paper items and scripts

| Research question (Sec.) | Experiment and data | Finding | Script (in `reproduce/`) |
|---|---|---|---|
| Setup (Table I, Sec. II) | E1 to E4: windows, cases, slots, faults and copies | | `table1.py` |
| RQ1. Do rankers ever decline? (III-A) | E1: 129 screened, 88 certified windows. E2: 218 RCAEval segments. Controlled test on 32 windows | No ranker declined on 645 live and 910 benchmark calls. A zero reference IQR, replaced by one, makes BARO's score depend on units (380 of 384) | `rq1.py`, `rerun_controlled_test.py` |
| RQ2. What does declining cost? (III-B) | E1: 88 certified, 150 faulty windows (Fig. 3). E2: 90 RCAEval code faults (Fig. 4) | Declining costs correct answers, and frozen thresholds did not reliably transfer (4 of 18 healthy windows accepted; BARO's top-score gate right on 1 of 30 accepted code faults) | `fig3_certified_gates.py`, `fig4_public_gates.py` |
| RQ3. Can the four outcomes be told apart live? (III-C) | E3: 111 windows (CPU hog). E4: 88 windows (network delay) (Fig. 5) | D separates quiet windows from incidents. For n-sigma, M removes every wrong localization only by withholding correct answers (18 of 39, 24 of 29) | `fig5_live_policies.py` |
| RQ4. What changes without oracle inputs? (III-D) | E3 and E4 without oracles, 716 missing-data copies (Figs. 5 and 6) | Data-only rules flag all 716 copies, but also 21 of 86 intact E3 quiet and fault windows. Rankers silently lose a service whose evidence stops | `fig5_live_policies.py`, `fig6_missing_data.py`, `rerun_from_windows.py` |

Each script prints every value next to the value in the paper (or, for consistency checks, the stored value) and
writes `outputs/checks_<script>.csv`.

## Layout

```
fouroutcome/      the method as a Python package: rankers (Eq. 1), evidence (Eq. 2), gates and policies
                  (Table II), calibration, data-only rules, missing-data copies, labels, measures
experiments/
  live/           E1, E3, E4 on Kubernetes: faults, probe, exporter, certificate, four-outcome runner
  rcaeval/        E2: download the pinned RCAEval data, rank, summarize the gates
  rq1/            RQ1 audits: rank emission, entry points, change-point detector, zero IQR, controlled test
reproduce/        the scripts above
data/             per-window and per-call results, labels, locked protocols, thresholds, exported windows
tests/            quick test
```

## What needs a download or a live cluster

* **Offline, from `data/`:** everything above.
* **The public RCAEval data (download):** re-ranking the RCAEval cases (`experiments/rcaeval/`) and the RQ1 audits
  on RCAEval segments (`experiments/rq1/`). The audits that call RCAEval itself need `requirements-rcaeval.txt`
  (Python 3.10, RCAEval 1.6.0).
* **A live cluster:** fault injection, the probe, the exporter, the certificate and the labels of E1, E3 and E4
  (`experiments/live/README.md`). Their per-window outputs are stored in `data/`. The E1 exported windows (about
  155 MB) are not included; the E1 numbers come from the stored per-call records.

## Prospective and post hoc

* The E1 certificate rule, the E2 protocol, and the E3 (7 Oct 2026) and E4 (8 Oct 2026) designs were hashed with
  their analysis code before use (`data/e3|e4/protocol.json`; the tests check the hashed thresholds and
  calibration). A host sleep paused E3 after slot 15, before any analysis; the remaining slots ran the next
  morning under an addendum locked before they started.
* Not locked in advance: the controlled test (380 of 384) and four of the five kinds of E3 copies (late,
  intermittent, mesh-only, other).
* The data-only rules were designed on E3, so only their E4 results are prospective; E4's data-only thresholds
  (`data/data_only/thresholds_blind.json`) were frozen before E4. Every data-only E3 number is post hoc.
* Also post hoc: the unit-rescaling check (21 of 90), the E3 oracle V, D row of Fig. 5, the E3 series-by-series
  coverage audit, and the caller or callee classification of E4's wrong answers
  (`data/e4/call_path_neighbours.json`, from the applications' public architectures).

The E3 addendum, the fired-event logs and the calibration records behind the frozen thresholds are not needed to
reproduce any number; they are available from the authors on request.

## Known deviation

The "other" kind of missing-data copy was meant to stop another service's data. In the runs, the generator froze
only the CPU columns of a randomly drawn service, and its pool also held the faulty service's own CPU columns,
drawn in 1 of 45 E3 and 4 of 47 E4 "other" copies, as Sec. II-E of the paper states. That E3 copy is the one fault
where n-sigma stops naming the faulty service (38 instead of 39 of 45 in Fig. 6).
`fouroutcome.copies.make_copies(legacy_other=True)` (default) reproduces the stored copies exactly;
`legacy_other=False` freezes every column of a different service.

## Data and licences

`data/README.md` describes every file. Code: MIT (`LICENSE`). Data: CC BY 4.0 (`DATA_LICENSE`); they are the
authors' own measurements and results, including 240 exported E3/E4 windows and the 32 windows of the controlled
test. The RCAEval benchmark telemetry (MIT) is not redistributed: `experiments/rcaeval/README.md` explains how to
download the exact revision used (Hugging Face `phamquiluan/RCAEval`, revision `afeacb11`); `data/e2/` holds only
our per-call results on it. Third-party code excerpts: `THIRD_PARTY_NOTICES.md`.

## Citation

If you use this code or data, please cite the paper (see also `CITATION.cff`):

> Shobhit Gupta and Suchi Kumari. "No Fault Still a Suspect: A Four-Outcome Evaluation of Metric Root Cause
> Analysis in Microservices." In *2027 International Conference on Information Networking (ICOIN)*, Nha Trang,
> Vietnam, January 2027. IEEE.

```bibtex
@inproceedings{gupta2027nofault,
  author    = {Shobhit Gupta and Suchi Kumari},
  title     = {No Fault Still a Suspect: A Four-Outcome Evaluation of Metric Root Cause Analysis in Microservices},
  booktitle = {2027 International Conference on Information Networking (ICOIN)},
  address   = {Nha Trang, Vietnam},
  month     = jan,
  year      = {2027},
  publisher = {IEEE}
}
```