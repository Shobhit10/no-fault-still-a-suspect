"""Four-outcome evaluation of metric root cause analysis (RCA) rankers.

Companion code of "No Fault Still a Suspect: A Four-Outcome Evaluation of Metric Root Cause
Analysis in Microservices" (Shobhit Gupta and Suchi Kumari; ICOIN 2027).

Modules
  window       exported windows and the ranker-visible frame
  rankers      BARO and n-sigma (Eq. 1) and one ranker call with every gate score
  evidence     support z (Eq. 2), service margin (Table II), detector D
  calibration  thresholds at a source acceptance target, frozen on other deployments
  dataonly     staleness check, scanned detector and CUSUM onset (the data-only rules)
  copies       missing-data copies (five kinds of loss) for RQ4
  policy       gates V/D/S/T/M, layered and data-only four-outcome policies, R/W/K scoring
  labels       certificate rule constants and the oracle labels (No-Incident, Localized, ...)
  measures     coverage, selective top-1 accuracy, yield, AUROC, exact intervals
"""
from .calibration import leave_one_out_thresholds, threshold_at_acceptance
from .copies import PATTERNS, lose, make_copies
from .dataonly import scan, stale_score, window_features
from .evidence import detector_at, robust_support
from .measures import auroc, policy_metrics
from .policy import decide, evaluate, load_thresholds, score_outcomes
from .rankers import column_scores, rank, score_window
from .window import load_window

__version__ = "1.0.0"
__all__ = ["auroc", "column_scores", "decide", "detector_at", "evaluate", "leave_one_out_thresholds",
           "load_thresholds", "load_window", "lose", "make_copies", "PATTERNS", "policy_metrics",
           "rank", "robust_support", "scan", "score_outcomes", "score_window", "stale_score",
           "threshold_at_acceptance", "window_features"]
