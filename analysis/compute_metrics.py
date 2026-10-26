#!/usr/bin/env python3
"""Compute the per-run metrics of the paper from the X-CARE dataset.

Writes  data/processed/metrics_by_seed.csv      one row per (configuration, seed), all metrics of the paper
        data/processed/latency_intervals.csv.gz  per-UE 100-ms PDCP latency intervals (used by the latency CCDF)

Usage:  python3 analysis/compute_metrics.py --dataset <dataset dir>
"""
import argparse, csv, gzip, io, math, os, statistics as st
import common as cm

COLUMNS = [
    "config", "seed", "t_end_s",
    # control actions (RQ1)
    "commands_cqm", "commands_mlb", "executed_handovers", "handovers_cqm", "handovers_mlb", "handovers_unattributed",
    "handovers_ambiguous", "reversals", "reversals_by_cqm", "reversals_by_mlb", "cqm_undo_share_pct", "mlb_undo_share_pct",
    # xApp objectives (RQ2)
    "outage_time_pct", "overload_time_pct", "sinr_mean_db", "strongest_cell_share_pct", "jain_load_fairness",
    # network performance (RQ3)
    "latency_mean_ms", "latency_p95_ms", "throughput_per_ue_mbps", "delivery_ratio_pct", "rlc_buffer_p95_kb",
    # decisions of X-CARE and of the fixed-priority mediator
    "xcare_detected", "xcare_notified_cqm", "xcare_notified_mlb", "xcare_notified_both", "xcare_tie", "xcare_low_confidence",
    "xcare_insufficient_data", "xcare_baseline_not_ready", "xcare_repeat_warnings", "priority_rejected_commands"]


def run_metrics(dataset, cfg, seed):
    run = cm.run_dir(dataset, cfg, seed)
    B = cm.end_time(run)
    trans, reports = cm.cucp(run, B)
    cmds = cm.commands(run, B)
    att, rev = cm.attribute_and_reverse(trans, cmds)
    finite = [(s, nb) for s, nb in reports if math.isfinite(s)]
    with_nb = [(s, nb) for s, nb in finite if nb is not None]
    pd = cm.pdcp_lte(run, B)
    du = cm.du(run, B)
    m = dict(config=cfg, seed=seed, t_end_s=B,
             commands_cqm=len(cmds["CQM"]), commands_mlb=len(cmds["MLB"]),
             executed_handovers=sum(len(v) for v in trans.values()), handovers_cqm=att["CQM"], handovers_mlb=att["MLB"],
             handovers_unattributed=att["unattributed"], handovers_ambiguous=att["ambiguous"],
             reversals=rev["CQM"] + rev["MLB"], reversals_by_cqm=rev["CQM"], reversals_by_mlb=rev["MLB"],
             cqm_undo_share_pct=100 * rev["CQM"] / att["CQM"], mlb_undo_share_pct=100 * rev["MLB"] / att["MLB"],
             outage_time_pct=100 * sum(s < cm.OUTAGE_SINR_DB for s, _ in finite) / len(finite),
             overload_time_pct=du["overload_time_pct"],
             sinr_mean_db=st.mean(s for s, _ in finite),
             strongest_cell_share_pct=100 * sum(nb - s <= 0 for s, nb in with_nb) / len(with_nb),
             jain_load_fairness=du["jain_load_fairness"],
             latency_mean_ms=pd["latency_mean_ms"], latency_p95_ms=cm.pctl(pd["interval_ms"], 0.95),
             throughput_per_ue_mbps=pd["throughput_per_ue_mbps"], delivery_ratio_pct=pd["delivery_ratio_pct"],
             rlc_buffer_p95_kb=du["rlc_buffer_p95_kb"])
    ev = cm.xcare_events(run)
    if ev is not None:
        m.update(xcare_detected=len(ev),
                 xcare_notified_cqm=sum(e["notified"] == "CQM" for e in ev), xcare_notified_mlb=sum(e["notified"] == "MLB" for e in ev),
                 xcare_notified_both=sum(e["notified"] == "BOTH" for e in ev),
                 **{f"xcare_{k}": sum(e["outcome"] == k for e in ev) for k in ("tie", "low_confidence", "insufficient_data", "baseline_not_ready")},
                 xcare_repeat_warnings=sum(e["repeat_warning"] == "1" for e in ev))
    rej = cm.priority_rejections(run)
    if rej is not None:
        m["priority_rejected_commands"] = len(rej)
    return m, pd["interval_ms"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", required=True)
    a = ap.parse_args()
    os.makedirs(cm.PROCESSED, exist_ok=True)
    rows = []
    with open(os.path.join(cm.PROCESSED, "latency_intervals.csv.gz"), "wb") as raw, \
            io.TextIOWrapper(gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename=""), newline="") as gz:   # reproducible bytes
        w = csv.writer(gz); w.writerow(["config", "seed", "latency_ms"])
        for cfg in cm.CONFIGS:
            for s in cm.SEEDS:
                m, iv = run_metrics(a.dataset, cfg, s)
                rows.append(m)
                w.writerows((cfg, s, repr(x)) for x in iv)
                print(f"{cfg:13s} seed {s:2d} done", flush=True)
    with open(os.path.join(cm.PROCESSED, "metrics_by_seed.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, restval=""); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
