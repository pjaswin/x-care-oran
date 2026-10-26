#!/usr/bin/env python3
"""Paired comparison of every configuration against Baseline (ten matched seeds).

Reads   data/processed/metrics_by_seed.csv
Writes  data/processed/summary.csv: mean, SD, mean paired difference and relative change with 95 % t-intervals,
        number of seeds lower/higher than Baseline and the exact two-sided sign-test p-value.
Prints  the values quoted in the paper.
"""
import csv, math, os, statistics as st
from math import comb
import common as cm

T975_DF9 = 2.2621571627          # t quantile, 9 degrees of freedom
METRICS = [  # (column, direction: -1 lower is better, +1 higher is better)
    ("reversals", -1), ("executed_handovers", -1), ("handovers_cqm", -1), ("handovers_mlb", -1), ("cqm_undo_share_pct", -1),
    ("outage_time_pct", -1), ("overload_time_pct", -1), ("sinr_mean_db", +1), ("strongest_cell_share_pct", +1), ("jain_load_fairness", +1),
    ("latency_mean_ms", -1), ("latency_p95_ms", -1), ("throughput_per_ue_mbps", +1), ("delivery_ratio_pct", +1), ("rlc_buffer_p95_kb", -1)]


def sign_p(k, n):
    return min(1.0, 2 * sum(comb(n, i) for i in range(max(k, n - k), n + 1)) / 2 ** n) if n else float("nan")


def main():
    rows = list(csv.DictReader(open(os.path.join(cm.PROCESSED, "metrics_by_seed.csv"))))
    val = lambda cfg, col: [float(r[col]) for r in sorted((r for r in rows if r["config"] == cfg), key=lambda r: int(r["seed"]))]
    out = []
    for col, d in METRICS:
        base = val("baseline", col)
        for cfg in cm.CONFIGS:
            v = val(cfg, col)
            rec = dict(metric=col, config=cfg, mean=st.mean(v), sd=st.stdev(v))
            if cfg != "baseline":
                diff = [a - b for a, b in zip(v, base)]; rel = [100 * (a - b) / b for a, b in zip(v, base)]
                lo, hi = sum(x < 0 for x in diff), sum(x > 0 for x in diff)
                h = lambda xs: T975_DF9 * st.stdev(xs) / math.sqrt(len(xs))
                rec.update(diff_mean=st.mean(diff), diff_ci95=h(diff), rel_change_pct=st.mean(rel), rel_ci95=h(rel),
                           seeds_lower=lo, seeds_higher=hi, seeds_better=lo if d < 0 else hi, sign_test_p=sign_p(max(lo, hi), lo + hi))
            out.append(rec)
    keys = list(dict.fromkeys(k for r in out for k in r))
    with open(os.path.join(cm.PROCESSED, "summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, restval=""); w.writeheader(); w.writerows(out)
    print(f"{'metric':26s} {'config':13s} {'mean':>10s} {'change vs Baseline':>20s}  better  sign-test p")
    for r in out:
        ch = "" if r["config"] == "baseline" else f"{r['rel_change_pct']:+7.1f}% ({r['diff_mean']:+.3g})"
        better = "" if r["config"] == "baseline" else f"{r['seeds_better']:2d}/10   {r['sign_test_p']:.3f}"
        print(f"{r['metric']:26s} {r['config']:13s} {r['mean']:10.3f} {ch:>20s}  {better}")


if __name__ == "__main__":
    main()
