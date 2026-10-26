"""Shared definitions and trace readers for the analysis of the X-CARE dataset.

Dataset layout (see data/README.md):  <dataset>/<config>/seed_<kk>/{ns3,xapp}/...
Every metric uses the window [0, T_end), where T_end is the last report time of the LTE-anchor PDCP trace.
"""
import csv, math, os
from collections import Counter, defaultdict

CONFIGS = ["baseline", "x-care", "priority-cqm", "priority-mlb"]
LABELS = {"baseline": "Baseline", "x-care": "X-CARE", "priority-cqm": "Priority-CQM", "priority-mlb": "Priority-MLB"}
SEEDS = range(1, 11)
CELLS = (2, 3, 4)                 # mmWave gNBs (cell 1 is the LTE anchor and takes no handover decisions)
ATTRIB_TOL = 1.6                  # s: a serving-cell change is attributed to a command for that UE and target issued <= 1.6 s earlier
CONFLICT_WINDOW = 3.0             # s: a cross-xApp reversal returns the UE, within 3 s, to the cell it left
OUTAGE_SINR_DB = 0.0              # CQM xApp emergency floor
OVERLOAD_PRB_PCT = 60.0           # MLB xApp overload threshold

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROCESSED = os.path.join(ROOT, "data", "processed")


def pctl(xs, f):
    """Lower nearest-rank percentile, as used throughout the paper."""
    xs = sorted(xs)
    return xs[int(f * (len(xs) - 1))] if xs else float("nan")


def run_dir(dataset, cfg, seed):
    return os.path.join(dataset, cfg, f"seed_{seed:02d}")


def end_time(run):
    last = None
    for ln in open(os.path.join(run, "ns3", "DlE2PdcpStatsLte.txt")):
        c = ln.split()
        try:
            last = float(c[1])
        except (ValueError, IndexError):
            pass
    return last


# ------------------------------------------------------------------------------------------------ CU-CP reports
def cucp(run, B):
    """Per-UE serving-cell changes, serving SINR samples and neighbour SINR, from cu-cp-cell-N.txt (every 100 ms)."""
    seq = defaultdict(list); reports = []
    for c in CELLS:
        with open(os.path.join(run, "ns3", f"cu-cp-cell-{c}.txt")) as f:
            f.readline()
            for ln in f:
                p = ln.rstrip("\n").split(",")
                if len(p) < 9:
                    continue
                try:
                    t = float(p[0]); sv = int(float(p[6])); ue = int(float(p[7])); s = float(p[8])
                except ValueError:
                    continue
                if ue <= 0 or not (0 <= t < B):
                    continue
                seq[ue].append((round(t, 2), sv))
                neigh = []
                for k in range(8 if len(p) >= 15 else 0):
                    i_id, i_s = 10 + 3 * k, 11 + 3 * k
                    if i_s >= len(p):
                        break
                    if not p[i_id].strip() or not p[i_s].strip():
                        continue
                    try:
                        v = float(p[i_s])
                    except ValueError:
                        continue
                    if math.isfinite(v):
                        neigh.append(v)
                reports.append((s, max(neigh) if neigh else None))
    trans = {}
    for ue, sq in seq.items():
        sq.sort(); ch = []; prev = None
        for t, c in sq:
            if prev is not None and c != prev:
                ch.append((t, prev, c))
            prev = c
        trans[ue] = ch
    return trans, reports


def commands(run, B):
    """Commands forwarded by each xApp (rows without a source cell were not forwarded: the UE had no report)."""
    out = {"CQM": [], "MLB": []}
    with open(os.path.join(run, "xapp", "commands.csv")) as f:
        for r in csv.DictReader(f):
            t = float(r["time_s"])
            if r["source_cell"] and 0 <= t < B:
                out[r["xapp"]].append((t, int(r["ue"]), int(r["source_cell"]), int(r["target_cell"])))
    return out


def attribute_and_reverse(trans, cmds):
    """Attribute each executed serving-cell change to the xApp whose command (same UE and target, issued 0..1.6 s
    earlier) explains it (unattributed if none, ambiguous if both), and count cross-xApp reversals: a change that
    returns the UE to the cell it left at an earlier change, within 3 s, the two changes made by different xApps."""
    by = {x: defaultdict(list) for x in cmds}
    for x, lst in cmds.items():
        for t, u, _, g in lst:
            by[x][u].append((t, g))
    att = Counter(); rev = Counter()
    for u, tl in trans.items():
        who = []
        for t, _, to in tl:
            c = {x for x in by if any(g == to and 0 <= t - tt <= ATTRIB_TOL for tt, g in by[x][u])}
            k = next(iter(c)) if len(c) == 1 else None
            who.append(k)
            att[k if k else ("ambiguous" if len(c) == 2 else "unattributed")] += 1
        for i, (ti, _, toi) in enumerate(tl):
            if who[i] is None:
                continue
            for j in range(i - 1, -1, -1):
                tj, fj, _ = tl[j]
                if ti - tj > CONFLICT_WINDOW:
                    break
                if who[j] is None:
                    continue
                if toi == fj and who[i] != who[j]:
                    rev[who[i]] += 1
                    break
    return att, rev


# ------------------------------------------------------------------------------------------- PDCP (LTE anchor)
def pdcp_lte(run, B):
    """DlE2PdcpStatsLte.txt: lifetime-cumulative per-UE PDCP counters. Totals over [0, B) from the last snapshot;
    the delay column is a cumulative mean, so per-interval means are recovered from differences of mean x count."""
    rows = defaultdict(list)
    for ln in open(os.path.join(run, "ns3", "DlE2PdcpStatsLte.txt")):
        c = ln.split()
        if len(c) < 11 or c[0].startswith("%"):
            continue
        t_end = float(c[1])
        if t_end > B + 1e-9:
            continue
        rows[c[3]].append((t_end, float(c[6]), float(c[8]), float(c[9]), float(c[10])))   # end, nTx, nRx, RxBytes, delay
    tx = rx = dsum = 0.0; per_ue_mbps = []; interval_ms = []
    for _, r in rows.items():
        r.sort(); e = r[-1]
        tx += e[1]; rx += e[2]; dsum += e[4] * e[2]
        per_ue_mbps.append(8 * e[3] / B / 1e6)
        prev = None
        for x in r:
            if prev is not None and x[2] - prev[2] > 0:
                interval_ms.append(1000 * (x[4] * x[2] - prev[4] * prev[2]) / (x[2] - prev[2]))
            prev = x
    return dict(latency_mean_ms=1000 * dsum / rx, throughput_per_ue_mbps=sum(per_ue_mbps) / len(per_ue_mbps),
                delivery_ratio_pct=100 * rx / tx, interval_ms=interval_ms)


# ------------------------------------------------------------------------------------------------ DU reports
def du(run, B):
    """du-cell-N.txt (cell level, every 100 ms; the row is repeated per served UE, the first row per time is used):
    PRB utilisation, RLC buffer, Jain fairness of the three cells' load, overload time."""
    ser = {}; n_rep = overload = 0
    for c in CELLS:
        with open(os.path.join(run, "ns3", f"du-cell-{c}.txt")) as f:
            h = f.readline().rstrip("\n").split(","); iu = h.index("dlPrbUsage"); ib = h.index("DRB.BufferSize.Qos")
            seen = set(); s = {}
            for ln in f:
                p = ln.split(",")
                try:
                    t = float(p[0])
                    if not (0 <= t < B) or t in seen:
                        continue
                    seen.add(t); u = float(p[iu]); s[int(t * 10)] = (u, float(p[ib]))
                    n_rep += 1; overload += u > OVERLOAD_PRB_PCT
                except (ValueError, IndexError):
                    pass
        ser[c] = s
    common = sorted(set.intersection(*[set(s) for s in ser.values()]))
    jain = [sum(u) ** 2 / (len(u) * sum(x * x for x in u)) for u in ([ser[c][b][0] for c in CELLS] for b in common) if sum(u) > 0]
    buf = [sum(ser[c][b][1] for c in CELLS) / 1e3 for b in common]
    return dict(jain_load_fairness=sum(jain) / len(jain), overload_time_pct=100 * overload / n_rep, rlc_buffer_p95_kb=pctl(buf, 0.95))


# --------------------------------------------------------------------------------------- xApp-side decision logs
def xcare_events(run):
    p = os.path.join(run, "xapp", "xcare_events.csv")
    return list(csv.DictReader(open(p))) if os.path.exists(p) else None


def priority_rejections(run):
    p = os.path.join(run, "xapp", "priority_rejections.csv")
    return list(csv.DictReader(open(p))) if os.path.exists(p) else None
