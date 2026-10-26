#!/usr/bin/env python3
"""Replay the decision layer of the recorded runs and compare with the recorded logs.

Feeds the KPM state of every recorded cycle (xapp/kpm_state.csv, xapp/cell_load.csv) through
xapps/orchestrator.DecisionLoop with the run's configuration and checks that the generated CQM, MLB and decision logs
are identical, line by line, to the logs recorded during the experiment (xapp/logs/). This verifies that the
published xApps make exactly the decisions of the experiments.

Usage:  python3 tools/replay_check.py --dataset <dataset dir> [--configs x-care ...]
"""
import argparse, csv, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "xapps"))
from orchestrator import CONFIGS, DecisionLoop

LOGS = {"cqm": "xapp-cqm.log", "mlb": "xapp-mlb.log", "dec": "xapp-decisions.log"}


def grouped(path, key):
    """Rows of a per-cycle CSV, split into cycles: a cycle ends when the time changes or a key repeats."""
    out = []
    for r in csv.DictReader(open(path)):
        if not out or r["time_s"] != out[-1][0]["time_s"] or any(q[key] == r[key] for q in out[-1]):
            out.append([])
        out[-1].append(r)
    return out


def cycles(xapp_dir):
    """(logged time, state matrix, cell PRB) of every cycle, as the xApps received it."""
    state = {}
    for g in grouped(os.path.join(xapp_dir, "kpm_state.csv"), "ue"):
        state.setdefault(g[0]["time_s"], []).append(np.array(
            [[float(r["ue"]), float(r["serving_cell"]), float(r["sinr_cell2_db"]), float(r["sinr_cell3_db"]),
              float(r["sinr_cell4_db"]), 0.0, float(r["mac_retx_pct"]), float(r["pdcp_latency_ms"])] for r in g]))
    for g in grouped(os.path.join(xapp_dir, "cell_load.csv"), "cell"):
        t = g[0]["time_s"]
        yield float(t), (state[t].pop(0) if state.get(t) else None), {int(r["cell"]): float(r["prb_utilization"]) for r in g}
    assert not any(state.values()), f"state rows without a cycle in {xapp_dir}"


def cycle_times(log):
    """Full-precision time of every decision cycle: each cycle writes at least one line to the CQM log."""
    seen = []
    for ln in open(log):
        ts = ln.split(",", 1)[0][3:]
        if not seen or seen[-1] != ts:
            seen.append(ts)
    return seen


def check(xapp_dir, cfg):
    got = {k: [] for k in LOGS}
    loop = DecisionLoop(cfg, got["cqm"].append, got["mlb"].append, got["dec"].append)
    times = iter(cycle_times(os.path.join(xapp_dir, "logs", LOGS["cqm"]))); t_full = next(times, None)
    for t2, state, prb in cycles(xapp_dir):
        if state is not None:
            while t_full is not None and round(float(t_full), 2) != t2:
                t_full = next(times, None)
            assert t_full is not None, f"no decision time for cycle {t2}"
            loop.step(float(t_full), state, prb)
            t_full = next(times, None)
    res = {}
    for k, f in LOGS.items():
        want = open(os.path.join(xapp_dir, "logs", f)).read().splitlines()
        diff = next((i for i, (a, b) in enumerate(zip(got[k], want)) if a != b), None)
        if diff is None and len(got[k]) != len(want):
            diff = min(len(got[k]), len(want))
        res[k] = (len(want), diff, None if diff is None else (want[diff:diff + 1], got[k][diff:diff + 1]))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--configs", nargs="*", choices=CONFIGS, default=list(CONFIGS))
    a = ap.parse_args()
    ok = True
    for cfg in a.configs:
        for s in range(1, 11):
            res = check(os.path.join(a.dataset, cfg, f"seed_{s:02d}", "xapp"), cfg)
            line = " | ".join(f"{k}: {n} lines {'identical' if d is None else 'DIFFER at ' + str(d)}" for k, (n, d, _) in res.items())
            print(f"{cfg:13s} seed {s:2d}: {line}", flush=True)
            for k, (n, d, ex) in res.items():
                if d is not None:
                    ok = False; print(f"    {k}: recorded {ex[0]}\n    {' ' * len(k)}  replayed {ex[1]}")
    print("ALL IDENTICAL" if ok else "DIFFERENCES FOUND")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
