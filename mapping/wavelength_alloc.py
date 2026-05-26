"""
Wavelength allocation — edge occupancy table + selection strategies.

Mirrors LogicalTopologyManager:
  - opticalEdgeOccupancy   — per-edge [spatial][wavelength] = owner pktId
  - tryAllocateOpticalPathForPacket()  — wavelength selection + occupancy
  - reserveOpticalPathForSetup()       — token generation + allocation
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .optical_budget import (
    compute_optical_budget,
    mesh_xy_path,
    BudgetResult,
    OpticalBudgetParams,
)


@dataclass
class WavelengthAllocator:
    """Manages optical edge occupancy and wavelength selection."""
    rows: int = 4
    cols: int = 4
    max_wavelengths: int = 16
    num_spatial_channels: int = 2
    default_required_wavelengths: int = 2
    strategy: str = "lowest"   # "lowest" or "thermal"
    budget_params: OpticalBudgetParams = field(default_factory=OpticalBudgetParams)
    node_temperatures: dict[int, float] = field(default_factory=dict)

    # Internal state
    _edge_occ: dict[tuple[int, int], list[list[int]]] = field(default_factory=dict, repr=False)
    _next_token: int = 1
    _evaluations: int = 0

    # Per-pair wavelength overrides: src->dst → count
    pair_wavelengths: dict[tuple[int, int], int] = field(default_factory=dict)

    def reset(self):
        self._edge_occ.clear()
        self._next_token = 1
        self._evaluations = 0

    def _edge_key(self, a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    def _get_occ(self, edge: tuple[int, int], spatial: int) -> list[int]:
        if edge not in self._edge_occ:
            self._edge_occ[edge] = []
        occ = self._edge_occ[edge]
        while len(occ) <= spatial:
            occ.append([])
        ch = occ[spatial]
        if len(ch) < self.max_wavelengths:
            ch.extend([0] * (self.max_wavelengths - len(ch)))
        return ch

    def _is_wl_free_on_path(self, path_edges: list[tuple[int, int]],
                            spatial: int, wl_idx: int) -> bool:
        for edge in path_edges:
            ch = self._get_occ(edge, spatial)
            if ch[wl_idx] != 0:
                return False
        return True

    def _build_path_edges(self, src: int, dst: int) -> list[tuple[int, int]]:
        path = mesh_xy_path(src, dst, self.cols, self.rows)
        edges = []
        cur = src
        for nxt in path:
            edges.append(self._edge_key(cur, nxt))
            cur = nxt
        return edges

    def _get_required_wavelengths(self, src: int, dst: int) -> int:
        key = (src, dst)
        if key in self.pair_wavelengths:
            return self.pair_wavelengths[key]
        return self.default_required_wavelengths

    def allocate(self, src: int, dst: int) -> tuple[bool, int, int, list[int]]:
        """
        Allocate wavelengths for src→dst.
        Returns (success, token, spatial_channel, selected_wavelengths).
        """
        path_edges = self._build_path_edges(src, dst)
        required = self._get_required_wavelengths(src, dst)
        required = min(required, self.max_wavelengths)
        use_thermal = (self.strategy == "thermal")

        best_spatial = -1
        best_wls: list[int] = []
        best_cost = float('inf')

        for spatial in range(self.num_spatial_channels):
            # Collect free wavelengths
            free_wls = []
            for wl_idx in range(self.max_wavelengths):
                if self._is_wl_free_on_path(path_edges, spatial, wl_idx):
                    free_wls.append(wl_idx + 1)

            if len(free_wls) < required:
                continue

            if not use_thermal:
                # Lowest-index first
                candidate = free_wls[:required]
                cost = sum(candidate)  # lower = better
                if cost < best_cost:
                    best_cost = cost
                    best_spatial = spatial
                    best_wls = candidate
            else:
                # Thermal-aware: evaluate consecutive combinations
                max_eval = min(len(free_wls) * 4, 200)
                evaluated = 0
                for start in range(len(free_wls) - required + 1):
                    if evaluated >= max_eval:
                        break
                    candidate = free_wls[start:start + required]
                    budget = compute_optical_budget(
                        src, dst, candidate, self.node_temperatures,
                        self.budget_params, self.cols, self.rows)
                    # Cost = tuning power + small loss penalty
                    cost = budget.totalTuningPower_mW + budget.totalLoss_dB * 0.05
                    evaluated += 1
                    self._evaluations += 1
                    if cost < best_cost:
                        best_cost = cost
                        best_spatial = spatial
                        best_wls = candidate

        if best_spatial < 0:
            return False, 0, -1, []

        # Occupy
        token = self._next_token
        self._next_token += 1
        for edge in path_edges:
            ch = self._get_occ(edge, best_spatial)
            for wl in best_wls:
                ch[wl - 1] = token

        return True, token, best_spatial, best_wls

    def release(self, token: int):
        """Release all wavelengths occupied by a given token."""
        for edge_key in list(self._edge_occ.keys()):
            for spatial in range(len(self._edge_occ[edge_key])):
                ch = self._edge_occ[edge_key][spatial]
                for i in range(len(ch)):
                    if ch[i] == token:
                        ch[i] = 0


@dataclass
class WavelengthExperiment:
    """Compare lowest vs thermal wavelength strategies for a set of communication pairs."""
    alloc_lowest: WavelengthAllocator = field(default_factory=WavelengthAllocator)
    alloc_thermal: WavelengthAllocator = field(default_factory=WavelengthAllocator)

    def run_comparison(
        self,
        communications: list[tuple[int, int]],  # (src, dst) pairs
        node_temps: dict[int, float],
        rows: int = 4, cols: int = 4,
    ) -> dict:
        """
        Run both strategies on the same communication set and return comparison stats.
        """
        results = {"lowest": {"tuning_mW": 0.0, "loss_dB": 0.0, "evals": 0, "snr_dB": 0.0,
                              "success": 0, "failed": 0},
                   "thermal": {"tuning_mW": 0.0, "loss_dB": 0.0, "evals": 0, "snr_dB": 0.0,
                                "success": 0, "failed": 0}}

        for strategy, alloc in [("lowest", self.alloc_lowest), ("thermal", self.alloc_thermal)]:
            alloc.reset()
            alloc.strategy = strategy
            alloc.node_temperatures = node_temps
            alloc.rows = rows
            alloc.cols = cols
            total_tuning = 0.0
            total_loss = 0.0
            total_snr = 0.0
            success_count = 0
            for src, dst in communications:
                ok, token, spatial, wls = alloc.allocate(src, dst)
                if ok:
                    budget = compute_optical_budget(
                        src, dst, wls, node_temps, alloc.budget_params, cols, rows)
                    total_tuning += budget.totalTuningPower_mW
                    total_loss += budget.totalLoss_dB
                    total_snr += budget.estimatedSNR_dB
                    success_count += 1
                    alloc.release(token)
            n = max(success_count, 1)
            r = results[strategy]
            r["tuning_mW"] = total_tuning / n
            r["loss_dB"] = total_loss / n
            r["snr_dB"] = total_snr / n
            r["evals"] = alloc._evaluations
            r["success"] = success_count
            r["failed"] = len(communications) - success_count

        return results
