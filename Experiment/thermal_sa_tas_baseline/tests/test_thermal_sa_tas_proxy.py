from __future__ import annotations

import sys
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
_PROJ = _HERE.parents[3]
_EXP = _PROJ / "experiment"
_PKG = _EXP / "thermal_sa_tas_baseline"
for _d in (_PROJ, _EXP, _PKG):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from mapping.task_graph import TaskGraph
from thermal_rc_ls_baseline.common import extract_original_assignment, make_original_static_tasks_mappable
from thermal_rc_ls_baseline.thermal_rc_proxy import (
    RCProxyConfig,
    aggregate_power,
    calibrate_or_synthetic_R,
    task_power_proxy,
    temperature_proxy,
)
from thermal_sa_tas_proxy import (
    TASScheduleConfig,
    TASObjectiveWeights,
    edge_delay_ns,
    list_schedule_proxy,
    tas_proxy_score,
)


class ThermalSATASProxyTests(unittest.TestCase):
    def _fixture(self):
        graph = TaskGraph.from_csv(_PROJ / "examples/task_driven/static/tasks_gemm_static.csv")
        original = extract_original_assignment(graph)
        make_original_static_tasks_mappable(graph)
        config = RCProxyConfig()
        powers = task_power_proxy(graph, config)
        baseline_power = aggregate_power(original, powers, config)
        matrix, _ = calibrate_or_synthetic_R(config, baseline_power, None)
        return graph, original, config, powers, matrix

    def test_schedule_respects_dependencies_and_pe_serial_order(self) -> None:
        graph, original, config, _, _ = self._fixture()
        schedule_config = TASScheduleConfig()
        payload = list_schedule_proxy(graph, original, config.rows, config.cols, schedule_config)
        rows = payload["schedule"]
        by_task = {int(row["task_id"]): row for row in rows}
        by_pe: dict[int, list[dict]] = {}
        for row in rows:
            by_pe.setdefault(int(row["pe_id"]), []).append(row)

        for tid, row in by_task.items():
            node = graph.tasks[tid]
            start = float(row["start_time_proxy_ns"])
            for pred_id in node.predecessor_set:
                pred = graph.tasks.get(pred_id)
                if pred is None or pred.is_gb_task:
                    continue
                pred_finish = float(by_task[pred_id]["finish_time_proxy_ns"])
                delay = edge_delay_ns(graph, original, pred_id, tid, config.cols, schedule_config)
                self.assertGreaterEqual(start + 1e-9, pred_finish + delay)

        for pe_rows in by_pe.values():
            ordered = sorted(pe_rows, key=lambda item: float(item["start_time_proxy_ns"]))
            for prev, nxt in zip(ordered, ordered[1:]):
                self.assertGreaterEqual(
                    float(nxt["start_time_proxy_ns"]) + 1e-9,
                    float(prev["finish_time_proxy_ns"]),
                )

    def test_thermal_proxy_monotonicity_for_added_power(self) -> None:
        graph, original, config, powers, matrix = self._fixture()
        base_power = aggregate_power(original, powers, config)
        hotter_power = list(base_power)
        hotter_power[0] += 1.0
        base_temp = temperature_proxy(matrix, base_power, config.Tambient)
        hotter_temp = temperature_proxy(matrix, hotter_power, config.Tambient)
        self.assertGreaterEqual(hotter_temp[0], base_temp[0])

    def test_proxy_score_contains_tas_terms(self) -> None:
        graph, original, config, powers, matrix = self._fixture()
        score = tas_proxy_score(
            graph,
            original,
            powers,
            matrix,
            config,
            TASScheduleConfig(),
            TASObjectiveWeights(),
        )
        self.assertIn("Tmax_proxy", score)
        self.assertIn("SigmaT_proxy", score)
        self.assertIn("HotCount_proxy", score)
        self.assertIn("MakespanProxy_ns", score)
        self.assertIn("PeakWindowEnergyProxy", score)
        self.assertIn("PeakWindowSigmaProxy", score)
        self.assertIn("NeighborPeakWindowEnergyProxy", score)
        self.assertIn("schedule", score)
        self.assertGreater(score["MakespanProxy_ns"], 0.0)
        self.assertGreater(score["PeakWindowEnergyProxy"], 0.0)


if __name__ == "__main__":
    unittest.main()
