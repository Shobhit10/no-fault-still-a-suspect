# Live experiment harness (E1, E3, E4)

These scripts ran the paper's live experiments on Kubernetes. They need a cluster and cannot be
re-run offline; `data/` holds every per-window record they produced, and `reproduce/` recomputes the
paper's numbers from it. Use them to repeat the experiments on other deployments or applications.

## Requirements

* A Kubernetes cluster with the applications under study in their own namespaces and an Istio
  service mesh (sidecar injection) in front of them. The paper used five open-source applications
  (Online Boutique 0.10.6, Sock Shop, OpenTelemetry Demo 3.0.0 / Helm chart 0.41.0, DeathStarBench
  hotel reservation, Train Ticket), each with its own load generator, on one shared cluster (ten
  4-vCPU / 16-GiB nodes; tested on a managed Kubernetes 1.35 service).
* Prometheus (kube-prometheus) scraping cAdvisor every 15 s and Istio metrics every 5 s, plus
  kube-state-metrics, reachable at `PROM_URL` (e.g. `kubectl -n monitoring port-forward
  svc/<prometheus-service> 9090:9090`, then `PROM_URL=http://localhost:9090`).
* `kubectl` (the current context, or `KUBE_CONTEXT=<context>`), `bash`, `flock`, Python 3.10+ with
  `requirements.txt`.
* Copy `config.example.json` to `config.json` and set namespaces, services, container names, load
  generator deployments, fault targets and surge factors for your deployments.

Nothing in this folder contains credentials or cluster names; everything cluster-specific is a
parameter, an environment variable or an entry of `config.json`.

## One-time preparation

```bash
bash faults/apply_limits.sh <namespace>            # same CPU / memory limits on every target (E1)
bash faults/add_fault_volume.sh <namespace>        # memory-backed /faultmem for memory faults
bash faults/setup_debug_pods.sh <namespace>        # node debug pods for tc netem (E4)
kubectl create namespace rca-probe                 # no sidecar injection in this namespace
kubectl apply -f probe/health_probe.yaml
```

The probe sends one request per second to three user-facing endpoints per application from outside
the mesh. For DeathStarBench the third endpoint is the `/user` login check with `Cornell_0`, one of
the application's built-in demo users.

## E1 faulty, screened and certified windows

```bash
# 30 fault cases per deployment: CPU exhaustion on one service, memory pressure on another, 15 s later
GT_FILE=gt/ground_truth_boutique.csv DURATION=300 bash faults/concurrent_faults.sh \
    boutique adservice cpu cartservice mem 15 boutique_cm_p1_r1
python export_window.py --config config.json --system boutique --ground-truth gt/ground_truth_boutique.csv --out-dir data_boutique

# candidate windows without a fault (>= 300 s before / 600 s after any injection, >= 900 s apart), then screening
python export_window.py --config config.json --system boutique --ground-truth gt_clean/boutique.csv --out-dir data_boutique_clean
python screen_windows.py --config config.json --system boutique --windows-dir data_boutique_clean \
    --ground-truth gt_clean/boutique.csv --out screened_boutique.csv

# certified healthy windows: calibrate, lock (hash schedule, rule, calibration and code), collect, certify
python certificate.py --config config.json --out runs/e1 --ground-truth-glob 'gt/*.csv' calibrate --start S --end E
python certificate.py --config config.json --out runs/e1 lock --t-start T --per-system 24
python certificate.py --config config.json --out runs/e1 --ground-truth-glob 'gt/*.csv' collect   # repeat until done
python certificate.py --config config.json --out runs/e1 certify

# one ranker call per window with every gate score (data/e1/calls.csv format)
python score_windows.py --index windows.csv --out calls.csv --methods baro,nsigma,dummy,granger_randomwalk,lingam_randomwalk
```

The leave-one-deployment-out thresholds and the counts of Fig. 3 are then computed as in
`reproduce/fig3_certified_gates.py`.

## E3 and E4 four-outcome tests

1. Freeze the thresholds before the test, on windows of the *other* deployments only
   (`fouroutcome.calibration.leave_one_out_thresholds`; the paper used the certified E1 windows) and
   put them in the run folder as `thresholds.json` (layered policy) and `thresholds_blind.json`
   (data-only policy). Run pilots on the probe only to choose fault strength and surge factors, and
   never score them.
2. ```bash
   python four_outcome.py --arm e3 --config config.json --out runs/e3 calibrate --start S --end E
   python four_outcome.py --arm e3 --config config.json --out runs/e3 lock --t-start T
   bash run_schedule.sh runs/e3 config.json        # fires every slot, collects and labels
   ```
   `--arm e4` runs the network-delay design. The lock refuses to overwrite itself, and `collect` and
   `label` refuse to run if any hashed file changed. A slot that cannot be fired within 60 s of its
   locked time is recorded as not fired, never moved.
3. Copies and features (offline):
   ```python
   from fouroutcome.copies import make_copies
   from fouroutcome.dataonly import window_features
   from fouroutcome.policy import evaluate, load_thresholds
   ```
   exactly as `reproduce/rerun_from_windows.py` does for the paper's windows.

| Script | Purpose |
|---|---|
| `faults/fault_lib.sh` | Shared, self-limiting fault delivery (CPU, memory, netem delay/loss, pod kill, disk I/O). |
| `faults/cpu_hog.sh` | E3 fault: CPU_LOOPS busy loops (128 in the paper) for 300 s. |
| `faults/net_delay.sh` | E4 fault: 150 +- 50 ms netem delay for 300 s, read back before it counts as fired. |
| `faults/load_surge.sh` | Surge: scale the load generator by SURGE_FACTOR (8 to 24 in the paper) for 300 s. |
| `faults/concurrent_faults.sh` | E1 fault pair with a stagger. |
| `faults/apply_limits.sh`, `faults/add_fault_volume.sh`, `faults/setup_debug_pods.sh` | Preparation. |
| `probe/health_probe.yaml` | Out-of-mesh user-facing probe. |
| `export_window.py` | Prometheus -> 5-s window CSV. |
| `screen_windows.py` | E1 screening (dead windows, container restarts). |
| `certificate.py` | Health certificate E1-E6: calibrate, lock, collect, certify. |
| `four_outcome.py` | E3/E4: schedule, lock, collect, label. |
| `run_schedule.sh` | E3/E4 driver. |
| `score_windows.py` | Ranker calls with every gate score on exported windows. |

`screen_windows.py` re-implements the screening rule from its description (the original audit used
the same restart counter); everything else follows the scripts that ran the experiments, with
cluster-specific values turned into parameters.
