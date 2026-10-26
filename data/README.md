# Data

## Processed data (this repository)

| File | Content |
|---|---|
| `processed/metrics_by_seed.csv` | One row per configuration and seed (40 rows) with every metric reported in the paper |
| `processed/summary.csv` | Paired comparison of each configuration with Baseline: mean, SD, mean difference and relative change with 95 % t-intervals, seeds better, exact sign-test p |
| `processed/latency_intervals.csv.gz` | Per-UE 100-ms PDCP latency intervals of every run (input of the latency CCDF) |

All metrics use the window [0, T_end) of each run, T_end being the last report of the LTE-anchor PDCP trace (210 s).

### `metrics_by_seed.csv`

| Column | Definition |
|---|---|
| `config`, `seed` | baseline, x-care, priority-cqm, priority-mlb; seed = ns-3 RngRun 1–10 |
| `commands_cqm`, `commands_mlb` | commands forwarded by each xApp |
| `executed_handovers` | serving-cell changes in the CU-CP reports |
| `handovers_cqm`, `handovers_mlb` | executed changes attributed to each xApp (a command for that UE and target issued at most 1.6 s earlier); `handovers_unattributed`, `handovers_ambiguous` (both xApps requested it) |
| `reversals` | cross-xApp reversals: a change that returns the UE, within 3 s, to the cell it left at an earlier change, the two changes made by different xApps; split into `reversals_by_cqm` / `_by_mlb` (xApp of the later change) |
| `cqm_undo_share_pct`, `mlb_undo_share_pct` | share of an xApp's handovers that reverse a handover of the other xApp |
| `outage_time_pct` | share of CU-CP reports with serving SINR below 0 dB (CQM objective) |
| `overload_time_pct` | share of DU reports with cell PRB utilisation above 60 % (MLB objective) |
| `sinr_mean_db`, `strongest_cell_share_pct` | mean serving SINR; share of reports on the strongest reported cell |
| `jain_load_fairness` | Jain's index of the three cells' PRB utilisation, mean over 100-ms reports |
| `latency_mean_ms`, `latency_p95_ms` | packet-weighted mean PDCP latency; P95 of the per-UE 100-ms intervals (LTE-anchor PDCP trace) |
| `throughput_per_ue_mbps`, `delivery_ratio_pct` | delivered PDCP throughput per UE; received / transmitted PDCP PDUs |
| `rlc_buffer_p95_kb` | P95 of the summed RLC buffer of the three cells per 100-ms report |
| `xcare_*` | X-CARE decisions (x-care runs): detected conflicts, notifications to CQM / MLB / both, ties, low-confidence, insufficient data, baseline not ready, repeated-conflict warnings |
| `priority_rejected_commands` | commands rejected by the fixed-priority mediator (priority runs) |

## Raw dataset (Zenodo)

The cleaned per-run data (40 runs, 448 MB, one `.tar.xz` archive per configuration) is archived on Zenodo:
**DOI to be added**. Layout:

```
<config>/seed_<kk>/                    config in baseline, x-care, priority-cqm, priority-mlb; kk = 01..10
    ns3/   cu-cp-cell-{2,3,4}.txt      CU-CP E2 reports, every 100 ms (serving cell, serving and neighbour SINR per UE)
           cu-up-cell-{2,3,4}.txt      CU-UP E2 reports (PDCP volume, throughput and latency per UE)
           du-cell-{2,3,4}.txt         DU E2 reports (PRB utilisation, buffer, transport blocks per cell and UE)
           DlE2PdcpStatsLte.txt        downlink PDCP counters of the LTE anchor (cumulative per UE)
           UeHandoverStartStats.txt, UeHandoverEndStats.txt   handover events
    xapp/  commands.csv                time_s, xapp (CQM|MLB), ue, source_cell, target_cell
           kpm_state.csv               time_s, ue, serving_cell, sinr_cell{2,3,4}_db, mac_retx_pct, pdcp_latency_ms
           cell_load.csv               time_s, cell, prb_utilization (fraction)
           xcare_events.csv            x-care runs only
           priority_rejections.csv     priority runs only
           logs/xapp-{cqm,mlb,decisions}.log   recorded xApp logs (input of tools/replay_check.py)
SHA256SUMS
```

The `ns3/` files keep the original ns-O-RAN formats (the first line names the columns). In `cu-cp-cell-N.txt` the
columns used are `timestamp`, `L3 serving Id(m_cellId)`, `UE (imsi)`, `L3 serving SINR` and the pairs
`L3 neigh Id k (cellId)` / `L3 neigh SINR k`; in `du-cell-N.txt` they are `timestamp`, `dlPrbUsage` and
`DRB.BufferSize.Qos` (the row is repeated for every served UE). The handover traces have no header:
`UeHandoverStartStats.txt` holds `time IMSI RNTI source_cell target_cell`, `UeHandoverEndStats.txt` holds
`time IMSI RNTI target_cell`.

`xapp/` holds what the xApps saw and did, converted from their logs:

* `commands.csv`: every command sent by an xApp, in the order processed (CQM first within a cycle).
* `kpm_state.csv`, `cell_load.csv`: the KPM state of every decision cycle as the xApps received it (values as
  reported; two samples have a serving SINR of -inf: baseline seed 9 at t = 8.12 s, x-care seed 10 at t = 4.3 s).
* `xcare_events.csv`: one row per conflict detected by X-CARE: `outcome` (notified, tie, low_confidence,
  insufficient_data, baseline_not_ready), `reversed_by` (xApp of the later action), `assessed_cell` (cell assessed as
  less favourable, or the contested cell when there is no verdict), `severity` and `confidence` (both 0 to 1),
  `notified` (CQM, MLB, BOTH), `score` (hold time 3 + 3·score² s), and `repeat_warning`, `repeat_pair`,
  `warning_until_s` for repeated-conflict warnings.
* `logs/`: the recorded logs of CQM, MLB and the decision layer. The paper campaign named CQM "HO" and X-CARE
  "OBSERVER"; these names were replaced, nothing else was changed.
* `priority_rejections.csv`: time_s, ue, rejected_xapp, requested_cell, winner_xapp, winner_cell.

Not included: PHY packet traces (8 GB) and other ns-3 outputs that no result uses.

Recompute the processed data from the raw dataset, and check that the published xApps reproduce every recorded
decision:

```bash
python3 analysis/compute_metrics.py --dataset <dataset dir>
python3 analysis/summarize.py
python3 analysis/make_figures.py
python3 tools/replay_check.py --dataset <dataset dir>
```
