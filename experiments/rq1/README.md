# RQ1 audits

| Script | What it measures | Needs | Paper result (stored in `data/`) |
|---|---|---|---|
| `preinjection_emission.py` | Rank emission: do rankers ever decline on windows without an injected fault? | RCAEval 1.6.0 (random and random-walk rankers) | 645 of 645 calls on screened windows and 910 of 910 on RE2 pre-injection segments returned a ranking (`e1/screened_window_calls.csv`, `e2/re2_preinjection_calls.csv`) |
| `rcaeval_entry_points.py` | Do any of RCAEval's ranking entry points return a support, confidence or rejection field? | RCAEval 1.6.0 | 34 entry points, none (`rq1/rcaeval_entry_points.csv`) |
| `baro_changepoint.py` | Does BARO's own change-point detector filter out healthy input? | BARO (`fse-baro`) | fires on every screened window and every valid pre-injection segment (`e1/baro_changepoint_screened.csv`, `e2/baro_changepoint_re2.csv`) |
| `winning_column_scale.py` | Why does a ranker keep naming one service: does its winning column have a zero reference scale? | - | RE2-OB, BARO: 94.7% zero IQR, concentration 94.7% (`rq1/winning_column_scale.csv`) |
| `controlled_scale_test.py` | Controlled test of the zero-IQR mechanism (not locked in advance) | - | BARO same rank in 380 of 384 trials (`rq1/controlled_scale_test.csv`); re-run offline with `reproduce/rerun_controlled_test.py` |

Install the optional dependencies with `pip install -r requirements-rcaeval.txt` in a Python 3.10
environment (RCAEval 1.6.0 checks the Python version). The two scripts without extra needs use the
BARO and n-sigma implementation of `fouroutcome.rankers`, which returns the same ranking as RCAEval's.
