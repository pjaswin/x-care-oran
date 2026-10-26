#!/usr/bin/env python3
"""Build the published X-CARE dataset from the raw outputs of the simulation campaign.

For every run it copies the ns-3 E2 traces that the analysis uses (unchanged ns-O-RAN formats), converts the
xApp text logs into tidy CSV files and keeps the CQM, MLB and decision logs (used by tools/replay_check.py). Raw PHY
packet traces and all other ns-3 outputs are not included.

Input  : <raw>/<config>/seed_<kk>/        (written by simulation/run_campaign.sh), or the layout of the paper
         campaign <raw>/<Config>Seed<k>/run_001/ (Config in Baseline, Observer, PriorityHO, PriorityMLB)
Output : <out>/<config>/seed_<kk>/ns3/...,  <out>/<config>/seed_<kk>/xapp/*.csv  and  .../xapp/logs/*.log
         with config in baseline, x-care, priority-cqm, priority-mlb.

Usage:  python3 tools/build_dataset.py --raw <raw campaign dir> --out <dataset dir>
"""
import argparse, csv, hashlib, os, re, shutil

CONFIGS = [("Baseline", "baseline"), ("Observer", "x-care"), ("PriorityHO", "priority-cqm"), ("PriorityMLB", "priority-mlb")]
SEEDS = range(1, 11)
CELLS = (2, 3, 4)
NS3_FILES = ([f"cu-cp-cell-{c}.txt" for c in CELLS] + [f"cu-up-cell-{c}.txt" for c in CELLS] + [f"du-cell-{c}.txt" for c in CELLS]
             + ["DlE2PdcpStatsLte.txt", "UeHandoverStartStats.txt", "UeHandoverEndStats.txt"])
XAPP = {"HO": "CQM", "CQM": "CQM", "MLB": "MLB", "BOTH": "BOTH"}       # xApp names as used in the paper
NUM = r"-?(?:inf|nan|\d+(?:\.\d*)?(?:e[-+]?\d+)?)"          # non-finite values are kept as reported by ns-3
LOGS = [(("xapp-handover_HO_xApp.log", "xapp-cqm.log"), "xapp-cqm.log"),
        (("xapp-handover_MLB_xApp.log", "xapp-mlb.log"), "xapp-mlb.log"),
        (("xapp-observer.log", "xapp-decisions.log"), "xapp-decisions.log")]
RENAME = [(" HO from ", " CQM from "), ("[OBSERVER]", "[X-CARE]"), (": HO sent it back", ": CQM sent it back"),   # names of
          ("notify HO block", "notify CQM block"), ("[->HO]", "[->CQM]"), (": HO wanted", ": CQM wanted"),         # the paper
          ("but HO already", "but CQM already"), ("-> HO command", "-> CQM command"), ("(winner=HO)", "(winner=CQM)")]

# ---------------------------------------------------------------------------------------------------- xApp commands
RE_CMD = re.compile(r"^At ([\d.]+), UE_(\d+) (HO|CQM|MLB) from gNB_(\S+) to gNB_(\d+)\.$")
RE_NOACT = re.compile(r"^At [\d.]+, no action\.$")


def commands(run):
    rows = []
    for logs, xapp in ((("xapp-handover_HO_xApp.log", "xapp-cqm.log"), "CQM"), (("xapp-handover_MLB_xApp.log", "xapp-mlb.log"), "MLB")):
        log = next(f for f in logs if os.path.exists(os.path.join(run, f)))
        for ln in open(os.path.join(run, log), errors="strict"):
            ln = ln.rstrip("\n")
            if not ln or RE_NOACT.match(ln):
                continue
            m = RE_CMD.match(ln)
            assert m, f"unparsed command line in {run}/{log}: {ln!r}"
            src = m.group(4)
            rows.append((float(m.group(1)), xapp, int(m.group(2)), int(src) if src.isdigit() else "", int(m.group(5))))
    rows.sort(key=lambda r: (r[0], r[1] != "CQM"))            # CQM commands are processed first within a cycle
    return ["time_s", "xapp", "ue", "source_cell", "target_cell"], rows


# ------------------------------------------------------------------------------------------- KPM state seen by xApps
RE_STATE = re.compile(r"^At ([\d.]+), State:$")
RE_PRB = re.compile(r"^At ([\d.]+), Cell PRB:$")


def state(run):
    srows, prows = [], []
    lines = open(os.path.join(run, "xapp-input.log")).read().splitlines()
    i = 0
    while i < len(lines):
        m = RE_STATE.match(lines[i])
        if m:
            t = float(m.group(1)); i += 1; block = []
            while i < len(lines) and not lines[i].startswith("At "):
                block.append(lines[i]); i += 1
            for row in re.findall(r"\[([^\[\]]+)\]", " ".join(block)):
                v = [float(x) for x in re.findall(NUM, row)]
                assert len(v) == 8, f"state row with {len(v)} values in {run}: {row!r}"
                ue, serv, s2, s3, s4, _cqi, retx, lat = v
                if ue > 0:
                    srows.append((t, int(ue), int(serv), s2, s3, s4, retx, lat))
            continue
        m = RE_PRB.match(lines[i])
        if m:
            t = float(m.group(1)); i += 1
            for cell, val in re.findall(r"(\d+): (" + NUM + ")", lines[i]):
                prows.append((t, int(cell), float(val)))
            i += 1; continue
        raise AssertionError(f"unparsed input-log line in {run}: {lines[i]!r}")
    return (["time_s", "ue", "serving_cell", "sinr_cell2_db", "sinr_cell3_db", "sinr_cell4_db", "mac_retx_pct", "pdcp_latency_ms"], srows,
            ["time_s", "cell", "prb_utilization"], prows)


# ------------------------------------------------------------------------------------------------- X-CARE decisions
RE_EVT = re.compile(r"^At ([\d.]+), \[(?:OBSERVER|X-CARE)\] (\w+) UE_(\d+): (HO|CQM|MLB) sent it back to gNB_(\d+) \| (.*)$")
RE_NOTE = re.compile(r"^sev=(" + NUM + r") share=(" + NUM + r") -> notify (\w+) .*?\(score (" + NUM + r")\)"
                     r"(?: \| CHRONIC pair \((\d+), (\d+)\) -> soft bar until t=(" + NUM + r"))?$")
RE_SKIP = re.compile(r"^D=(" + NUM + r") \(chi2 gate (" + NUM + r")\) -> harmless, no action$")
OUTCOME = {"REVERSAL": "notified", "TIE": "tie", "LOW_CONFIDENCE": "low_confidence", "INSUFFICIENT_DATA": "insufficient_data",
           "BASELINE_NOT_READY": "baseline_not_ready"}
RE_REJ = re.compile(r"^At ([\d.]+), \[PRIORITY\] UE_(\d+): (HO|CQM|MLB) wanted gNB_(\d+) but (HO|CQM|MLB) already has gNB_(\d+) in effect "
                    r"-> (HO|CQM|MLB) command REJECTED$")
RE_OTHER = re.compile(r"^At [\d.]+, \[(CYCLE|PRIORITY)\] ")


def decisions(run):
    ev, rej = [], []
    log = next(f for f in ("xapp-observer.log", "xapp-decisions.log") if os.path.exists(os.path.join(run, f)))
    for ln in open(os.path.join(run, log)):
        ln = ln.rstrip("\n")
        m = RE_EVT.match(ln)
        if m:
            t, kind, ue, back, cell, rest = m.groups()
            row = dict(time_s=float(t), ue=int(ue), outcome=OUTCOME[kind], reversed_by=XAPP[back], assessed_cell=int(cell),
                       severity="", confidence="", notified="", score="", repeat_warning=0, repeat_pair="", warning_until_s="")
            n = RE_NOTE.match(rest)
            if n:
                assert kind == "REVERSAL", ln
                row.update(severity=float(n.group(1)), confidence=float(n.group(2)), notified=XAPP[n.group(3)], score=float(n.group(4)))
                if n.group(5):
                    row.update(repeat_warning=1, repeat_pair=f"{n.group(5)}-{n.group(6)}", warning_until_s=float(n.group(7)))
            else:
                s = RE_SKIP.match(rest)
                assert s and kind != "REVERSAL", f"unparsed X-CARE line in {run}: {ln!r}"
                row.update(severity=float(s.group(1)))          # logged as "D=", it is the normalised severity
            ev.append(row); continue
        m = RE_REJ.match(ln)
        if m:
            t, ue, loser, want, winner, has, rejected = m.groups()
            assert XAPP[loser] == XAPP[rejected], ln
            rej.append((float(t), int(ue), XAPP[rejected], int(want), XAPP[winner], int(has))); continue
        assert RE_OTHER.match(ln), f"unparsed decision-log line in {run}: {ln!r}"
    return ev, rej


def copy_logs(run, dst):
    """The xApp logs as recorded; logs of the paper campaign used the names HO and OBSERVER for CQM and X-CARE."""
    os.makedirs(dst, exist_ok=True)
    for names, out in LOGS:
        src = next(os.path.join(run, f) for f in names if os.path.exists(os.path.join(run, f)))
        with open(src) as fi, open(os.path.join(dst, out), "w") as fo:
            for ln in fi:
                for a, b in RENAME:
                    ln = ln.replace(a, b)
                fo.write(ln)


def write_csv(path, header, rows, dicts=False):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r[h] for h in header] if dicts else r)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", required=True, help="raw campaign directory (<Config>Seed<k>/run_001)")
    ap.add_argument("--out", required=True, help="output dataset directory")
    a = ap.parse_args()
    sums = []
    for raw_name, cfg in CONFIGS:
        for s in SEEDS:
            run = next((r for r in (os.path.join(a.raw, cfg, f"seed_{s:02d}"),                # run_campaign.sh layout
                                    os.path.join(a.raw, f"{raw_name}Seed{s}", "run_001"))      # paper campaign layout
                        if os.path.isdir(r)), None)
            assert run, f"no raw run for {cfg} seed {s} in {a.raw}"
            dst = os.path.join(a.out, cfg, f"seed_{s:02d}")
            os.makedirs(os.path.join(dst, "ns3"), exist_ok=True); os.makedirs(os.path.join(dst, "xapp"), exist_ok=True)
            for f in NS3_FILES:
                shutil.copy2(os.path.join(run, f), os.path.join(dst, "ns3", f))
            h, rows = commands(run); write_csv(os.path.join(dst, "xapp", "commands.csv"), h, rows)
            copy_logs(run, os.path.join(dst, "xapp", "logs"))
            sh, srows, ph, prows = state(run)
            write_csv(os.path.join(dst, "xapp", "kpm_state.csv"), sh, srows)
            write_csv(os.path.join(dst, "xapp", "cell_load.csv"), ph, prows)
            ev, rej = decisions(run)
            if cfg == "x-care":
                write_csv(os.path.join(dst, "xapp", "xcare_events.csv"),
                          ["time_s", "ue", "outcome", "reversed_by", "assessed_cell", "severity", "confidence",
                           "notified", "score", "repeat_warning", "repeat_pair", "warning_until_s"], ev, dicts=True)
            else:
                assert not ev, f"X-CARE events in a {cfg} run: {run}"
            if cfg.startswith("priority"):
                write_csv(os.path.join(dst, "xapp", "priority_rejections.csv"),
                          ["time_s", "ue", "rejected_xapp", "requested_cell", "winner_xapp", "winner_cell"], rej)
            else:
                assert not rej, f"priority rejections in a {cfg} run: {run}"
            print(f"{cfg:13s} seed {s:2d}: {len(rows):5d} commands, {len(srows):6d} state rows, {len(ev):4d} X-CARE events, "
                  f"{len(rej):4d} rejections", flush=True)
    for root, _, files in os.walk(a.out):
        for f in sorted(files):
            p = os.path.join(root, f)
            if f != "SHA256SUMS":
                sums.append(f"{sha256(p)}  {os.path.relpath(p, a.out)}")
    with open(os.path.join(a.out, "SHA256SUMS"), "w") as f:
        f.write("\n".join(sorted(sums, key=lambda x: x.split("  ", 1)[1])) + "\n")


if __name__ == "__main__":
    main()
