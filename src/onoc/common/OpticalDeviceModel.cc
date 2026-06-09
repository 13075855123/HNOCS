//
// Copyright (C) 2010-2011 Eitan Zahavi, The Technion EE Department
// Copyright (C) 2010-2011 Yaniv Ben-Itzhak, The Technion EE Department
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Lesser General Public License for more details.
//
// You should have received a copy of the GNU Lesser General Public License
// along with this program.  If not, see http://www.gnu.org/licenses/.
//

#include "OpticalDeviceModel.h"

#include <algorithm>
#include <set>
#include <sstream>

// ────────────────────────────────────────────────────────────
//  Human-readable device type names
// ────────────────────────────────────────────────────────────
const char *opticalDeviceTypeName(OpticalDeviceType t) {
    switch (t) {
        case DEV_NONE:            return "none";
        case DEV_MODULATOR:       return "modulator";
        case DEV_RING_THROUGH:    return "ring_through";
        case DEV_RING_DROP:       return "ring_drop";
        case DEV_WAVEGUIDE:       return "waveguide";
        case DEV_WAVEGUIDE_BEND:  return "waveguide_bend";
        case DEV_MUX:             return "mux";
        case DEV_DEMUX:           return "demux";
        case DEV_SOA:             return "soa";
        case DEV_PHOTODETECTOR:   return "photodetector";
        default:                  return "unknown";
    }
}

// ────────────────────────────────────────────────────────────
//  Helper: look up device params
// ────────────────────────────────────────────────────────────
const DevicePerWavelengthParams &getDeviceParams(const OpticalParamTable &table,
        OpticalDeviceType devType, int wavelengthIndex) {
    DeviceParamKey key;
    key.deviceType = devType;
    key.wavelengthIndex = wavelengthIndex;

    OpticalParamTable::const_iterator it = table.find(key);
    if (it != table.end()) {
        return it->second;
    }

    // Try with wavelengthIndex=0 as fallback (wavelength-independent default)
    key.wavelengthIndex = 0;
    it = table.find(key);
    if (it != table.end()) {
        return it->second;
    }

    // Return a static default
    static DevicePerWavelengthParams defaultParams;
    return defaultParams;
}

// ────────────────────────────────────────────────────────────
//  Build wavelength-dependent 5-port microring router turn metadata matrix
//  Ports: 0=Local(Core), 1=West, 2=North, 3=East, 4=South
//  n = total available wavelengths
//
//  Through-count formulas (user-specified):
//   Local→W:i-1    Local→N:3n+i-1  Local→E:3n+i-1  Local→S:2n+i-1
//   W→Local:3n+i-1 W→N:4n+i-1     W→E:4n          W→S:i-1
//   N→Local:i-1    N→W:2n+i-1     N→E:6n+i-1      N→S:4n
//   E→Local:2n+i-1 E→W:4n         E→N:i-1         E→S:4n+i-1
//   S→Local:3n+i-1 S→W:6n+i-1     S→N:4n          S→E:2n+i-1
//
//  Bend counts (fixed):
//   L→W:0 L→N:5 L→E:4 L→S:5 | W→L:5 W→N:5 W→E:0 W→S:1
//   N→L:1 N→W:1 N→E:5 N→S:6 | E→L:3 E→W:0 E→N:1 E→S:5
//   S→L:8 S→W:5 S→N:6 S→E:1
//
//  Drop count: always 1 for any valid port pair.
// ────────────────────────────────────────────────────────────
RouterTurnMetadataMatrix buildWavelengthDependentRouterMatrix(int n) {
    const int P = 5;
    RouterTurnMetadataMatrix matrix(P, std::vector<RouterTurnMetadata>(P));

    // Bend counts table [inPort][outPort]
    static const int bendTable[5][5] = {
        /*Local*/ {0, 0, 5, 4, 5},
        /*West*/  {5, 0, 5, 0, 1},
        /*North*/ {1, 1, 0, 5, 6},
        /*East*/  {3, 0, 1, 0, 5},
        /*South*/ {8, 5, 6, 1, 0},
    };

    // Through-count formula type [inPort][outPort]:
    //  0 = i-1,  1 = 2n+i-1,  2 = 3n+i-1,  3 = 4n,  4 = 4n+i-1,  5 = 6n+i-1
    static const int formulaType[5][5] = {
        /*Local*/ {-1, 0, 2, 2, 1},
        /*West*/  {2, -1, 4, 3, 0},
        /*North*/ {0, 1, -1, 5, 3},
        /*East*/  {1, 3, 0, -1, 4},
        /*South*/ {2, 5, 3, 1, -1},
    };

    for (int inP = 0; inP < P; ++inP) {
        for (int outP = 0; outP < P; ++outP) {
            if (inP == outP) continue;
            RouterTurnMetadata &meta = matrix[inP][outP];
            meta.dropCount = 1;
            meta.bendCount = bendTable[inP][outP];

            // Store formula type; through count will be evaluated per wavelength
            // We store it as a negative sentinel so expandRouterTurnToSegments
            // can compute the actual count at expansion time.
            // formulaType → expression:
            int ft = formulaType[inP][outP];
            meta.throughCount = ft; // stored as formula type (negative convention)
        }
    }
    return matrix;
}

// ────────────────────────────────────────────────────────────
//  Expand router turn metadata → device segments for wavelength i
// ────────────────────────────────────────────────────────────
static int evalThroughCount(int formulaType, int i, int n) {
    switch (formulaType) {
        case 0: return i - 1;           // i-1
        case 1: return 2 * n + i - 1;   // 2n+i-1
        case 2: return 3 * n + i - 1;   // 3n+i-1
        case 3: return 4 * n;           // 4n
        case 4: return 4 * n + i - 1;   // 4n+i-1
        case 5: return 6 * n + i - 1;   // 6n+i-1
        default: return 0;
    }
}

void expandRouterTurnToSegments(const RouterTurnMetadata &meta,
        int wavelengthIndex, int inPort, int outPort, int nodeId,
        std::vector<OpticalDeviceSegment> &segments) {
    // Note: meta.throughCount stores the formulaType here (set by builder)
    // We need totalWavelengths n to evaluate it. The caller must provide it
    // through a separate mechanism. For now we use the raw stored value
    // and let the LogicalTopologyManager handle the expansion.
    //
    // We emit segments in order: through passes → drop → bends
    int formulaType = meta.throughCount; // stored as formula type
    // throughCount will be resolved by caller; for now emit 0 through segments
    // and let the LogicalTopologyManager inject the correct count.

    // 1. Through passes (count = evalThroughCount(formulaType, i, n))
    //    Emitted by LogicalTopologyManager which knows i and n.
    // 2. Drop (always 1)
    {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_RING_DROP;
        seg.deviceIndex = nodeId * 1000 + inPort * 100 + outPort * 10;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
    // 3. Bends
    for (int b = 0; b < meta.bendCount; ++b) {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_WAVEGUIDE_BEND;
        seg.deviceIndex = nodeId * 1000 + inPort * 100 + outPort * 10 + b;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
}

// ────────────────────────────────────────────────────────────
//  Build modulator microring-chain segments for wavelength i
//  Light enters bus waveguide → passes through rings 1..(i-1)
//  → drops at ring i (modulation) → exits.
//  Total: (i-1) through + 1 drop
// ────────────────────────────────────────────────────────────
void buildModulatorSegments(int srcId, int wavelengthIndex,
        int totalWavelengths, std::vector<OpticalDeviceSegment> &segments) {
    // Through passes for rings before the target ring
    for (int r = 1; r < wavelengthIndex; ++r) {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_RING_THROUGH;
        seg.deviceIndex = srcId * 1000 + r;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
    // Drop at the target ring (modulation)
    {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_RING_DROP;
        seg.deviceIndex = srcId * 1000 + wavelengthIndex;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
    // Note: after modulation, light is on the drop path and exits;
    // it does NOT continue through subsequent rings.
}

// ────────────────────────────────────────────────────────────
//  Build demodulator microring-chain segments for wavelength i
//  Light enters bus waveguide → passes through rings 1..(i-1)
//  → drops at ring i (coupling to PD) → exits to PD.
//  Total: (i-1) through + 1 drop
//  After drop, light goes to PD — does NOT continue through
//  subsequent rings (unlike through-path in a router).
// ────────────────────────────────────────────────────────────
void buildDemodulatorSegments(int dstId, int wavelengthIndex,
        int totalWavelengths, std::vector<OpticalDeviceSegment> &segments) {
    // Through passes for rings before the target ring
    for (int r = 1; r < wavelengthIndex; ++r) {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_RING_THROUGH;
        seg.deviceIndex = dstId * 1000 + r;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
    // Drop at the target ring (coupling to PD)
    {
        OpticalDeviceSegment seg;
        seg.deviceType = DEV_RING_DROP;
        seg.deviceIndex = dstId * 1000 + wavelengthIndex;
        seg.wavelengthIndex = wavelengthIndex;
        segments.push_back(seg);
    }
}

// ────────────────────────────────────────────────────────────
//  Demodulator-side crosstalk: leakage from λ_{i-1} through-port
//  into λ_i drop-port.  Only adjacent, same-destination crosstalk
//  is significant; cross-node crosstalk is negligible.
// ────────────────────────────────────────────────────────────
double computeDemodulatorCrosstalk_dBm(int wavelengthIndex,
        int totalWavelengths,
        double signalPower_dBm,
        const OpticalParamTable &paramTable) {
    if (wavelengthIndex <= 1) return -199.0; // no lower adjacent channel

    // Crosstalk from λ_{i-1}: its through-port leakage couples into λ_i's ring
    const DevicePerWavelengthParams &ringParams =
        getDeviceParams(paramTable, DEV_RING_THROUGH, wavelengthIndex - 1);
    double leakage_dB = ringParams.crosstalkToAdjacent_dB;
    if (leakage_dB > -90.0) {
        double xtalkPower_dBm = signalPower_dBm + leakage_dB;
        return xtalkPower_dBm;
    }
    return -199.0;
}

// ────────────────────────────────────────────────────────────
//  Populate default silicon photonic parameters
//  Based on literature values – all can be overridden via CSV/JSON.
// ────────────────────────────────────────────────────────────
void populateDefaultOpticalParams(OpticalParamTable &table, int numWavelengths) {
    if (numWavelengths < 1) numWavelengths = 8;

    for (int wl = 1; wl <= numWavelengths; ++wl) {
        DeviceParamKey key;
        key.wavelengthIndex = wl;

        // ── Modulator (microring) ──
        key.deviceType = DEV_MODULATOR;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 2.0;           // typical Si microring modulator
            p.crosstalkToAdjacent_dB = -25.0;   // adjacent channel leakage
            p.crosstalkToNonAdjacent_dB = -40.0;
            p.modulatorEfficiency_dB = 0.0;     // accounted in insertion loss
            table[key] = p;
        }

        // ── Ring through (off-resonance pass) ──
        key.deviceType = DEV_RING_THROUGH;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 0.05;          // very low for high-Q ring
            p.crosstalkToAdjacent_dB = -35.0;
            p.crosstalkToNonAdjacent_dB = -50.0;
            table[key] = p;
        }

        // ── Ring drop (on-resonance extraction) ──
        key.deviceType = DEV_RING_DROP;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 1.0;           // coupling + propagation
            p.crosstalkToAdjacent_dB = -20.0;   // more crosstalk at drop
            p.crosstalkToNonAdjacent_dB = -35.0;
            table[key] = p;
        }

        // ── Waveguide propagation (per cm) ──
        key.deviceType = DEV_WAVEGUIDE;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 1.5;           // dB/cm for SOI wire
            p.crosstalkToAdjacent_dB = -60.0;
            p.crosstalkToNonAdjacent_dB = -80.0;
            table[key] = p;
        }

        // ── Waveguide 90° bend ──
        key.deviceType = DEV_WAVEGUIDE_BEND;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 0.01;          // per 90° for R ≥ 5 μm
            p.crosstalkToAdjacent_dB = -70.0;
            p.crosstalkToNonAdjacent_dB = -90.0;
            table[key] = p;
        }

        // ── WDM MUX (e.g. AWG) ──
        key.deviceType = DEV_MUX;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 2.5;           // typical Si AWG MUX
            p.crosstalkToAdjacent_dB = -25.0;
            p.crosstalkToNonAdjacent_dB = -40.0;
            table[key] = p;
        }

        // ── WDM DEMUX (e.g. AWG) ──
        key.deviceType = DEV_DEMUX;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 2.5;           // typical Si AWG DEMUX
            p.crosstalkToAdjacent_dB = -25.0;
            p.crosstalkToNonAdjacent_dB = -40.0;
            table[key] = p;
        }

        // ── SOA ──
        key.deviceType = DEV_SOA;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 0.0;           // gain is handled separately
            p.soaGain_dB = 10.0;
            p.soaNoiseFigure_dB = 7.0;
            p.soaSaturationPower_dBm = 12.0;
            p.crosstalkToAdjacent_dB = -50.0;
            p.crosstalkToNonAdjacent_dB = -60.0;
            table[key] = p;
        }

        // ── Photodetector ──
        key.deviceType = DEV_PHOTODETECTOR;
        {
            DevicePerWavelengthParams p;
            p.insertionLoss_dB = 0.5;           // coupling loss to PD
            p.pdResponsivity_AW = 1.0;
            p.pdSensitivity_dBm = -12.0;        // PAM4 128 GBaud (256 Gbps)
            p.crosstalkToAdjacent_dB = -40.0;
            p.crosstalkToNonAdjacent_dB = -60.0;
            table[key] = p;
        }
    }

    // Also populate wavelength-independent fallbacks (index 0).
    for (int dt = DEV_MODULATOR; dt < DEV_COUNT; ++dt) {
        OpticalDeviceType devType = static_cast<OpticalDeviceType>(dt);
        DeviceParamKey key0;
        key0.deviceType = devType;
        key0.wavelengthIndex = 0;
        if (table.find(key0) == table.end()) {
            DeviceParamKey key1;
            key1.deviceType = devType;
            key1.wavelengthIndex = 1;
            OpticalParamTable::const_iterator it = table.find(key1);
            if (it != table.end()) {
                table[key0] = it->second;
            }
        }
    }
}

// ────────────────────────────────────────────────────────────
//  Core budget computation: walk all device segments, accumulate
//  per-wavelength losses, apply SOA gain + ASE noise, compute
//  SNR and PAM4 BER.
// ────────────────────────────────────────────────────────────
void computeDeviceLevelBudget(const OpticalDevicePath &path,
        const OpticalParamTable &paramTable,
        const OpticalBudgetConstraints &constraints,
        const RouterTurnMetadataMatrix &routerMatrix,
        OpticalDevicePath &result) {
    result = path; // copy segment list

    double launchPower_linear_mW = std::pow(10.0, constraints.launchPower_dBm / 10.0);

    // Check waveguide damage threshold at source
    if (constraints.launchPower_dBm > constraints.waveguideMaxPower_dBm) {
        EV_WARN << "Launch power " << constraints.launchPower_dBm
                << " dBm exceeds waveguide damage threshold "
                << constraints.waveguideMaxPower_dBm << " dBm" << std::endl;
    }

    // Collect which wavelengths are used on this path
    std::vector<int> activeWavelengths;
    {
        std::set<int> wlSet;
        for (size_t i = 0; i < path.segments.size(); ++i) {
            int wl = path.segments[i].wavelengthIndex;
            if (wl > 0) wlSet.insert(wl);
        }
        activeWavelengths.assign(wlSet.begin(), wlSet.end());
    }
    if (activeWavelengths.empty()) {
        activeWavelengths.push_back(1); // default
    }

    result.totalLoss_dB = 0.0;
    result.totalCrosstalk_dB = 0.0;
    result.worstReceivedPower_dBm = 99.0;
    result.worstSNR_dB = 99.0;
    result.worstBER = 0.0;
    result.signalMargin_dB = 99.0;
    // Per-wavelength accumulators
    for (size_t wi = 0; wi < activeWavelengths.size(); ++wi) {
        int wl = activeWavelengths[wi];
        double totalInsertionLoss_dB = 0.0;  // reset per wavelength
        double currentPower_dBm = constraints.launchPower_dBm;
        double accumulatedCrosstalk_dB = -199.0; // linear-sum later, track in dB
        double accumulatedNoisePower_mW = 0.0;    // mW
        double accumulatedLoss_dB = 0.0;

        // Thermal noise floor (mW)
        double thermalNoise_mW = std::pow(10.0, constraints.thermalNoiseFloor_dBm / 10.0);
        accumulatedNoisePower_mW += thermalNoise_mW;

        // Walk segments
        for (size_t si = 0; si < path.segments.size(); ++si) {
            const OpticalDeviceSegment &seg = path.segments[si];
            const DevicePerWavelengthParams &params =
                getDeviceParams(paramTable, seg.deviceType, wl);

            double segLoss_dB = 0.0;

            switch (seg.deviceType) {
                case DEV_NONE:
                    break;

                case DEV_WAVEGUIDE:
                    // Loss = per-cm loss × length
                    segLoss_dB = params.insertionLoss_dB * seg.waveguideLength_cm;
                    break;

                case DEV_SOA: {
                    // SOA: apply gain (negative loss) and accumulate ASE noise.
                    // Gain saturation: if output would exceed saturation power,
                    // the actual gain is reduced (output clipped to Psat).
                    // ASE must be computed from the *actual* (post-saturation)
                    // gain, not the small-signal gain — otherwise ASE is
                    // overestimated by up to ~8 dB in deep saturation.
                    segLoss_dB = -params.soaGain_dB; // small-signal gain
                    double actualGain_dB = params.soaGain_dB;
                    if (currentPower_dBm - segLoss_dB > params.soaSaturationPower_dBm) {
                        segLoss_dB = currentPower_dBm - params.soaSaturationPower_dBm;
                        actualGain_dB = params.soaSaturationPower_dBm - currentPower_dBm;
                    }
                    {
                        double aseNoise_dBm = computeSOAASENoisePower_dBm(
                                actualGain_dB, params.soaNoiseFigure_dB);
                        double aseNoise_mW = std::pow(10.0, aseNoise_dBm / 10.0);
                        accumulatedNoisePower_mW += aseNoise_mW;
                    }
                    break;
                }

                case DEV_MODULATOR:
                case DEV_RING_THROUGH:
                case DEV_RING_DROP:
                case DEV_WAVEGUIDE_BEND:
                case DEV_MUX:
                case DEV_DEMUX:
                case DEV_PHOTODETECTOR:
                default:
                    segLoss_dB = params.insertionLoss_dB;
                    break;
            }

            // ── Temperature-aware adjustments ──
            double tempExtraLoss_dB = 0.0;
            if (constraints.enableThermalEffects && constraints.getNodeTemperature) {
                int nodeId = seg.deviceIndex / 1000;
                double T_K = constraints.getNodeTemperature(nodeId);
                double deltaT_K = T_K - constraints.Tambient_K;

                // Microring through/drop: detuning → extra IL + tuning power
                if (seg.deviceType == DEV_RING_THROUGH || seg.deviceType == DEV_RING_DROP) {
                    double detuning_nm = constraints.thermoOpticCoeff_nm_per_K * deltaT_K;
                    double absDetuning = std::abs(detuning_nm);
                    // Lorentzian-based excess loss: IL_extra ≈ lossCoeff × (detuning/bandwidth)^2
                    double excessIL = constraints.ringIL_TempCoeff_dB_per_K * absDetuning;
                    tempExtraLoss_dB += excessIL;
                    // Tuning power to compensate detuning
                    double ringTuningPower = constraints.tuningEfficiency_mW_per_nm * absDetuning;
                    result.totalTuningPower_mW += ringTuningPower;
                    result.perRouterTuningPower_mW[nodeId] += ringTuningPower;
                    if (absDetuning > result.maxRingDetuning_nm)
                        result.maxRingDetuning_nm = absDetuning;
                }

                // SOA: gain degradation with temperature
                if (seg.deviceType == DEV_SOA) {
                    double gainDrop = constraints.soaGain_TempCoeff_dB_per_K * std::max(0.0, deltaT_K);
                    tempExtraLoss_dB += gainDrop;
                }

                // Waveguide: excess propagation loss due to temperature
                if (seg.deviceType == DEV_WAVEGUIDE) {
                    tempExtraLoss_dB += constraints.waveguideLoss_TempCoeff_dB_per_cm_per_K
                            * seg.waveguideLength_cm * std::max(0.0, deltaT_K);
                }
            }

            segLoss_dB += tempExtraLoss_dB;
            result.tempAdjustedLoss_dB += tempExtraLoss_dB;
            currentPower_dBm -= segLoss_dB;
            accumulatedLoss_dB += segLoss_dB;

            // Track positive insertion losses (exclude SOA gain)
            if (segLoss_dB > 0.0) {
                totalInsertionLoss_dB += segLoss_dB;
            }

            // Accumulate crosstalk (worst-case sum in dB domain ≈ linear domain approximation)
            // We use linear summation for crosstalk power
            double crosstalk_mW = 0.0;
            if (params.crosstalkToAdjacent_dB > -90.0) {
                double pwr_mW = std::pow(10.0, currentPower_dBm / 10.0);
                double xtalk_mW = pwr_mW * std::pow(10.0, params.crosstalkToAdjacent_dB / 10.0);
                crosstalk_mW += xtalk_mW;
            }
            if (params.crosstalkToNonAdjacent_dB > -90.0) {
                double pwr_mW = std::pow(10.0, currentPower_dBm / 10.0);
                double xtalk_mW = pwr_mW * std::pow(10.0, params.crosstalkToNonAdjacent_dB / 10.0);
                crosstalk_mW += xtalk_mW;
            }
            if (crosstalk_mW > 0.0) {
                accumulatedNoisePower_mW += crosstalk_mW;
                double crosstalk_dBm = 10.0 * std::log10(crosstalk_mW);
                if (crosstalk_dBm > accumulatedCrosstalk_dB || accumulatedCrosstalk_dB < -190.0) {
                    accumulatedCrosstalk_dB = crosstalk_dBm;
                }
            }
        }

        // Final received power
        double rxPower_dBm = currentPower_dBm;

        // Demodulator-side crosstalk: adjacent-channel leakage at same destination
        if (constraints.enableDemodCrosstalk && !constraints.singleDestinationPerWavelength
                && wl > 1) {
            double xtalk_dBm = computeDemodulatorCrosstalk_dBm(
                    wl, constraints.totalWavelengths, rxPower_dBm, paramTable);
            if (xtalk_dBm > -190.0) {
                double xtalk_mW = std::pow(10.0, xtalk_dBm / 10.0);
                accumulatedNoisePower_mW += xtalk_mW;
                if (xtalk_dBm > accumulatedCrosstalk_dB || accumulatedCrosstalk_dB < -190.0) {
                    accumulatedCrosstalk_dB = xtalk_dBm;
                }
            }
        }

        // Compute SNR
        double rxPower_mW = std::pow(10.0, rxPower_dBm / 10.0);
        double totalNoise_mW = accumulatedNoisePower_mW;
        double snrLinear = (totalNoise_mW > 0.0) ? (rxPower_mW / totalNoise_mW) : 1e12;
        double snr_dB = 10.0 * std::log10(snrLinear);

        // PAM4 BER
        int m = constraints.modulationBitsPerSymbol;
        double ber;
        if (m == 1) {
            // OOK: BER = 0.5 * erfc(sqrt(SNR/2))
            double x = std::sqrt(snrLinear / 2.0);
            ber = 0.5 * std::erfc(x);
        } else {
            // PAM4 (default)
            ber = computePAM4BER(snr_dB);
        }

        // Sensitivity check
        double pdSens_dBm = -99.0;
        {
            const DevicePerWavelengthParams &pdParams =
                getDeviceParams(paramTable, DEV_PHOTODETECTOR, wl);
            pdSens_dBm = pdParams.pdSensitivity_dBm;
        }
        bool meetsSens = (rxPower_dBm >= pdSens_dBm);

        // Store per-wavelength results
        result.perWavelengthTotalLoss_dB[wl] = accumulatedLoss_dB;
        result.perWavelengthCrosstalk_dB[wl] = accumulatedCrosstalk_dB;
        result.perWavelengthReceivedPower_dBm[wl] = rxPower_dBm;
        result.perWavelengthSNR_dB[wl] = snr_dB;
        result.perWavelengthBER[wl] = ber;
        result.perWavelengthMeetsSensitivity[wl] = meetsSens;

        // Update aggregates (worst across wavelengths)
        result.totalLoss_dB = std::max(result.totalLoss_dB, totalInsertionLoss_dB);
        if (accumulatedCrosstalk_dB > result.totalCrosstalk_dB) {
            result.totalCrosstalk_dB = accumulatedCrosstalk_dB;
        }
        if (rxPower_dBm < result.worstReceivedPower_dBm) {
            result.worstReceivedPower_dBm = rxPower_dBm;
        }
        if (snr_dB < result.worstSNR_dB) {
            result.worstSNR_dB = snr_dB;
        }
        if (ber > result.worstBER) {
            result.worstBER = ber;
        }
    }

    // Worst-case margin
    double worstSensitivity = constraints.receiverSensitivity_dBm;
    {
        const DevicePerWavelengthParams &pdParams =
            getDeviceParams(paramTable, DEV_PHOTODETECTOR, 1);
        worstSensitivity = pdParams.pdSensitivity_dBm;
    }
    result.signalMargin_dB = result.worstReceivedPower_dBm - worstSensitivity;
}
