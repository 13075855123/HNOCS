"""
Optical budget model — Python replica of OMNeT++ OpticalDeviceModel + temperature effects.

Mirrors:
  OpticalDeviceModel.cc  — computeDeviceLevelBudget()
  OpticalDeviceModel.h   — device types, per-wavelength params, SOA ASE noise
  LogicalTopologyManager.getDeviceLevelPathMetrics() — path builder + budget caller

Key updates matching OMNeT++ (2026-05):
  - Per-branch splitter power: launchPower - coupling - 10*log10(N_branches) - excess
  - Waveguide crossing loss (DEV_WAVEGUIDE_CROSSING)
  - Temperature-aware effects: ring detuning, SOA gain temp coeff, waveguide loss temp coeff
  - SOA ASE noise accumulation across path
  - PAM4 BER estimation
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
    WAVEGUIDE_CROSSING = 10  # matches OMNeT++ DEV_WAVEGUIDE_CROSSING


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
    DevType.MODULATOR:           DeviceParams(insertionLoss_dB=2.0),
    DevType.RING_THROUGH:        DeviceParams(insertionLoss_dB=0.01),
    DevType.RING_DROP:           DeviceParams(insertionLoss_dB=0.5),
    DevType.WAVEGUIDE:           DeviceParams(insertionLoss_dB=2.0),   # dB/cm
    DevType.WAVEGUIDE_BEND:      DeviceParams(insertionLoss_dB=0.005),
    DevType.WAVEGUIDE_CROSSING:  DeviceParams(insertionLoss_dB=0.05,
                                              crosstalkToAdjacent_dB=-30.0),
    DevType.MUX:                 DeviceParams(insertionLoss_dB=1.0),
    DevType.DEMUX:               DeviceParams(insertionLoss_dB=1.0),
    DevType.SOA:                 DeviceParams(soaGain_dB=10.0, soaNoiseFigure_dB=7.0),
    DevType.PHOTODETECTOR:       DeviceParams(insertionLoss_dB=1.0, pdResponsivity_AW=1.0),
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
    # Splitter parameters (matches OMNeT++ LTM)
    numSplitBranches: int = 16                  # 1×N splitter (N = num PEs)
    splitterExcessLoss_dB: float = 1.0
    couplingLoss_dB: float = 3.0                # grating coupler
    waveguideMaxPower_dBm: float = 14.0
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

    def get_per_branch_power_dBm(self) -> float:
        """Compute per-branch launch power after splitter.
        Matches LTM::getDeviceLevelPathMetrics() splitter computation.
        """
        if self.numSplitBranches <= 1:
            return self.launchPower_dBm
        return (self.launchPower_dBm
                - self.couplingLoss_dB
                - 10.0 * math.log10(float(self.numSplitBranches))
                - self.splitterExcessLoss_dB)


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
    totalCrosstalk_dB: float = 0.0
    receivedPower_dBm: float = 0.0
    signalMargin_dB: float = 0.0
    estimatedSNR_dB: float = 99.0
    estimatedBER: float = 0.0
    meetsSensitivity: bool = True
    totalTuningPower_mW: float = 0.0
    maxRingDetuning_nm: float = 0.0
    tempAdjustedLoss_dB: float = 0.0
    # Per-wavelength detail
    perWavelengthLoss_dB: list[float] = field(default_factory=list)
    perWavelengthRxPower_dBm: list[float] = field(default_factory=list)
    perWavelengthSNR_dB: list[float] = field(default_factory=list)
    # Device-type breakdown
    modulatorLoss_dB: float = 0.0
    muxDemuxLoss_dB: float = 0.0
    waveguidePropagationLoss_dB: float = 0.0
    waveguideBendingLoss_dB: float = 0.0
    waveguideCrossingLoss_dB: float = 0.0
    ringThroughLoss_dB: float = 0.0
    ringDropLoss_dB: float = 0.0
    soaGainTotal_dB: float = 0.0
    detectorLoss_dB: float = 0.0


# ============================================================================
# Helper functions
# ============================================================================
def _params(devType: int, wl: int = 1) -> DeviceParams:
    return DEFAULT_PARAMS.get(devType, DeviceParams())


def _computePAM4BER(snr_dB: float) -> float:
    """PAM4 BER from SNR. Matches OMNeT++ computePAM4BER()."""
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
# Determine port directions for a router hop (matches OMNeT++ logic)
# ============================================================================
def _port_direction(prev: int, nxt: int, cols: int, rows: int) -> tuple[int, int]:
    """Return (inPort, outPort) for prev→nxt hop.
    Port mapping: 0=Local, 1=East, 2=South, 3=West, 4=North
    (Simplified: 0=Local/Core, 1=East→West, 2=South→North, 3=West→East, 4=North→South)
    """
    pr, pc = divmod(prev, cols)
    nr, nc = divmod(nxt, cols)
    dx = nc - pc
    dy = nr - pr

    # Map delta to port
    # Match OMNeT++: Port 0=Local,1=West,2=North,3=East,4=South
    if dx == 0 and dy == -1:
        return 2, 4     # North → South (inPort=North, outPort=South)
    elif dx == 0 and dy == 1:
        return 4, 2     # South → North
    elif dx == -1 and dy == 0:
        return 3, 1     # East → West
    elif dx == 1 and dy == 0:
        return 1, 3     # West → East
    else:
        # Fallback
        if dy < 0:
            return 4, 2
        elif dy > 0:
            return 2, 4
        elif dx < 0:
            return 3, 1
        else:
            return 1, 3


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

    Includes:
      - Per-branch splitter power computation
      - Waveguide crossing loss at each intermediate router
      - Temperature-aware ring detuning, SOA gain, waveguide loss
      - SOA ASE noise accumulation
      - PAM4 BER estimation
    """
    result = BudgetResult()
    totalWL = params.totalWavelengths
    path_nodes = mesh_xy_path(src_id, dst_id, cols, rows)
    hop_count = len(path_nodes)

    if not wavelengths:
        wavelengths = [1]

    # Per-branch launch power (after splitter)
    per_branch_power_dBm = params.get_per_branch_power_dBm()

    for wl in wavelengths:
        segments: list[Segment] = []

        # ---- Modulator chain at source ----
        # Waveguide: source to modulator
        segments.append(Segment(DevType.WAVEGUIDE, src_id * 10,
                                params.sourceToModulator_cm, wl))
        # Through rings: (wl - 1) through passes
        for t in range(wl - 1):
            segments.append(Segment(DevType.RING_THROUGH,
                                    src_id * 1000 + t, wavelengthIndex=wl))
        # Drop ring: 1 drop
        segments.append(Segment(DevType.RING_DROP,
                                src_id * 1000 + wl, wavelengthIndex=wl))
        # Waveguide: modulator to router core port
        segments.append(Segment(DevType.WAVEGUIDE, src_id * 10 + 1,
                                params.modulatorToRouter_cm, wl))

        # ---- Router hops ----
        prev_node = src_id
        for edge_idx, next_node in enumerate(path_nodes):
            inPort, outPort = _port_direction(prev_node, next_node, cols, rows)

            # First hop: source injection (Local=0 → outPort)
            if edge_idx == 0:
                inPort = 0

            # Through rings at router: (wl - 1) through
            through_count = wl - 1
            for t in range(through_count):
                idx = prev_node * 1000 + inPort * 100 + outPort * 10 + t
                segments.append(Segment(DevType.RING_THROUGH, idx, wavelengthIndex=wl))
            # Drop ring
            idx = prev_node * 1000 + inPort * 100 + outPort * 10 + through_count
            segments.append(Segment(DevType.RING_DROP, idx, wavelengthIndex=wl))

            # Waveguide crossing at each intermediate router
            # (simplified: 1 crossing per hop, matching implementation plan)
            segments.append(Segment(DevType.WAVEGUIDE_CROSSING,
                                    prev_node * 100 + next_node, wavelengthIndex=wl))

            # Inter-router waveguide
            segments.append(Segment(DevType.WAVEGUIDE,
                                    prev_node * 10 + next_node,
                                    params.routerToRouter_cm, wl))

            # SOA after each router output
            if params.enableSOA:
                segments.append(Segment(DevType.SOA, next_node, wavelengthIndex=wl))

            prev_node = next_node

        # ---- Demodulator chain at destination ----
        # Waveguide: router core port to demodulator
        segments.append(Segment(DevType.WAVEGUIDE, dst_id * 10 + 2,
                                params.routerToDemodulator_cm, wl))
        # Through rings: (wl - 1) through
        for t in range(wl - 1):
            segments.append(Segment(DevType.RING_THROUGH,
                                    dst_id * 1000 + 100 + t, wavelengthIndex=wl))
        # Drop ring
        segments.append(Segment(DevType.RING_DROP,
                                dst_id * 1000 + 100 + wl, wavelengthIndex=wl))
        # Waveguide: demodulator ring chain to PD
        segments.append(Segment(DevType.WAVEGUIDE, dst_id * 10 + 3,
                                params.demodulatorToPD_cm, wl))
        # Photodetector
        segments.append(Segment(DevType.PHOTODETECTOR, dst_id, wavelengthIndex=wl))

        # ---- Accumulate losses ----
        currentPower_dBm = per_branch_power_dBm
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
                segLoss_dB = -dp.soaGain_dB  # gain = negative loss
                ase = _computeSOAASE(dp.soaGain_dB, dp.soaNoiseFigure_dB)
                accumulatedNoise_mW += 10.0 ** (ase / 10.0)
            else:
                segLoss_dB = dp.insertionLoss_dB

            base_loss = segLoss_dB

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
                    segLoss_dB += (params.waveguideLoss_TempCoeff_dB_per_cm_per_K *
                                   seg.waveguideLength_cm * max(0.0, deltaT))

                result.tempAdjustedLoss_dB += (segLoss_dB - base_loss)

            # Per-device-type breakdown
            if seg.devType == DevType.MODULATOR:
                result.modulatorLoss_dB += segLoss_dB
            elif seg.devType in (DevType.MUX, DevType.DEMUX):
                result.muxDemuxLoss_dB += segLoss_dB
            elif seg.devType == DevType.WAVEGUIDE:
                result.waveguidePropagationLoss_dB += segLoss_dB
            elif seg.devType == DevType.WAVEGUIDE_BEND:
                result.waveguideBendingLoss_dB += segLoss_dB
            elif seg.devType == DevType.WAVEGUIDE_CROSSING:
                result.waveguideCrossingLoss_dB += segLoss_dB
            elif seg.devType == DevType.RING_THROUGH:
                result.ringThroughLoss_dB += segLoss_dB
            elif seg.devType == DevType.RING_DROP:
                result.ringDropLoss_dB += segLoss_dB
            elif seg.devType == DevType.SOA:
                result.soaGainTotal_dB += (-segLoss_dB)  # gain is negative loss
            elif seg.devType == DevType.PHOTODETECTOR:
                result.detectorLoss_dB += segLoss_dB

            currentPower_dBm -= segLoss_dB
            accumulatedLoss_dB += segLoss_dB

        # SNR and BER
        noiseTotal_mW = accumulatedNoise_mW
        signalPower_mW = 10.0 ** (currentPower_dBm / 10.0)
        snr_linear = signalPower_mW / noiseTotal_mW if noiseTotal_mW > 0 else 1e12
        snr_dB = 10.0 * math.log10(snr_linear)
        ber = _computePAM4BER(snr_dB)

        # Track per-wavelength results
        result.perWavelengthLoss_dB.append(accumulatedLoss_dB)
        result.perWavelengthRxPower_dBm.append(currentPower_dBm)
        result.perWavelengthSNR_dB.append(snr_dB)

        # Aggregate (worst-case across wavelengths)
        result.totalLoss_dB = max(result.totalLoss_dB, accumulatedLoss_dB)
        result.receivedPower_dBm = min(result.receivedPower_dBm, currentPower_dBm)
        result.estimatedSNR_dB = min(result.estimatedSNR_dB, snr_dB)
        result.estimatedBER = max(result.estimatedBER, ber)

    result.signalMargin_dB = result.receivedPower_dBm - params.receiverSensitivity_dBm
    result.meetsSensitivity = result.receivedPower_dBm >= params.receiverSensitivity_dBm

    return result
