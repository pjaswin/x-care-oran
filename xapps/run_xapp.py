#!/usr/bin/env python3
"""Run the CQM and MLB xApps, with X-CARE or a fixed-priority mediator, against the E2 connector.

    python3 run_xapp.py --config {baseline,x-care,priority-cqm,priority-mlb} [--port 4200] [--log-dir /home]

Three threads: decode the connector messages, assemble KPM cycles (state.py), and run the decision loop
(orchestrator.py). Handover commands are sent back to the connector; after sending, the reports queued meanwhile
are discarded so the next decision uses fresh measurements.
"""
import argparse, logging, os, queue, struct, threading
import numpy as np

import ric_io
from orchestrator import CONFIGS, DecisionLoop
from state import KpmCollector

np.set_printoptions(suppress=True)


def file_logger(name, path):
    lg = logging.getLogger(name)
    lg.handlers.clear()
    fh = logging.FileHandler(path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(message)s"))
    lg.addHandler(fh); lg.setLevel(logging.INFO)
    return lg


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", choices=CONFIGS, required=True)
    ap.add_argument("--port", type=int, default=4200)
    ap.add_argument("--log-dir", default="/home")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    raw, decoded, cycles, controls = queue.Queue(), queue.Queue(), queue.Queue(), queue.Queue()
    log_in = file_logger("xapp_input", os.path.join(a.log_dir, "xapp-input.log"))
    loop = DecisionLoop(a.config,
                        file_logger("cqm", os.path.join(a.log_dir, "xapp-cqm.log")).info,
                        file_logger("mlb", os.path.join(a.log_dir, "xapp-mlb.log")).info,
                        file_logger("decisions", os.path.join(a.log_dir, "xapp-decisions.log")).info)

    def decode():
        while True:
            decoded.put(ric_io.deserialize_map(raw.get()))

    def collect():
        kpm = KpmCollector(verbose=a.verbose)
        while True:
            cycle = kpm.add(decoded.get())
            if cycle is not None:
                t, state, cell_prb = cycle
                log_in.info(f"At {round(t, 2)}, State:\n{state}")
                log_in.info(f"At {round(t, 2)}, Cell PRB:\n{cell_prb}")
                cycles.put(cycle)

    def decide():
        while True:
            for ue, tgt in loop.step(*cycles.get()):
                controls.put((ue, tgt))

    conn = ric_io.open_control_socket(a.port)
    for f in (decode, collect, decide):
        threading.Thread(target=f, daemon=True).start()
    print(f"[xApp] running configuration '{a.config}'", flush=True)
    while True:
        try:
            data = ric_io.receive(conn)
        except (struct.error, OSError):
            print("E2 connector disconnected, exiting.", flush=True)
            break
        if not data:
            continue
        raw.put(data)
        if not controls.empty():
            while not controls.empty():
                ric_io.send_control(conn, *controls.get())
            for q in (raw, decoded, cycles):
                with q.mutex:
                    q.queue.clear()


if __name__ == "__main__":
    main()
