from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
for item in [
    ROOT,
    ROOT / "experiment",
    ROOT / "experiment" / "thermal_rc_ls_baseline",
]:
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from common import extract_original_assignment, make_original_static_tasks_mappable
from mapping.task_graph import TaskGraph, TaskNode
from thermal_rc_proxy import (
    RCObjectiveWeights,
    RCProxyConfig,
    aggregate_power,
    calibrate_or_synthetic_R,
    communication_proxy,
    proxy_score,
    synthetic_distance_decay_R,
    task_power_proxy,
    temperature_proxy,
)


class ThermalRCProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = TaskGraph.from_csv(
            ROOT / "examples" / "task_driven" / "static" / "tasks_gemm_static.csv"
        )
        self.original = extract_original_assignment(self.graph)
        make_original_static_tasks_mappable(self.graph)
        self.config = RCProxyConfig()
        self.weights = RCObjectiveWeights()
        self.task_power = task_power_proxy(self.graph, self.config)

    def test_proxy_dimensions(self) -> None:
        matrix = synthetic_distance_decay_R(self.config)
        power = aggregate_power(self.original, self.task_power, self.config)
        temps = temperature_proxy(matrix, power, self.config.Tambient)
        self.assertEqual(len(power), 16)
        self.assertEqual(len(temps), 16)
        self.assertEqual(len(matrix), 16)
        self.assertTrue(all(len(row) == 16 for row in matrix))
        score = proxy_score(
            self.graph,
            self.original,
            self.task_power,
            matrix,
            self.config,
            self.weights,
        )
        self.assertGreater(score["Tmax_proxy"], self.config.Tambient)
        self.assertGreaterEqual(score["CommProxy"], 0.0)

    def test_temperature_monotonicity(self) -> None:
        matrix = synthetic_distance_decay_R(self.config)
        power = aggregate_power(self.original, self.task_power, self.config)
        temps = temperature_proxy(matrix, power, self.config.Tambient)
        hotter_power = list(power)
        hotter_power[0] += 1.0
        hotter_temps = temperature_proxy(matrix, hotter_power, self.config.Tambient)
        for before, after in zip(temps, hotter_temps):
            self.assertGreaterEqual(after, before)

    def test_calibration_fallback_and_dimensions(self) -> None:
        baseline_power = aggregate_power(self.original, self.task_power, self.config)
        matrix, calibration = calibrate_or_synthetic_R(self.config, baseline_power, None)
        self.assertEqual(calibration.source, "synthetic_distance_decay")
        self.assertEqual(len(matrix), 16)
        synthetic_temps = temperature_proxy(matrix, baseline_power, self.config.Tambient)
        fitted, fitted_calibration = calibrate_or_synthetic_R(
            self.config,
            baseline_power,
            synthetic_temps,
        )
        self.assertEqual(len(fitted), 16)
        self.assertTrue(fitted_calibration.used_baseline_temperature)

    def test_communication_proxy_nonnegative(self) -> None:
        value = communication_proxy(self.graph, self.original, self.config.cols)
        self.assertGreaterEqual(value, 0.0)

    def test_thermal_only_objective_omits_comm_proxy(self) -> None:
        matrix = synthetic_distance_decay_R(self.config)
        weights = RCObjectiveWeights(
            objective="thermal_only",
            w_tmax=0.60,
            w_sigma=0.30,
            w_hot=0.10,
            w_comm=0.0,
        )
        score = proxy_score(
            self.graph,
            self.original,
            self.task_power,
            matrix,
            self.config,
            weights,
        )
        self.assertNotIn("CommProxy", score)
        self.assertNotIn("f_comm", score)

    def test_thermal_only_score_ignores_communication_distance(self) -> None:
        graph = TaskGraph()
        graph.tasks = {
            0: TaskNode(0, -2, 1.0, 100, successors=[1]),
            1: TaskNode(1, -2, 1.0, 0),
            2: TaskNode(2, -2, 1.0, 0),
            3: TaskNode(3, -2, 1.0, 0),
        }
        graph.tasks[1].predecessor_set.add(0)
        graph._input_order = [0, 1, 2, 3]

        assignment_near = {0: 0, 1: 1, 2: 3, 3: 2}
        assignment_far = {0: 0, 1: 3, 2: 1, 3: 2}
        task_power = {tid: 1.0 for tid in graph.mappable_task_ids}
        matrix = synthetic_distance_decay_R(self.config)
        weights = RCObjectiveWeights(
            objective="thermal_only",
            w_tmax=0.60,
            w_sigma=0.30,
            w_hot=0.10,
            w_comm=0.0,
        )
        denominators = proxy_score(
            graph,
            assignment_near,
            task_power,
            matrix,
            self.config,
            weights,
        )
        score_near = proxy_score(
            graph,
            assignment_near,
            task_power,
            matrix,
            self.config,
            weights,
            denominators=denominators,
        )
        score_far = proxy_score(
            graph,
            assignment_far,
            task_power,
            matrix,
            self.config,
            weights,
            denominators=denominators,
        )
        self.assertNotEqual(
            communication_proxy(graph, assignment_near, self.config.cols),
            communication_proxy(graph, assignment_far, self.config.cols),
        )
        self.assertEqual(score_near["temperatures_K"], score_far["temperatures_K"])
        self.assertAlmostEqual(score_near["score"], score_far["score"], places=12)


if __name__ == "__main__":
    unittest.main()
