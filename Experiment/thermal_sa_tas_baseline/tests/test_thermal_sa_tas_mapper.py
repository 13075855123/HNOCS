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
from thermal_rc_ls_baseline.common import (
    extract_original_assignment,
    make_original_static_tasks_mappable,
    validate_assignment,
)
from thermal_rc_ls_baseline.thermal_rc_proxy import (
    RCProxyConfig,
    aggregate_power,
    calibrate_or_synthetic_R,
    task_power_proxy,
)
from thermal_sa_tas_mapper import ThermalSATASMapper, ThermalSATASearchConfig
from thermal_sa_tas_proxy import TASScheduleConfig, TASObjectiveWeights, tas_proxy_score


class ThermalSATASMapperTests(unittest.TestCase):
    def _make_mapper(self, seed: int = 42, max_total_iter: int = 40) -> ThermalSATASMapper:
        graph = TaskGraph.from_csv(_PROJ / "examples/task_driven/static/tasks_gemm_static.csv")
        original = extract_original_assignment(graph)
        make_original_static_tasks_mappable(graph)
        config = RCProxyConfig()
        powers = task_power_proxy(graph, config)
        baseline_power = aggregate_power(original, powers, config)
        matrix, _ = calibrate_or_synthetic_R(config, baseline_power, None)
        schedule_config = TASScheduleConfig()
        weights = TASObjectiveWeights()
        original_score = tas_proxy_score(
            graph,
            original,
            powers,
            matrix,
            config,
            schedule_config,
            weights,
        )
        denominators = {
            "Tmax_proxy": float(original_score["Tmax_proxy"]),
            "SigmaT_proxy": float(original_score["SigmaT_proxy"]),
            "HotCount_proxy": float(original_score["HotCount_proxy"]),
            "MakespanProxy_ns": float(original_score["MakespanProxy_ns"]),
            "CommProxy": float(original_score["CommProxy"]),
            "MaxLoadProxy_ns": float(original_score["MaxLoadProxy_ns"]),
            "LoadImbalanceProxy": float(original_score["LoadImbalanceProxy"]),
            "PeakWindowEnergyProxy": float(original_score["PeakWindowEnergyProxy"]),
            "PeakWindowSigmaProxy": float(original_score["PeakWindowSigmaProxy"]),
            "NeighborPeakWindowEnergyProxy": float(original_score["NeighborPeakWindowEnergyProxy"]),
        }
        search = ThermalSATASearchConfig(
            seed=seed,
            max_total_iter=max_total_iter,
            restarts=1,
            iterations_per_temperature=4,
            no_improve_patience=max_total_iter + 1,
        )
        return ThermalSATASMapper(
            graph,
            original,
            powers,
            matrix,
            config,
            schedule_config,
            weights,
            search,
            denominators,
        )

    def test_mapping_validity(self) -> None:
        mapper = self._make_mapper(max_total_iter=20)
        result = mapper.run()
        validate_assignment(mapper.graph, result.assignment, mapper.proxy_config.num_pes)
        self.assertGreaterEqual(len(result.history), 1)
        self.assertIn("thermal_sa_tas", result.proxy)
        self.assertIn("final_selection", result.proxy["thermal_sa_tas"])
        self.assertGreater(len(result.schedule), 0)

    def test_deterministic_seed(self) -> None:
        first = self._make_mapper(seed=11, max_total_iter=30).run()
        second = self._make_mapper(seed=11, max_total_iter=30).run()
        self.assertEqual(first.assignment, second.assignment)
        self.assertEqual(first.history, second.history)

    def test_cooling_history_decreases_temperature(self) -> None:
        result = self._make_mapper(seed=7, max_total_iter=16).run()
        temps = [row["temperature"] for row in result.history]
        self.assertGreater(len(set(temps)), 1)
        self.assertGreater(temps[0], temps[-1])
        self.assertTrue(all("accepted" in row for row in result.history))


if __name__ == "__main__":
    unittest.main()
