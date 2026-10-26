# X-CARE

**Detecting, assessing and notifying conflicts between xApps in the O-RAN near-RT RIC.**

xApps in the near-RT RIC are developed independently. Each one optimises its own objective, so they can act on the
same parameters in opposite directions. This repository contains X-CARE, an xApp that handles such conflicts by
observing the other xApps. It is evaluated on two handover xApps:

* **CQM** (Connection Quality Management) hands UEs over to cells with better SINR.
* **MLB** (Mobility Load Balancing) moves UEs out of overloaded cells.

Each xApp regularly undoes the other's handovers. X-CARE does not block or reorder commands. It works in three steps:

| Module | What it does |
|---|---|
| **Detection** | Tracks the actions actually executed in the RAN and attributes each one to the xApp that issued it. It builds a temporal interaction graph and reports a conflict when one xApp's action reverses another's within a time window. |
| **Assessment** | Learns a baseline of the KPM state and scores the network state on each side of the conflict: the Mahalanobis distance from the baseline, signed into a degradation score. It names the likely culprit and a confidence. |
| **Notification** | Converts the severity, the confidence and how often the UE has conflicted into a conflict score. It sends that score to the culprit, which holds back its actions on that UE accordingly. When the same conflict keeps recurring, it also sends a warning. |

X-CARE is compared with no conflict handling (**Baseline**) and with a fixed-priority mediator in which either CQM
(**Priority-CQM**) or MLB (**Priority-MLB**) always wins. The evaluation uses ns-O-RAN with 3 mmWave cells, 10 mobile UEs,
210 s runs and 10 seeds per configuration.

## Results

The table gives the mean over the 10 seeds of each change relative to Baseline. Every seed is paired with its
Baseline run (same mobility).

| Metric | Baseline | X-CARE | Priority-CQM | Priority-MLB |
|---|---:|---:|---:|---:|
| Cross-xApp reversals per run | 311.6 | **−30.3 %** | −43.3 % | −72.2 % |
| Executed handovers per run | 794.6 | **−21.4 %** | −11.2 % | −9.3 % |
| Outage time, serving SINR < 0 dB (CQM objective) | 1.81 % | **−17.1 %** | −0.4 % | +28.0 % |
| Overload time, cell PRB use > 60 % (MLB objective) | 34.0 % | **−3.9 %** | +6.9 % | +10.9 % |
| Mean PDCP latency | 30.3 ms | **−19.2 %** | +7.1 % | +28.7 % |
| 95th-percentile PDCP latency | 85.9 ms | **−22.7 %** | +11.8 % | +39.8 % |
| Throughput per UE | 12.97 Mb/s | **+0.5 %** | −0.1 % | −0.6 % |

* Every X-CARE improvement holds in all 10 seeds, except overload time, which holds in 8 (sign test p = 0.11).
* The fixed-priority mediators remove more reversals, but neither improves the winning xApp's objective. Both worsen
  the losing xApp's objective and the latency.
* Confidence intervals and sign tests for all metrics are in
  [`data/processed/summary.csv`](data/processed/summary.csv).

## Repository layout

```
xapps/            CQM, MLB, X-CARE (detection, assessment, notification), fixed-priority mediator, RIC interface
simulation/       ns-O-RAN scenario, patches to ns-3 and to the E2 module, campaign script
analysis/         metrics, paired statistics and figures of the paper
tools/            dataset builder and replay check
data/processed/   per-run metrics, summary statistics, latency samples
figures/          figures of the paper (PDF and PNG)
```

## Reproducing the results

You need Python 3.8 or later.

```bash
pip install -r requirements.txt
```

**From the processed data in this repository** (takes a few seconds):

```bash
python3 analysis/summarize.py       # prints the paired statistics, writes data/processed/summary.csv
python3 analysis/make_figures.py    # writes figures/
```

**From the per-run dataset.** Download the four archives and `SHA256SUMS` from the [v1.0 release](https://github.com/pjaswin/x-care-oran/releases/tag/v1.0)
(79 MB, 448 MB unpacked; contents described in [`data/README.md`](data/README.md)) and extract them into one folder.
Then:

```bash
python3 analysis/compute_metrics.py --dataset <dataset dir>   # rewrites data/processed/metrics_by_seed.csv
python3 tools/replay_check.py --dataset <dataset dir>         # replays the recorded KPM state through xapps/
```

`replay_check.py` feeds the KPM state recorded in each run to the published xApps. It checks that their CQM, MLB and
X-CARE (or mediator) logs match the recorded logs line for line. This holds for all 40 runs.

**Running a new experiment.** Building the simulator is described in [`simulation/README.md`](simulation/README.md),
and deploying the xApps in the near-RT RIC in [`xapps/README.md`](xapps/README.md).

## Implementation notes

The published xApps keep the exact behaviour used in the experiments, including two details worth knowing when
reading the code:

* CQM's emergency path for "persistently poor" cycles reads the MAC retransmission column of the KPM state, so it
  triggers on a low retransmission rate.
* MLB ranks the candidate UEs by the same column.

Both details are documented in [`xapps/README.md`](xapps/README.md) and in the code.

## Citation

The paper is under review. A citation will be added here.

## License

* Code: MIT, see [`LICENSE`](LICENSE).
* Scenario and ns-3 patches in [`simulation/`](simulation/): GPL-2.0-only, the license of ns-3.
* Connector patch [`xapps/connector/`](xapps/connector/): Apache-2.0, the license of the OSC E2 connector.
* Data: CC BY 4.0.
