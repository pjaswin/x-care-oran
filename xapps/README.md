# xApps

Python implementation of the two xApps and of the conflict handling evaluated in the paper. All components run in
one process inside the xApp container of the near-RT RIC and receive the E2 reports through the E2 connector.

| File | Component |
|---|---|
| `cqm.py` | **CQM** xApp, Connection Quality Management: SINR-driven handovers |
| `mlb.py` | **MLB** xApp, Mobility Load Balancing: offloads UEs from overloaded cells |
| `xcare/graph.py` | X-CARE temporal interaction graph |
| `xcare/detection.py` | X-CARE Conflict Detection: executed actions, attribution to the issuing xApp, conflicts from the graph |
| `xcare/assessment.py` | X-CARE Conflict Assessment: KPM baseline, Mahalanobis distance, signed degradation score, likely culprit |
| `xcare/notification.py` | X-CARE Conflict Notification: severity, confidence, escalation, conflict score, repeated-conflict warning |
| `priority.py` | Fixed-priority mediator (comparison baseline) |
| `orchestrator.py` | Decision cycle for the four configurations; logs; per-UE command guard |
| `state.py` | Assembly of one decision cycle from the CU-CP, CU-UP and DU reports |
| `ric_io.py` | Socket interface to the E2 connector |
| `run_xapp.py`, `start_xapp.sh` | Entry points |
| `connector/xapp-sm-connector.patch` | Changes to the C++ E2 connector |

## Configurations

```bash
python3 run_xapp.py --config baseline        # both xApps, no conflict mitigation
python3 run_xapp.py --config x-care          # X-CARE observes and notifies (never rejects a command)
python3 run_xapp.py --config priority-cqm    # fixed priority, CQM wins
python3 run_xapp.py --config priority-mlb    # fixed priority, MLB wins
```

Logs written to `--log-dir` (default `/home`): `xapp-input.log` (KPM state of every cycle), `xapp-cqm.log`,
`xapp-mlb.log` (commands), `xapp-decisions.log` (X-CARE or priority decisions).

## Deployment

The xApps use the near-RT RIC of OpenRAN Gym / Colosseum (an OSC near-RT RIC, Bronze release) and its E2 connector
`xapp-sm-connector`:

```bash
git clone https://github.com/wineslab/colosseum-near-rt-ric.git
cd colosseum-near-rt-ric && git checkout 12eca72deabdb31018b70df251567f324d82b354
git apply --directory=setup/xapp-sm-connector /path/to/x-care-oran/xapps/connector/xapp-sm-connector.patch
```

Build the RIC and the xApp container as described in the ns-O-RAN quick-start guide
(<https://openrangym.com/tutorials/ns-o-ran>), place this folder at `/home/sample-xapp` in the container, and start
a configuration with `./start_xapp.sh <config>` (Python 3 with NumPy).

## Parameters

| Component | Parameter | Value |
|---|---|---|
| CQM | hysteresis, time-to-trigger, minimum interval, return ban | 4 dB, 3 cycles (300 ms), 1.5 s, 4 s |
| CQM | override of a barred cell | 10 dB better for 4 cycles (0.4 s) |
| MLB | overload, persistence, target, minimum stay | 60 % PRB, 2 cycles, at least 30 % less loaded, 1 s |
| MLB | SINR at the target | at least 5 dB, at most 12 dB below the serving cell |
| Both | hold on a notification with score C | 3 + 3 C^2 s |
| X-CARE | graph window W, attribution look-back delta | 3 s, 1.6 s |
| X-CARE | baseline warm-up, update rate, chi-square gate | 200 samples, 0.02, 9.49 |
| X-CARE | tie / joint thresholds, confidence reference | 0.44 / 1.0, 3.27 (baseline standard deviations) |
| X-CARE | alpha_min, C_min, gamma, escalation window | 0.30, 0.30, 0.25, 4 s |
| X-CARE | repeated-conflict warning | after 2 conflicts on the same UE and cell pair within 200 s; +4 dB for 90 s |
| Orchestrator | command guard | one command per UE every 0.5 s; CQM commands first |

## Notes on the implementation

* State column 6 carries the MAC retransmission rate. CQM's emergency path on "persistent poor cycles" and MLB's
  ranking of candidate UEs read this column (see the comments in `cqm.py` and `mlb.py`). The behaviour is kept
  exactly as in the experiments.
* MLB does not check whether a move reverses the load imbalance between the two cells.
* `tools/replay_check.py` replays the recorded KPM state of every run through `orchestrator.py` and verifies that the
  CQM, MLB and decision logs are reproduced line by line.
