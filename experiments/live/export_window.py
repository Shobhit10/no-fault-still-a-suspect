#!/usr/bin/env python3
"""Export one telemetry window per case from Prometheus onto a 5-s grid.

For each case of a ground-truth file the window spans [start - 90 s, end + 180 s] (570 s for a
quiet window, 585 s for an E1 fault case; E3/E4 cases are written with start = event - 210 s and
end = event + 120 s, so their windows span 300 s on each side of the event). For every service of
the application it queries, at a 5-s step:

  cpu_usage_seconds, memory_usage_bytes, memory_working_set_bytes   (cAdvisor; rates of counters)
  cpu_throttling, fs_writes_bytes                                    (cAdvisor)
  latency_p50/p90/p95/p99, istio_requests, istio_errors              (Istio; 1-min rate windows)
  tcp_received, tcp_sent, tcp_connections, net_pkt_dropped           (Istio, else cAdvisor)

A service/metric with no data is written as zeros so every window has the same rectangular schema;
missing samples inside a series are forward-filled, which is exactly how lost telemetry looks to a
ranker (the staleness check of the data-only policy relies on it). The rankers read five of these
columns (fouroutcome.window.SUFFIX_MAP).

usage:
  export_window.py --config config.json --system boutique --ground-truth gt.csv --out-dir data_boutique
  export_window.py --config config.json --system boutique --case-id c1 --start S --end E --out-dir DIR
env: PROM_URL overrides config["prometheus_url"] (e.g. a kubectl port-forward to localhost:9090).
An existing export is never overwritten unless FORCE_REEXPORT=1: once a window leaves Prometheus
retention a re-export would silently replace real telemetry with constant columns.
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

CONTAINER_METRICS = [
    ("container_cpu_usage_seconds_total", True),
    ("container_memory_usage_bytes", False),
    ("container_memory_working_set_bytes", False),
    ("container_network_transmit_bytes_total", True),
    ("container_network_receive_bytes_total", True),
]
EXPECTED_SUFFIXES = ["cpu_usage_seconds", "memory_usage_bytes", "memory_working_set_bytes", "cpu_throttling",
                     "fs_writes_bytes", "latency_p50", "latency_p90", "latency_p95", "latency_p99",
                     "istio_requests", "istio_errors", "tcp_received", "tcp_sent", "tcp_connections",
                     "net_pkt_dropped"]
PRE, POST = 90, 180


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    cfg["prometheus_url"] = os.environ.get("PROM_URL", cfg.get("prometheus_url", "http://localhost:9090"))
    return cfg


def container_name(system_cfg, service):
    return system_cfg.get("container_overrides", {}).get(service, system_cfg["container"].format(service=service))


def query_range(prom, query, start, end, step="5s"):
    url = prom.rstrip("/") + "/api/v1/query_range?" + urllib.parse.urlencode(
        {"query": query, "start": start, "end": end, "step": step})
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            d = json.load(r)
    except Exception as e:  # a failed query is reported and treated as missing data
        print(f"  QUERY FAILED: {query[:80]}... -- {type(e).__name__}: {e}")
        return None
    res = d.get("data", {}).get("result", [])
    if d.get("status") != "success" or not res:
        return None
    values = res[0]["values"]
    return pd.Series([float(v[1]) for v in values], index=[int(float(v[0]) - start) for v in values])


def export_window(case_id, system_cfg, start_time, end_time, out_dir, prom):
    """Write <out_dir>/<case_id>.csv for the window [start_time - 90, end_time + 180]."""
    ns = system_cfg["namespace"]
    rep = system_cfg.get("istio_reporter", "source")
    s, e = int(start_time) - PRE, int(end_time) + POST
    columns = {}
    for svc in system_cfg["services"]:
        c = container_name(system_cfg, svc)
        pod = f'namespace="{ns}", pod=~"{svc}.*", container="{c}"'
        dst = f'destination_service_name="{svc}", destination_workload_namespace="{ns}"'
        q = lambda query: query_range(prom, query, s, e)  # noqa: E731
        for metric, counter in CONTAINER_METRICS:
            base = f"{metric}{{{pod}}}"
            series = q(f"rate({base}[1m])" if counter else base)
            if series is not None:
                columns[f"{svc}_{metric.replace('container_', '').replace('_total', '')}"] = series
        for name, query in (
                ("cpu_throttling", f"sum(rate(container_cpu_cfs_throttled_periods_total{{{pod}}}[1m]))"),
                ("fs_writes_bytes", f"sum(rate(container_fs_writes_bytes_total{{{pod}}}[1m]))")):
            series = q(query)
            if series is not None:
                columns[f"{svc}_{name}"] = series
        for quant, name in ((0.5, "latency_p50"), (0.9, "latency_p90"), (0.95, "latency_p95"), (0.99, "latency_p99")):
            series = q(f'histogram_quantile({quant}, sum(rate(istio_request_duration_milliseconds_bucket'
                       f'{{{dst}, reporter="{rep}"}}[1m])) by (le))')
            if series is not None:
                columns[f"{svc}_{name}"] = series
        series = q(f'sum(rate(istio_requests_total{{{dst}, reporter="{rep}"}}[1m]))')
        if series is not None:
            columns[f"{svc}_istio_requests"] = series
        # errors = HTTP 5xx or a non-zero gRPC status (gRPC replies carry HTTP 200)
        series = q(f'(sum(rate(istio_requests_total{{{dst}, reporter="{rep}", response_code=~"5.."}}[1m])) or vector(0)) '
                   f'+ (sum(rate(istio_requests_total{{{dst}, reporter="{rep}", grpc_response_status=~"[1-9].*"}}[1m])) or vector(0))')
        if series is not None:
            columns[f"{svc}_istio_errors"] = series
        for tm, cadv, name in (("istio_tcp_received_bytes_total", "container_network_receive_bytes_total", "tcp_received"),
                               ("istio_tcp_sent_bytes_total", "container_network_transmit_bytes_total", "tcp_sent")):
            series = q(f'sum(rate({tm}{{{dst}, reporter="destination"}}[1m]))')
            if series is None or float(abs(series).sum()) == 0.0:
                series = q(f'sum(rate({cadv}{{namespace="{ns}", pod=~"{svc}-.*"}}[1m]))')
            if series is not None:
                columns[f"{svc}_{name}"] = series
        series = q(f'sum(rate(container_network_receive_packets_dropped_total{{namespace="{ns}", pod=~"{svc}-.*"}}[1m])) '
                   f'+ sum(rate(container_network_transmit_packets_dropped_total{{namespace="{ns}", pod=~"{svc}-.*"}}[1m]))')
        if series is not None:
            columns[f"{svc}_net_pkt_dropped"] = series
        series = q(f'sum(istio_tcp_connections_opened_total{{{dst}, reporter="destination"}}) '
                   f'- (sum(istio_tcp_connections_closed_total{{{dst}, reporter="destination"}}) or vector(0))')
        if series is None or float(abs(series).sum()) == 0.0:
            series = q(f'sum(rate(container_network_receive_packets_total{{namespace="{ns}", pod=~"{svc}-.*"}}[1m]))')
        if series is not None:
            columns[f"{svc}_tcp_connections"] = series
    if not columns:
        print(f"WARNING: no data for {case_id}; nothing written")
        return None
    index = sorted(set().union(*[v.index for v in columns.values()]))
    rect = {}
    for svc in system_cfg["services"]:
        for suf in EXPECTED_SUFFIXES:
            v = columns.get(f"{svc}_{suf}")
            rect[f"{svc}_{suf}"] = (pd.Series(0.0, index=index) if v is None
                                    else v.reindex(index).ffill().bfill().fillna(0.0))
    df = pd.DataFrame(rect).sort_index().ffill().bfill()
    df.insert(0, "time", df.index)
    df = df.reset_index(drop=True)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{case_id}.csv")
    df.to_csv(path, index=False)
    print(f"Saved {path} ({len(df)} rows, {len(rect)} metric columns)")
    return path


def parse_ground_truth(path):
    """{case_id: {start_time, end_time, services, faults}} from the layout of concurrent_faults.sh."""
    cases = {}
    with open(path) as fh:
        for line in fh:
            row = line.strip().split(",")
            if len(row) == 3 and row[1] == "end_time":
                cases.setdefault(row[0], {})["end_time"] = int(row[2])
            elif len(row) >= 8 and (len(row) - 2) % 3 == 0:
                k = (len(row) - 2) // 3
                cases.setdefault(row[0], {}).update(
                    services=[row[2 + 2 * i] for i in range(k)], faults=[row[3 + 2 * i] for i in range(k)],
                    start_time=int(row[1 + 3 * k]))
    return cases


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ground-truth")
    ap.add_argument("--case-id")
    ap.add_argument("--start", type=int, help="case start (epoch s); the window starts 90 s earlier")
    ap.add_argument("--end", type=int, help="case end (epoch s); the window ends 180 s later")
    a = ap.parse_args()
    cfg = load_config(a.config)
    sys_cfg = cfg["systems"][a.system]
    force = os.environ.get("FORCE_REEXPORT") == "1"
    if a.case_id:
        cases = {a.case_id: {"start_time": a.start, "end_time": a.end}}
    else:
        cases = parse_ground_truth(a.ground_truth)
    for cid, info in cases.items():
        if "end_time" not in info or "start_time" not in info:
            print(f"SKIP {cid}: case did not complete")
            continue
        if os.path.exists(os.path.join(a.out_dir, f"{cid}.csv")) and not force:
            continue
        export_window(cid, sys_cfg, info["start_time"], info["end_time"], a.out_dir, cfg["prometheus_url"])


if __name__ == "__main__":
    main()
