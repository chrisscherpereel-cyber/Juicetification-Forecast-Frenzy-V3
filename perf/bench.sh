#!/bin/bash
# Run the app on ONE CPU core (closest local stand-in for Community Cloud's small,
# shared allocation), monitor its CPU/memory, and drive it with N simulated students.
#
#   perf/bench.sh <app_dir> <tag> [loadtest.py args...]
#   e.g.  perf/bench.sh . opt40 --users 40 --think 1.0 --ramp 5
#
# Needs: Linux (taskset), pip install websockets psutil. Results: /tmp/lt_<tag>.json
# (latencies) and /tmp/mon_<tag>.json (server CPU / memory). Run locally — never point
# a load test at the live Community Cloud app.
set -e
APP=$(cd "$1" && pwd); TAG=$2; shift 2
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${PORT:-8599}
cd "$APP"
taskset -c 0 streamlit run ${APPFILE:-forecast_frenzy.py} --server.headless true \
   --server.port $PORT --browser.gatherUsageStats false >/tmp/st_$TAG.log 2>&1 &
SPID=$!
for i in $(seq 1 60); do curl -sf http://127.0.0.1:$PORT/_stcore/health >/dev/null && break; sleep 0.5; done
python "$HERE/monitor.py" $SPID /tmp/mon_$TAG.json &
MPID=$!
taskset -c 1 python "$HERE/loadtest.py" --url http://127.0.0.1:$PORT --out /tmp/lt_$TAG.json "$@"
sleep 2
kill -INT $MPID; wait $MPID 2>/dev/null || true
cat /tmp/mon_$TAG.json; echo
kill $SPID; wait $SPID 2>/dev/null || true
