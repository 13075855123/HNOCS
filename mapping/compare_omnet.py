"""
compare_omnet.py — 自动对比 OMNeT++ 仿真结果与 Python NoCSimulator 结果

用法:
  python -m mapping.compare_omnet --csv tasks_gemm_static.csv --config ONoC_GEMM
  python -m mapping.compare_omnet --all   # 对比全部四个任务图

输出: 完成时间、PE 温度、路由器温度、温度时序的差异报告。
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .task_graph import TaskGraph
from .noc_simulator import NoCSimulator


# ── 仿真参数（匹配 omnetpp.ini ONOCGeneral） ──
SIM_PARAMS = dict(
    rows=4, cols=4, en_opt=True,
    energy_window=100e-9, pend_to=200e-9, retry_dt=50e-9,
    power_idle=0.3, power_compute=2.5,
    RconvPE=8.0, RconvRouter=10.0, RlateralPE=10.0, RlateralRouter=10.0,
    Rpe2router=3.0, Cpe=1e-6, Crouter=1e-7, Tambient=318.15,
    T_throttle=327.15, throttle_beta=0.1,
    optical_ring_tuning_mW_per_ring=2.0, optical_num_rings_per_router=160,
)

# ── 容忍阈值 ──
TIME_TOLERANCE_PCT = 2.0       # 完成时间偏差 < 2%
TEMP_PEAK_TOLERANCE_K = 2.0    # 峰值温度偏差 < 2K
TEMP_AVG_TOLERANCE_K = 1.0     # 平均温度偏差 < 1K
TEMP_TIMESERIES_TOLERANCE_K = 1.0  # 时序各时刻偏差 < 1K
OPTICAL_TOLERANCE = 0          # 光 flit 数必须精确匹配


class CompareResult:
    """单次对比的所有结果"""
    def __init__(self, name: str):
        self.name = name
        self.omnet_time: Optional[float] = None
        self.python_time: Optional[float] = None
        self.omnet_opt_total: int = 0
        self.python_opt_total: int = 0
        self.pe_peak: dict[str, float] = {}  # "omnet", "python"
        self.pe_avg: dict[str, float] = {}
        self.router_peak: dict[str, float] = {}
        self.router_avg: dict[str, float] = {}
        self.time_series_errors: list[dict] = []  # [{pe, time, omnet, python}]
        self.errors: list[str] = []

    def ok(self) -> bool:
        return len(self.errors) == 0


# ═══════════════════════════════════════════════════════════════════
# OMNeT++ 数据提取
# ═══════════════════════════════════════════════════════════════════

def _parse_vec_headers(vec_path: Path) -> dict[int, tuple[str, int]]:
    """解析 .vec 头部的向量声明。
    返回 {vector_id: (type, pe_id)} 其中 type 是 'pe' 或 'router'。
    """
    result: dict[int, tuple[str, int]] = {}
    with open(vec_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("vector "):
                if line and line[0].isdigit():
                    break
                continue
            parts = line.split()
            vid = int(parts[1])
            name = parts[3] if len(parts) > 3 else ""
            module = parts[2] if len(parts) > 2 else ""

            if name == "pe-die-temperature":
                m = re.search(r"pe\[(\d+)\]", module)
                if m:
                    result[vid] = ("pe", int(m.group(1)))
            elif name == "router-die-temperature":
                m = re.search(r"router\[(\d+)\]", module)
                if m:
                    result[vid] = ("router", int(m.group(1)))
    return result


def _parse_vec_data(vec_path: Path,
                    headers: dict[int, tuple[str, int]]
                    ) -> dict[str, dict[int, list[float]]]:
    """解析 .vec 数据行。
    返回 {"pe": {pe_id: [temp_K, ...]}, "router": {router_id: [temp_K, ...]}}
    """
    result: dict[str, dict[int, list[float]]] = {
        "pe": defaultdict(list), "router": defaultdict(list)
    }
    with open(vec_path, "r", encoding="utf-8", errors="replace") as f:
        in_data = False
        for line in f:
            if not in_data:
                if line.startswith("vector "):
                    continue
                if line and line[0].isdigit():
                    in_data = True
                else:
                    continue
            if not line or not line[0].isdigit():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            vid = int(parts[0])
            if vid in headers:
                ttype, idx = headers[vid]
                val = float(parts[3])
                result[ttype][idx].append(val)
    return result


def _parse_vec_time_series(vec_path: Path,
                           headers: dict[int, tuple[str, int]]
                           ) -> dict[int, list[tuple[float, float]]]:
    """解析 .vec 数据行，保留时间戳。
    返回 {pe_id: [(time_us, temp_K), ...]}
    """
    result: dict[int, list[tuple[float, float]]] = defaultdict(list)
    with open(vec_path, "r", encoding="utf-8", errors="replace") as f:
        in_data = False
        for line in f:
            if not in_data:
                if line.startswith("vector "):
                    continue
                if line and line[0].isdigit():
                    in_data = True
                else:
                    continue
            if not line or not line[0].isdigit():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            vid = int(parts[0])
            if vid in headers and headers[vid][0] == "pe":
                pe_id = headers[vid][1]
                t_us = float(parts[2]) * 1e6
                val = float(parts[3])
                result[pe_id].append((t_us, val))
    return result


def extract_omnet_results(results_dir: Path, config: str) -> dict:
    """从 OMNeT++ 输出文件提取关键指标。

    返回字典：
      - time_us: 完成时间
      - optical_total: 光 flit 总数
      - pe_peak: {pe_id: temp_C}
      - pe_avg: {pe_id: temp_C}
      - router_peak: {r_id: temp_C}
      - router_avg: {r_id: temp_C}
      - pe_time_series: {pe_id: [(t_us, temp_K), ...]}
      - dvfs_data: {pe_id: [(task_id, tstart_C, dvfs), ...]}
    """
    sca_path = results_dir / f"{config}-#0.sca"
    vec_path = results_dir / f"{config}-#0.vec"

    result = {}

    # ── .sca 解析 ──
    if sca_path.exists():
        with open(sca_path, "r", encoding="utf-8", errors="replace") as f:
            optical_total = 0
            for line in f:
                if "allTasksCompletedAt" in line and line.startswith("scalar"):
                    parts = line.split()
                    result["time_us"] = float(parts[3]) * 1e6
                elif "pe-optical-packets-sent" in line and line.startswith("scalar"):
                    parts = line.split()
                    optical_total += int(float(parts[3]))
            result["optical_total"] = optical_total
    else:
        result["time_us"] = None

    # ── .vec 解析 ──
    if vec_path.exists():
        headers = _parse_vec_headers(vec_path)
        temps = _parse_vec_data(vec_path, headers)
        time_series = _parse_vec_time_series(vec_path, headers)

        result["pe_peak"] = {}
        result["pe_avg"] = {}
        for pe_id, vals in temps["pe"].items():
            temps_c = [v - 273.15 for v in vals]
            result["pe_peak"][pe_id] = max(temps_c)
            result["pe_avg"][pe_id] = sum(temps_c) / len(temps_c)

        result["router_peak"] = {}
        result["router_avg"] = {}
        for r_id, vals in temps["router"].items():
            temps_c = [v - 273.15 for v in vals]
            result["router_peak"][r_id] = max(temps_c)
            result["router_avg"][r_id] = sum(temps_c) / len(temps_c)

        result["pe_time_series"] = dict(time_series)

    return result


# ═══════════════════════════════════════════════════════════════════
# 主对比逻辑
# ═══════════════════════════════════════════════════════════════════

def compare_single(csv_path: str, config: str,
                   results_dir: str = "examples/task_driven/results"
                   ) -> CompareResult:
    """对比单个任务图的 OMNeT++ vs Python 结果。"""
    name = config.replace("ONoC_", "")
    cr = CompareResult(name)

    # 1. 提取 OMNeT++ 数据
    rd = Path(results_dir)
    omnet = extract_omnet_results(rd, config)
    cr.omnet_time = omnet.get("time_us")

    # 2. 运行 Python 仿真（含温度追踪）
    graph = TaskGraph.from_csv(csv_path)
    sim = NoCSimulator(graph, **SIM_PARAMS)

    py_temps: dict[int, list[tuple[float, float]]] = defaultdict(list)
    py_router_temps: dict[int, list[tuple[float, float]]] = defaultdict(list)
    orig_tick = sim._on_tick

    def record_tick(ev):
        orig_tick(ev)
        t = sim.t * 1e6
        for pid in range(sim.N):
            py_temps[pid].append((t, sim._T_pe[pid]))
            py_router_temps[pid].append((t, sim._T_router[pid]))

    sim._on_tick = record_tick
    sim.init()
    sim_result = sim.run(tmax=0.02, max_ev=500000)
    cr.python_time = sim_result["t"] * 1e6

    # 3. 对比完成时间
    if cr.omnet_time and cr.python_time:
        dt_pct = (cr.python_time / cr.omnet_time - 1) * 100
        if abs(dt_pct) > TIME_TOLERANCE_PCT:
            cr.errors.append(
                f"完成时间偏差 {dt_pct:+.1f}% 超出阈值 ±{TIME_TOLERANCE_PCT}%: "
                f"OMNeT={cr.omnet_time:.1f}us Python={cr.python_time:.1f}us"
            )

    # 4. 对比 PE 峰值温度
    for pe_id in sorted(omnet.get("pe_peak", {})):
        o_peak = omnet["pe_peak"][pe_id]
        p_vals = [v - 273.15 for _, v in py_temps.get(pe_id, [])]
        p_peak = max(p_vals) if p_vals else 0
        diff = p_peak - o_peak
        if abs(diff) > TEMP_PEAK_TOLERANCE_K:
            cr.errors.append(
                f"PE{pe_id} 峰值温度偏差 {diff:+.2f}K: "
                f"OMNeT={o_peak:.2f}C Python={p_peak:.2f}C"
            )
    cr.pe_peak = {
        "omnet_max": max(omnet.get("pe_peak", {}).values()) if omnet.get("pe_peak") else 0,
        "python_max": max(max(v-273.15 for _,v in py_temps[pid]) for pid in py_temps) if py_temps else 0,
    }
    if omnet.get("pe_avg"):
        o_avg = sum(omnet["pe_avg"].values()) / len(omnet["pe_avg"])
        p_all = [v-273.15 for pid in py_temps for _,v in py_temps[pid]]
        p_avg = sum(p_all) / len(p_all) if p_all else 0
        diff_avg = p_avg - o_avg
        if abs(diff_avg) > TEMP_AVG_TOLERANCE_K:
            cr.errors.append(
                f"PE 平均温度偏差 {diff_avg:+.2f}K: OMNeT={o_avg:.2f}C Python={p_avg:.2f}C"
            )
        cr.pe_avg = {"omnet": o_avg, "python": p_avg}

    # 5. 对比路由器温度
    if omnet.get("router_peak"):
        o_rpeak = max(omnet["router_peak"].values())
        o_ravg = sum(omnet["router_avg"].values()) / len(omnet["router_avg"]) if omnet.get("router_avg") else 0
        cr.router_peak = {"omnet_max": o_rpeak}
        cr.router_avg = {"omnet": o_ravg}
        if py_router_temps:
            p_all_r = [v-273.15 for pid in py_router_temps for _,v in py_router_temps[pid]]
            p_rpeak = max(p_all_r) if p_all_r else 0
            p_ravg = sum(p_all_r)/len(p_all_r) if p_all_r else 0
            cr.router_peak["python_max"] = p_rpeak
            cr.router_avg["python"] = p_ravg
            if abs(p_rpeak - o_rpeak) > TEMP_PEAK_TOLERANCE_K:
                cr.errors.append(
                    f"Router 峰值温度偏差 {p_rpeak-o_rpeak:+.2f}K: "
                    f"OMNeT={o_rpeak:.2f}C Python={p_rpeak:.2f}C"
                )

    # 6. 光 flit 数
    cr.omnet_opt_total = omnet.get("optical_total", 0)
    cr.python_opt_total = sim.ofl
    if cr.omnet_opt_total > 0 and cr.omnet_opt_total != cr.python_opt_total:
        cr.errors.append(
            f"光 flit 总数不匹配: OMNeT={cr.omnet_opt_total} Python={cr.python_opt_total}"
        )

    # 6. 对比温度时序（关键 PE，等间隔采样）
    if omnet.get("pe_time_series") and py_temps:
        key_pes = [0, 4, 8, 12]
        for pe_id in key_pes:
            o_ts = omnet["pe_time_series"].get(pe_id, [])
            p_ts = py_temps.get(pe_id, [])
            if not o_ts or not p_ts:
                continue
            # 在 5 个等间隔时间点采样
            t_min = max(o_ts[0][0], p_ts[0][0])
            t_max = min(o_ts[-1][0], p_ts[-1][0])
            for t_target_us in [0, t_min + (t_max-t_min)*0.25, t_min + (t_max-t_min)*0.5,
                                t_min + (t_max-t_min)*0.75, t_max]:
                if t_target_us <= 0:
                    continue
                o_t = min(o_ts, key=lambda x: abs(x[0] - t_target_us))
                p_t = min(p_ts, key=lambda x: abs(x[0] - t_target_us))
                diff = (p_t[1] - 273.15) - (o_t[1] - 273.15)
                if abs(diff) > TEMP_TIMESERIES_TOLERANCE_K:
                    cr.errors.append(
                        f"PE{pe_id} @t={t_target_us:.0f}us 时序温度偏差 {diff:+.2f}K: "
                        f"OMNeT={o_t[1]-273.15:.2f}C Python={p_t[1]-273.15:.2f}C"
                    )

    return cr


# ═══════════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════════

def print_report(results: list[CompareResult]):
    """打印差异报告。"""
    print("=" * 72)
    print("  OMNeT++ vs Python 对比报告")
    print("=" * 72)
    print()

    all_ok = True
    for cr in results:
        status = "PASS" if cr.ok() else "FAIL"
        if not cr.ok():
            all_ok = False
        print(f"[{status}] {cr.name}")
        print(f"  完成时间:  OMNeT={cr.omnet_time:.1f}us  Python={cr.python_time:.1f}us  "
              f"diff={(cr.python_time/cr.omnet_time-1)*100:+.1f}%" if cr.omnet_time else "  (无 OMNeT 数据)")
        if cr.pe_peak:
            o = cr.pe_peak.get("omnet_max", 0)
            p = cr.pe_peak.get("python_max", 0)
            print(f"  PE 峰值温度: OMNeT={o:.2f}C  Python={p:.2f}C  diff={p-o:+.2f}K")
        if cr.pe_avg:
            print(f"  PE 平均温度: OMNeT={cr.pe_avg['omnet']:.2f}C  Python={cr.pe_avg['python']:.2f}C  "
                  f"diff={cr.pe_avg['python']-cr.pe_avg['omnet']:+.2f}K")
        if cr.router_peak:
            o = cr.router_peak.get("omnet_max", 0)
            p = cr.router_peak.get("python_max", 0)
            print(f"  Router 峰值:  OMNeT={o:.2f}C  Python={p:.2f}C  diff={p-o:+.2f}K")
        if cr.router_avg:
            print(f"  Router 平均:  OMNeT={cr.router_avg['omnet']:.2f}C  Python={cr.router_avg['python']:.2f}C  "
                  f"diff={cr.router_avg['python']-cr.router_avg['omnet']:+.2f}K")
        if cr.omnet_opt_total:
            print(f"  光 flit 数:  OMNeT={cr.omnet_opt_total}  Python={cr.python_opt_total}")
        if cr.errors:
            print(f"  {len(cr.errors)} 个偏差:")
            for e in cr.errors[:6]:
                print(f"    - {e}")
            if len(cr.errors) > 6:
                print(f"    ... 共 {len(cr.errors)} 个")
        print()

    print("=" * 72)
    print(f"  总计: {'全部通过' if all_ok else '存在偏差，请检查'}")
    print("=" * 72)


# ═══════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════

CONFIGS = {
    "tasks_gemm_static.csv": "ONoC_GEMM",
    "tasks_mpeg4_static.csv": "ONoC_MPEG4",
    "tasks_vopd_static.csv": "ONoC_VOPD",
    "optic_static.csv": "ONoC_Optic",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="对比 OMNeT++ 与 Python NoC 仿真结果"
    )
    parser.add_argument("--csv", help="任务图 CSV 文件路径")
    parser.add_argument("--config", help="OMNeT++ config 名 (如 ONoC_GEMM)")
    parser.add_argument("--results-dir", default="examples/task_driven/results",
                        help="OMNeT++ 结果目录")
    parser.add_argument("--all", action="store_true",
                        help="对比全部四个任务图")
    args = parser.parse_args(argv)

    csv_dir = Path("examples/task_driven")

    if args.all:
        results = []
        for csv_name, config in CONFIGS.items():
            csv_path = csv_dir / csv_name
            if not csv_path.exists():
                print(f"  跳过: {csv_path} 不存在")
                continue
            print(f"  正在对比 {config} ...")
            cr = compare_single(str(csv_path), config, args.results_dir)
            results.append(cr)
        print_report(results)
    elif args.csv and args.config:
        cr = compare_single(args.csv, args.config, args.results_dir)
        print_report([cr])
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
