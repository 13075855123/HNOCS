#!/bin/bash
# ===========================================================================
# HNOCS Regression Test Suite — Phase 5
# 一键回归脚本：运行 5 benchmark，提取标量，对比基线，输出通过/失败
# 用法: cd /d/HNOCS/examples/task_driven && bash regression_test.sh
# ===========================================================================

set -euo pipefail

export TOOLS="/d/omnetpp/omnetpp-6.3.0/tools/win32.x86_64"
export OMNETPP_ROOT="/d/omnetpp/omnetpp-6.3.0"
export PATH="$TOOLS/clang64/bin:$TOOLS/usr/bin:$OMNETPP_ROOT/bin:$PATH"

BIN="../../libhnocs_dbg.exe"
NED_PATH="../../src;."
INI="omnetpp.ini"
RESULT_DIR="results"

PASS=0
FAIL=0
FAIL_ITEMS=""

# ---------- baseline values (paper §7) ----------
declare -A B_EVENTS B_TIME_US B_FLITS B_SOA_UJ B_SOA_HOPS B_TUNING_NJ B_LASER_NJ

# Updated baselines after C1+C2 fixes (2026-06-02)
B_EVENTS[Optic]=266709;    B_TIME_US[Optic]=10.507;  B_FLITS[Optic]=32768;   B_SOA_UJ[Optic]=12.75;  B_SOA_HOPS[Optic]=60;   B_TUNING_NJ[Optic]=42.06;   B_LASER_NJ[Optic]=52.5
B_EVENTS[VOPD]=1756666;    B_TIME_US[VOPD]=89.277;   B_FLITS[VOPD]=54375;    B_SOA_UJ[VOPD]=1.57;   B_SOA_HOPS[VOPD]=51;   B_TUNING_NJ[VOPD]=106.3;   B_LASER_NJ[VOPD]=446.4
B_EVENTS[MPEG4]=2264091;   B_TIME_US[MPEG4]=122.452; B_FLITS[MPEG4]=22250;   B_SOA_UJ[MPEG4]=1.32;  B_SOA_HOPS[MPEG4]=44;   B_TUNING_NJ[MPEG4]=95.8;   B_LASER_NJ[MPEG4]=612.3
B_EVENTS[HNN]=3869365;     B_TIME_US[HNN]=204.997;  B_FLITS[HNN]=53248;     B_SOA_UJ[HNN]=3.75;    B_SOA_HOPS[HNN]=166;    B_TUNING_NJ[HNN]=474.8;    B_LASER_NJ[HNN]=1025.0
B_EVENTS[GEMM]=2178337;    B_TIME_US[GEMM]=120.285; B_FLITS[GEMM]=3072;      B_SOA_UJ[GEMM]=1.29;   B_SOA_HOPS[GEMM]=67;    B_TUNING_NJ[GEMM]=111.0;   B_LASER_NJ[GEMM]=601.4

declare -A CFG
CFG[Optic]=ONoC_Optic
CFG[VOPD]=ONoC_VOPD
CFG[MPEG4]=ONoC_MPEG4
CFG[HNN]=ONoC_HNN
CFG[GEMM]=ONoC_GEMM

ORDER="Optic VOPD MPEG4 HNN GEMM"

# ---------- helper: extract scalar value from .sca ----------
# .sca format: scalar <module> <name> <value>
scalar_val() {
  local sca_file="$1"
  local name="$2"
  grep " $name " "$sca_file" 2>/dev/null | head -1 | awk '{print $4}'
}

scalar_sum() {
  local sca_file="$1"
  local name="$2"
  grep " $name " "$sca_file" 2>/dev/null | awk '{sum += $4} END {print int(sum + 0.5)}'
}

scalar_float_sum() {
  local sca_file="$1"
  local name="$2"
  grep " $name " "$sca_file" 2>/dev/null | awk '{sum += $4} END {print sum}'
}

echo "======================================================================"
echo "  HNOCS Regression Test (Phase 5)"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"
echo ""

# ---------- ensure binary exists ----------
if [ ! -f "$BIN" ]; then
  echo "[BUILD] Recompiling libhnocs_dbg.exe..."
  (cd /d/HNOCS && make MODE=debug -j8)
  echo ""
fi

# ---------- run all benchmarks ----------
for BM in $ORDER; do
  CONFIG="${CFG[$BM]}"
  LOGFILE="${RESULT_DIR}/regression_${BM}.log"

  echo "--- [$BM] $CONFIG ---"

  # run simulation
  $BIN -u Cmdenv -n "$NED_PATH" -c "$CONFIG" "$INI" > "$LOGFILE" 2>&1
  EXIT_CODE=$?

  if [ $EXIT_CODE -ne 0 ]; then
    echo "  [FAIL] Exit code=$EXIT_CODE (crash/error)"
    FAIL=$((FAIL + 1))
    FAIL_ITEMS="$FAIL_ITEMS\n  $BM: crash (exit=$EXIT_CODE)"
    continue
  fi

  # locate .sca file
  SCA=$(ls -t "${RESULT_DIR}/${CONFIG}-"*.sca 2>/dev/null | head -1)
  if [ -z "$SCA" ]; then
    echo "  [FAIL] No .sca file found"
    FAIL=$((FAIL + 1))
    FAIL_ITEMS="$FAIL_ITEMS\n  $BM: missing .sca"
    continue
  fi

  # ---------- extract metrics ----------

  # event count: parse last "Event #N" line from log
  EVENTS=$(grep "Event #" "$LOGFILE" | tail -1 | sed 's/.*Event #\([0-9]*\).*/\1/')
  EVENTS=${EVENTS:-0}

  # simulation end time: extract t=X from last Event line in log
  TIME_S=$(grep "Event #" "$LOGFILE" | tail -1 | grep -o 't=[0-9.]*' | head -1 | cut -d= -f2)
  TIME_US=$(awk "BEGIN { v = ${TIME_S:-0}; printf \"%.3f\", v * 1e6 }")

  # total optical flits (sum across all PEs)
  FLITS=$(scalar_sum "$SCA" "pe-optical-packets-sent")

  # SOA energy (J -> uJ)
  SOA_J=$(scalar_val "$SCA" "onoc-soa-total-energy-J")
  SOA_UJ=$(awk "BEGIN { v = ${SOA_J:-0}; printf \"%.2f\", v * 1e6 }")

  # SOA hops
  SOA_HOPS=$(scalar_val "$SCA" "onoc-soa-total-circuit-hops")
  SOA_HOPS=${SOA_HOPS:-0}

  # tuning energy (J -> nJ)
  TUNING_J=$(scalar_val "$SCA" "onoc-dynamic-tuning-total-energy-J")
  TUNING_NJ=$(awk "BEGIN { v = ${TUNING_J:-0}; printf \"%.2f\", v * 1e9 }")

  # laser energy (J -> nJ)
  LASER_J=$(scalar_val "$SCA" "onoc-laser-total-energy-J")
  LASER_NJ=$(awk "BEGIN { v = ${LASER_J:-0}; printf \"%.2f\", v * 1e9 }")

  # DVFS throttle penalty
  THROTTLE_SUM=$(scalar_float_sum "$SCA" "totalThrottlePenalty")
  THROTTLE_SUM=${THROTTLE_SUM:-0}

  # circuit stats
  STALE_ACKS=$(scalar_sum "$SCA" "pe-setup-ack-stale")
  RESERVE_FAILS=$(scalar_sum "$SCA" "pe-setup-reserve-fail")
  TIMEOUTS=$(scalar_sum "$SCA" "pe-setup-pending-timeout")

  # ---------- compare ----------
  ERRORS=""

  # events: exact match (deterministic)
  if [ "$EVENTS" -ne "${B_EVENTS[$BM]}" ]; then
    ERRORS="${ERRORS}  events: got $EVENTS, expected ${B_EVENTS[$BM]}\n"
  fi

  # time: < 3% deviation
  T_EXPECTED="${B_TIME_US[$BM]}"
  T_DEV=$(awk "BEGIN { d = ${TIME_US} - ${T_EXPECTED}; if (d < 0) d = -d; printf \"%.2f\", d / ${T_EXPECTED} * 100 }")
  if [ "$(awk "BEGIN { print (${T_DEV} > 3 ? 1 : 0) }")" = "1" ]; then
    ERRORS="${ERRORS}  time: ${TIME_US}us vs ${T_EXPECTED}us (${T_DEV}%)\n"
  fi

  # flits: exact match
  if [ "$FLITS" -ne "${B_FLITS[$BM]}" ]; then
    ERRORS="${ERRORS}  flits: got $FLITS, expected ${B_FLITS[$BM]}\n"
  fi

  # ---------- report ----------
  if [ -z "$ERRORS" ]; then
    echo "  [PASS] events=$EVENTS time=${TIME_US}us flits=$FLITS"
    echo "         SOA=${SOA_UJ}uJ/${SOA_HOPS}hops tune=${TUNING_NJ}nJ laser=${LASER_NJ}nJ"
    echo "         throttle=$THROTTLE_SUM stale_ack=$STALE_ACKS reserve_fail=$RESERVE_FAILS timeout=$TIMEOUTS"
    PASS=$((PASS + 1))
  else
    printf "  [FAIL]\n%b" "$ERRORS"
    FAIL=$((FAIL + 1))
    FAIL_ITEMS="$FAIL_ITEMS\n  $BM: see above"
  fi
  echo ""
done

# ---------- summary ----------
echo "======================================================================"
echo "  Results: $PASS passed, $FAIL failed out of 5 benchmarks"
echo "======================================================================"

if [ $FAIL -gt 0 ]; then
  echo -e "Failed:$FAIL_ITEMS"
  exit 1
else
  echo "All benchmarks pass. Regression suite OK."
  exit 0
fi
