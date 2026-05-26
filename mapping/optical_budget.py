"""
Optical budget model — Python replica of OMNeT++ OpticalDeviceModel + temperature effects.

Mirrors:
  OpticalDeviceModel.cc  — computeDeviceLevelBudget()
  OpticalDeviceModel.h   — device types, per-wavelength params, SOA ASE noise
  LogicalTopologyManager.getDeviceLevelPathMetrics() — path builder + budget caller

Provides:
  OpticalBudgetParams   — configurable device parameters (IL, SOA gain, etc.)
  OpticalBudget         — end-to-end budget calculator with temperature-aware effects
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# Device types (match OpticalDeviceModel.h enum)
# ============================================================================
class DevType:
    NONE = 0
    MODULATOR = 1
    RING_THROUGH = 2
    RING_DROP = 3
    WAVEGUIDE = 4
    WAVEGUIDE_BEND = 5
    MUX = 6
    DEMUX = 7
    SOA = 8
    PHOTODETECTOR = 9


# ============================================================================
# Per-device, per-wavelength parameters (match DevicePerWavelengthParams)
# ============================================================================
@dataclass
class DeviceParams:
    """Default silicon photonic device parameters (literature-based)."""
    insertionLoss_dB: float = 0.0
    crosstalkToAdjacent_dB: float = -99.0
    crosstalkToNonAdjacent_dB: float = -99.0
    soaGain_dB: float = 10.0
    soaNoiseFigure_dB: float = 7.0
    soaSaturationPower_dBm: float = 30.0
    pdResponsivity_AW: float = 1.0
    pdSensitivity_dBm: float = -15.0
    modulatorEfficiency_dB: float = 0.0


# Default per-wavelength parameters for each device type
DEFAULT_PARAMS = {
    DevType.MODULATOR:      DeviceParams(insertionLoss_dB=2.0),
    DevType.RING_THROUGH:   DeviceParams(insertionLoss_dB=0.01),
    DevType.RING_DROP:      DeviceParams(insertionLoss_dB=0.5),
    DevType.WAVEGUIDE:      DeviceParams(insertionLoss_dB=2.0),   # dB/cm
    DevType.WAVEGUIDE_BEND: DeviceParams(insertionLoss_dB=0.005),
    DevType.MUX:            DeviceParams(insertionLoss_dB=1.0),
    DevType.DEMUX:          DeviceParams(insertionLoss_dB=1.0),
    DevType.SOA:            DeviceParams(soaGain_dB=10.0, soaNoiseFigure_dB=7.0),
    DevType.PHOTODETECTOR:  DeviceParams(insertionLoss_dB=1.0, pdResponsivity_AW=1.0),
}


# ============================================================================
# Global constraints (match OpticalBudgetConstraints)
# ============================================================================
@dataclass
class OpticalBudgetParams:
    """Configurable optical budget constraints, mirrored from OMNeT++ INI."""
    launchPower_dBm: float = 0.0
    receiverSensitivity_dBm: float = -18.0
    thermalNoiseFloor_dBm: float = -50.0
    modulationBitsPerSymbol: int = 2            # 1=OOK, 2=PAM4
    enableSOA: bool = True
    totalWavelengths: int = 16
    # Waveguide distances (cm)
    sourceToModulator_cm: float = 0.01
    modulatorToRouter_cm: float = 0.03
    routerToRouter_cm: float = 0.15
    routerToDemodulator_cm: float = 0.03
    demodulatorToPD_cm: float = 0.005
    # Temperature-aware
    enableThermalEffects: bool = False
    Tambient_K: float = 318.15
    thermoOpticCoeff_nm_per_K: float = 0.1
    tuningEfficiency_mW_per_nm: float = 0.5
    ringIL_TempCoeff_dB_per_K: float = 0.02
    soaGain_TempCoeff_dB_per_K: float = 0.05
    waveguideLoss_TempCoeff_dB_per_cm_per_K: float = 0.001


# ============================================================================
# Optical path segment (match OpticalDeviceSegment)
# ============================================================================
@dataclass
class Segment:
    devType: int
    deviceIndex: int = -1
    waveguideLength_cm: float = 0.0
    wavelengthIndex: int = 1


# ============================================================================
# Optical budget result
# ============================================================================
@dataclass
class BudgetResult:
    totalLoss_dB: float = 0.0
    receivedPower_dBm: float = 0.0
    signalMargin_dB: float = 0.0
    estimatedSNR_dB: float = 99.0
    estimatedBER: float = 0.0
    meetsSensitivity: bool = True
    totalTuningPower_mW: float = 0.0
    maxRingDetuning_nm: float = 0.0
    tempAdjustedLoss_dB: float = 0.0


# ============================================================================
# Helper functions
# ============================================================================
def _params(devType: int, wl: int = 1) -> DeviceParams:
    return DEFAULT_PARAMS.get(devType, DeviceParams())


def _computePAM4BER(snr_dB: float) -> float:
    if snr_dB <= -99.0:
        return 0.5
    snr_linear = 10.0 ** (snr_dB / 10.0)
    x = math.sqrt(snr_linear / 10.0)
    return 0.75 * math.erfc(x)


def _computeSOAASE(gain_dB: float, nf_dB: float, bw_hz: float = 30e9) -> float:
    """ASE noise power in dBm (match OMNeT++ computeSOAASENoisePower_dBm)."""
    gain_lin = 10.0 ** (gain_dB / 10.0)
    nf_lin = 10.0 ** (nf_dB / 10.0)
    h = 6.62607015e-34
    nu = 193.4e12
    ase_watts = h * nu * (gain_lin - 1.0) * nf_lin * bw_hz
    if ase_watts <= 0.0:
        return -199.0
    return 10.0 * math.log10(ase_watts * 1000.0)


# ============================================================================
# Mesh XY path helper
# ============================================================================
def mesh_xy_path(src: int, dst: int, cols: int, rows: int) -> list[int]:
    """Build XY-routed path nodes (routers) from src to dst (no wrap-around)."""
    if src == dst:
        return []
    sr, sc = divmod(src, cols)
    dr, dc = divmod(dst, cols)
    path = []
    cur = src
    cr, cc = sr, sc
    # X direction first
    while cc != dc:
        cc = cc + 1 if dc > cc else cc - 1
        cur = cr * cols + cc
        path.append(cur)
    # Y direction
    while cr != dr:
        cr = cr + 1 if dr > cr else cr - 1
        cur = cr * cols + cc
        path.append(cur)
    return path


def mesh_hop_count(src: int, dst: int, cols: int) -> int:
    sr, sc = divmod(src, cols)
    dr, dc = divmod(dst, cols)
    return abs(sr - dr) + abs(sc - dc)


# ============================================================================
# Main budget computation
# ============================================================================
def compute_optical_budget(
    src_id: int,
    dst_id: int,
    wavelengths: list[int],
    node_temperatures: dict[int, float],   # node_id -> temperature_K
    params: OpticalBudgetParams,
    cols: int = 4,
    rows: int = 4,
) -> BudgetResult:
    """
    Compute end-to-end optical budget for a src→dst path at given wavelengths.
    Mirrors LogicalTopologyManager.getDeviceLevelPathMetrics() + computeDeviceLevelBudget().
    """
    result = BudgetResult()
    totalWL = params.totalWavelengths
    path_nodes = mesh_xy_path(src_id, dst_id, cols, rows)
    hop_count = len(path_nodes)

    if not wavelengths:
        wavelengths = [1]

    for wl in wavelengths:
        segments: list[Segment] = []

        # ---- Modulator chain ----
        for t in range(wl - 1):
            segments.append(Segment(DevType.RING_THROUGH, src_id * 1000 + t, wavelengthIndex=wl))
        segments.append(Segment(DevType.RING_DROP, src_id * 1000 + wl, wavelengthIndex=wl))
        segments.append(Segment(DevType.WAVEGUIDE, src_id * 10, params.modulatorToRouter_cm, wl))

        # ---- Router hops ----
        prev_node = src_id
        for next_node in path_nodes:
            # Compute port directions
            pr, pc = divmod(prev_node, cols)
            nr, nc = divmod(next_node, cols)
            dx = nc - pc
            dy = nr - pr
            # Map to port
            if dx == 0 and dy == -1:   inPort, outPort = 2, 0  # N→S
            elif dx == 0 and dy == 1:  inPort, outPort = 0, 2  # S→N
            elif dx == -1 and dy == 0: inPort, outPort = 3, 1  # W→E
            elif dx == 1 and dy == 0:  inPort, outPort = 1, 3  # E→W
            else:
                if dy < 0:       inPort, outPort = 0, 2
                elif dy > 0:     inPort, outPort = 2, 0
                elif dx < 0:     inPort, outPort = 1, 3
                else:            inPort, outPort = 3, 1

            # First hop: source injection (Local=0 → outPort)
            is_first = (prev_node == src_id)
            if is_first:
                inPort = 0

            # Through rings (count depends on wavelength)
            through_count = wl - 1  # simplified model
            for t in range(through_count):
                idx = prev_node * 1000 + inPort * 100 + outPort * 10 + t
                segments.append(Segment(DevType.RING_THROUGH, idx, wavelengthIndex=wl))
            # Drop ring
            idx = prev_node * 1000 + inPort * 100 + outPort * 10 + through_count
            segments.append(Segment(DevType.RING_DROP, idx, wavelengthIndex=wl))

            # Inter-router waveguide
            segments.append(Segment(DevType.WAVEGUIDE, prev_node * 10 + next_node,
                                    params.routerToRouter_cm, wl))
            # SOA after each router
            if params.enableSOA:
                segments.append(Segment(DevType.SOA, next_node, wavelengthIndex=wl))

            prev_node = next_node

        # ---- Demodulator chain ----
        for t in range(wl - 1):
            segments.append(Segment(DevType.RING_THROUGH, dst_id * 1000 + 100 + t, wavelengthIndex=wl))
        segments.append(Segment(DevType.RING_DROP, dst_id * 1000 + 100 + wl, wavelengthIndex=wl))
        segments.append(Segment(DevType.WAVEGUIDE, dst_id * 10 + 1, params.demodulatorToPD_cm, wl))
        segments.append(Segment(DevType.PHOTODETECTOR, dst_id, wavelengthIndex=wl))

        # ---- Accumulate losses ----
        currentPower_dBm = params.launchPower_dBm
        accumulatedLoss_dB = 0.0
        accumulatedNoise_mW = 10.0 ** (params.thermalNoiseFloor_dBm / 10.0)

        for seg in segments:
            dp = _params(seg.devType, wl)
            segLoss_dB = 0.0

            if seg.devType == DevType.NONE:
                pass
            elif seg.devType == DevType.WAVEGUIDE:
                segLoss_dB = dp.insertionLoss_dB * seg.waveguideLength_cm
            elif seg.devType == DevType.SOA:
                segLoss_dB = -dp.soaGain_dB
                ase = _computeSOAASE(dp.soaGain_dB, dp.soaNoiseFigure_dB)
                accumulatedNoise_mW += 10.0 ** (ase / 10.0)
            else:
                segLoss_dB = dp.insertionLoss_dB

            # Temperature-aware adjustment
            if params.enableThermalEffects:
                node_id = seg.deviceIndex // 1000
                T_K = node_temperatures.get(node_id, params.Tambient_K)
                deltaT = T_K - params.Tambient_K

                if seg.devType in (DevType.RING_THROUGH, DevType.RING_DROP):
                    detuning = params.thermoOpticCoeff_nm_per_K * deltaT
                    abs_det = abs(detuning)
                    segLoss_dB += params.ringIL_TempCoeff_dB_per_K * abs_det
                    result.totalTuningPower_mW += params.tuningEfficiency_mW_per_nm * abs_det
                    if abs_det > result.maxRingDetuning_nm:
                        result.maxRingDetuning_nm = abs_det
                elif seg.devType == DevType.SOA:
                    segLoss_dB += params.soaGain_TempCoeff_dB_per_K * max(0.0, deltaT)
                elif seg.devType == DevType.WAVEGUIDE:
                    segLoss_dB += params.waveguideLoss_TempCoeff_dB_per_cm_per_K * seg.waveguideLength_cm * max(0.0, deltaT)

                result.tempAdjustedLoss_dB += (segLoss_dB - dp.insertionLoss_dB)  # approximate

            currentPower_dBm -= segLoss_dB
            accumulatedLoss_dB += segLoss_dB

        # SNR and BER
        noiseTotal_mW = accumulatedNoise_mW
        signalPower_mW = 10.0 ** (currentPower_dBm / 10.0)
        snr_linear = signalPower_mW / noiseTotal_mW if noiseTotal_mW > 0 else 1e12
        snr_dB = 10.0 * math.log10(snr_linear)
        ber = _computePAM4BER(snr_dB)

        result.totalLoss_dB = max(result.totalLoss_dB, accumulatedLoss_dB)
        result.receivedPower_dBm = min(result.receivedPower_dBm, currentPower_dBm)
        result.estimatedSNR_dB = min(result.estimatedSNR_dB, snr_dB)
        result.estimatedBER = max(result.estimatedBER, ber)

    result.signalMargin_dB = result.receivedPower_dBm - params.receiverSensitivity_dBm
    result.meetsSensitivity = result.receivedPower_dBm >= params.receiverSensitivity_dBm

    return result
