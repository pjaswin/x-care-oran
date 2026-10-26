#!/bin/bash
# Start the xApps and the E2 connector inside the xApp container.
#   ./start_xapp.sh <baseline|x-care|priority-cqm|priority-mlb>
# Expects this directory at /home/sample-xapp and the patched connector at /home/xapp-sm-connector.
set -e
CONFIG=${1:?usage: start_xapp.sh <baseline|x-care|priority-cqm|priority-mlb>}
pkill -f "run_xapp.py" 2>/dev/null || true
pkill hw_xapp_main 2>/dev/null || true
sleep 1
cd /home/sample-xapp && python3 run_xapp.py --config "$CONFIG" --log-dir /home &
sleep 1
cd /home/xapp-sm-connector && ./run_xapp.sh
