#!/bin/bash
# Run the evaluation campaign: every configuration with every seed (210 s of simulated time each).
#
#   NS3_DIR=<patched ns-O-RAN tree> CONTAINER=<xApp container> E2_TERM_IP=<container IP> OUT=<raw output dir> \
#   ./run_campaign.sh [configs...]
#
# For each (configuration, seed) it starts the xApps in the container, runs the ns-3 scenario and copies the ns-3
# traces and the xApp logs to $OUT/<config>/seed_<kk>/. Build the published dataset afterwards with
#   python3 tools/build_dataset.py --raw $OUT --out <dataset dir>
set -euo pipefail
: "${NS3_DIR:?set NS3_DIR}" "${CONTAINER:?set CONTAINER}" "${E2_TERM_IP:?set E2_TERM_IP}" "${OUT:?set OUT}"
XAPP_LOG_DIR=${XAPP_LOG_DIR:-}            # host directory mounted at /home in the container (where the xApp logs are)
SIM_TIME=${SIM_TIME:-210}
SEEDS=${SEEDS:-"1 2 3 4 5 6 7 8 9 10"}
CONFIGS=("${@:-baseline x-care priority-cqm priority-mlb}")
NS3_FILES="cu-cp-cell-2.txt cu-cp-cell-3.txt cu-cp-cell-4.txt cu-up-cell-2.txt cu-up-cell-3.txt cu-up-cell-4.txt
           du-cell-2.txt du-cell-3.txt du-cell-4.txt DlE2PdcpStatsLte.txt UeHandoverStartStats.txt UeHandoverEndStats.txt"
XAPP_FILES="xapp-input.log xapp-cqm.log xapp-mlb.log xapp-decisions.log"

for cfg in ${CONFIGS[@]}; do
  for seed in $SEEDS; do
    dst="$OUT/$cfg/seed_$(printf %02d "$seed")"; mkdir -p "$dst"
    echo "[$(date +%T)] $cfg, seed $seed -> $dst"
    docker exec -d "$CONTAINER" bash -c "/home/sample-xapp/start_xapp.sh $cfg > /home/container.log 2>&1"
    until docker exec "$CONTAINER" bash -c "ps aux | grep -v grep | grep -q hw_xapp_main"; do sleep 1; done
    sleep 3
    (cd "$NS3_DIR" && ./ns3 run "scratch/xapp_conflict --RngRun=$seed --simTime=$SIM_TIME --e2TermIp=$E2_TERM_IP \
        --handoverMode=NoAuto --indicationPeriodicity=0.1 --enableE2FileLogging=false" > "$dst/ns3_stdout.log" 2>&1)
    for f in $NS3_FILES; do cp "$NS3_DIR/$f" "$dst/"; done
    if [ -n "$XAPP_LOG_DIR" ]; then
      for f in $XAPP_FILES; do cp "$XAPP_LOG_DIR/$f" "$dst/"; done
    else
      for f in $XAPP_FILES; do docker cp "$CONTAINER:/home/$f" "$dst/"; done
    fi
    sleep 10
  done
done
