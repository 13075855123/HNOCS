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

from common import extract_original_assignment, make_original_static_tasks_mappable, validate_assignment
from mapping.task_graph import TaskGraph
from thermal_rc_ls_mapper import ThermalRCLSMapper, ThermalRCLSSearchConfig
from thermal_rc_proxy import (
    RCObjectiveWeights,
    RCProxyConfig,
    aggregate_power,
    calibrate_or_synthetic_R,
    task_power_proxy,
)


class ThermalRCLSMapperTests(unittest.TestCase):
    def _make_mapper(
        self,
        seed: int = 7,
        objective: str = "rc",
        random_swap_rate: float = 0.25,
    ) -> ThermalRCLSMapper:
        graph = TaskGraph.from_csv(
            ROOT / "examples" / "task_driven" / "static" / "tasks_gemm_static.csv"
        )
        original = extract_original_assignment(graph)
        make_original_static_tasks_mappable(graph)
        config = RCProxyConfig()
        if objective == "thermal_only":
            weights = RCObjectiveWeights(
                objective="thermal_only",
                w_tmax=0.60,
                w_sigma=0.30,
                w_hot=0.10,
                w_comm=0.0,
            )
        else:
            weights = RCObjectiveWeights()
        powers = task_power_proxy(graph, config)
        baseline_power = aggregate_power(original, powers, config)
        matrix, _ = calibrate_or_synthetic_R(config, baseline_power, None)
        search = ThermalRCLSSearchConfig(
            seed=seed,
            init_mode="random_spread",
            max_iter=40,
            no_improve_patience=10,
            random_swap_rate=random_swap_rate,
        )
        return ThermalRCLSMapper(
            graph,
            original,
            powers,
            matrix,
            config,
            weights,
            search,
        )

    def test_mapping_validity(self) -> None:
        mapper = self._make_mapper()
        result = mapper.run()
        validate_assignment(mapper.graph, result.assignment, mapper.proxy_config.num_pes)
        self.assertGreaterEqual(len(result.history), 1)
        self.assertIn("thermal_rc_ls", result.proxy)

    def test_deterministic_seed(self) -> None:
        first = self._make_mapper(seed=11).run()
        second = self._make_mapper(seed=11).run()
        self.assertEqual(first.assignment, second.assignment)
        self.assertEqual(
            first.history[-1]["best_score"],
            second.history[-1]["best_score"],
        )

    def test_thermal_only_deterministic_without_random_swaps(self) -> None:
        first_mapper = self._make_mapper(
            seed=19,
            objective="thermal_only",
            random_swap_rate=0.0,
        )
        second_mapper = self._make_mapper(
            seed=19,
            objective="thermal_only",
            random_swap_rate=0.0,
        )
        first = first_mapper.run()
        second = second_mapper.run()
        self.assertEqual(first.assignment, second.assignment)
        self.assertEqual(first.history, second.history)
        self.assertIn("thermal_only_rc_ls", first.proxy)
        self.assertEqual(first.proxy["method"], "thermal_only_rc_ls")
        self.assertEqual(first.proxy["method_label"], "ThermalOnly-RC-LS")
        self.assertNotIn("CommProxy", first.proxy["thermal_only_rc_ls"])
        validate_assignment(first_mapper.graph, first.assignment, first_mapper.proxy_config.num_pes)

    def test_thermal_only_mapping_validity(self) -> None:
        mapper = self._make_mapper(
            seed=23,
            objective="thermal_only",
            random_swap_rate=0.0,
        )
        result = mapper.run()
        validate_assignment(mapper.graph, result.assignment, mapper.proxy_config.num_pes)


if __name__ == "__main__":
    unittest.main()
