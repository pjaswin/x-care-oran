# Simulation

The network is simulated with **ns-O-RAN** (ns-3 mmWave with LTE–NR dual connectivity and the O-RAN E2 interface).
This folder contains only what was added or changed for X-CARE; everything else comes from the upstream projects
pinned below.

| Path | Content |
|---|---|
| `scenario/xapp_conflict.cc` | The evaluation scenario (topology, radio, traffic, E2 reporting) |
| `patches/01-ns3-mmwave.patch` | Changes to the ns-3 tree: E2 report format for the xApp interface (per-UE KPM entries and UE list), re-enabling handovers to a cell after a completed handover, and a build without the optional SUMO dependency |
| `patches/02-oran-interface.patch` | Change to the E2 module: decoding of the RIC control message into a handover request |
| `run_campaign.sh` | Runs all configurations and seeds and collects the traces and xApp logs |

The patches contain only the functional changes; local logging statements and comments are omitted. Applied to the
pinned commits, they reproduce the code that generated the dataset.

## Build

```bash
# 1. ns-3 mmWave tree used in the paper (fork of ns-O-RAN)
git clone https://github.com/HapCommSys/V2X_ns3_handover_simulation.git ns3
cd ns3 && git checkout f7fa7bb8f8ad6e8c9e494652391b32a8e09a0ab7
git apply /path/to/x-care-oran/simulation/patches/01-ns3-mmwave.patch

# 2. O-RAN E2 module
git clone https://github.com/o-ran-sc/sim-ns3-o-ran-e2.git contrib/oran-interface
git -C contrib/oran-interface checkout 8ceee89404856e3249b75b3ae36b3877e910aef8      # branch l-release
git -C contrib/oran-interface apply /path/to/x-care-oran/simulation/patches/02-oran-interface.patch

# 3. Scenario
cp /path/to/x-care-oran/simulation/scenario/xapp_conflict.cc scratch/

# 4. Build (requires the e2sim library, see the ns-O-RAN quick-start guide: https://openrangym.com/tutorials/ns-o-ran)
./ns3 configure --enable-examples --enable-tests
./ns3 build
```

## Run

The xApps run in the near-RT RIC (see [`../xapps/README.md`](../xapps/README.md)). One run of the paper campaign:

```bash
./ns3 run "scratch/xapp_conflict --RngRun=<seed> --simTime=210 --e2TermIp=<xApp container IP> \
           --handoverMode=NoAuto --indicationPeriodicity=0.1 --enableE2FileLogging=false"
```

`handoverMode=NoAuto` disables RAN-autonomous handovers, so every handover is commanded by an xApp. The whole campaign
(4 configurations x 10 seeds) is automated by `run_campaign.sh`:

```bash
NS3_DIR=~/ns3 CONTAINER=sample-xapp E2_TERM_IP=10.0.2.24 OUT=~/raw ./run_campaign.sh
python3 ../tools/build_dataset.py --raw ~/raw --out ~/x-care-dataset
```

## Scenario

| Parameter | Value |
|---|---|
| Area, heights | 150 m x 150 m; gNB 25 m, LTE eNB 35 m, UE 1.5 m |
| Cells | 3 mmWave gNBs (two corners and the midpoint of the opposite edge), 1 LTE eNB at the centre |
| UEs | 10, 2D random walk at 5–10 m/s |
| Carrier | 28 GHz, 20 MHz, numerology 2 (60 kHz SCS) |
| Antennas | gNB 16x16 uniform planar array, UE single element |
| Propagation | 3GPP UMi street canyon |
| Traffic | downlink UDP CBR, 1700 B every 1 ms per UE (13.6 Mb/s) |
| RLC | UM, 1 MB buffer |
| E2 reports | CU-CP, CU-UP, DU every 100 ms |
| Run | 210 s, seeds (RngRun) 1–10 for every configuration |

## Credits and license

The ns-3 tree is the work of the ns-3, ns3-mmwave, ns-O-RAN and V2X handover simulation authors; the E2 module is
from the O-RAN Software Community. The scenario file and the patches are distributed under the GNU GPL v2, like
ns-3.
