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

#ifndef __HNOCS_ONOC_OPTICAL_DEVICE_MODEL_H_
#define __HNOCS_ONOC_OPTICAL_DEVICE_MODEL_H_

#include <omnetpp.h>

#include <cmath>
#include <functional>
#include <map>
#include <string>
#include <vector>

using namespace omnetpp;

// ────────────────────────────────────────────────────────────
//  1. Device type enumeration
// ────────────────────────────────────────────────────────────
enum OpticalDeviceType {
    DEV_NONE = 0,               // placeholder / no device
    DEV_MODULATOR,              // Microring-based optical modulator (E→O)
    DEV_RING_THROUGH,           // Microring resonator through-port pass
    DEV_RING_DROP,              // Microring resonator drop-port extraction
    DEV_WAVEGUIDE,              // Straight waveguide segment (loss per cm)
    DEV_WAVEGUIDE_BEND,         // Waveguide 90° bend
    DEV_MUX,                    // WDM multiplexer (AWG or cascaded rings)
    DEV_DEMUX,                  // WDM demultiplexer
    DEV_SOA,                    // Semiconductor optical amplifier
    DEV_PHOTODETECTOR,          // Photodetector / PD demodulator (O→E)

    DEV_COUNT                   // sentinel
};

// Human-readable names for logging / parameter files.
const char *opticalDeviceTypeName(OpticalDeviceType t);

// ────────────────────────────────────────────────────────────
//  2. Per-device, per-wavelength parameter block
//     All loss / gain values in dB.  Power values in dBm.
// ────────────────────────────────────────────────────────────
struct DevicePerWavelengthParams {
    double insertionLoss_dB;         // Insertion loss (or negative gain for SOA)
    double crosstalkToAdjacent_dB;   // Crosstalk coupled to adjacent channel
    double crosstalkToNonAdjacent_dB;// Crosstalk to non-adjacent channels
    // SOA-specific:
    double soaGain_dB;               // SOA small-signal gain (positive)
    double soaNoiseFigure_dB;        // SOA noise figure
    double soaSaturationPower_dBm;   // SOA output saturation power
    // PD-specific:
    double pdResponsivity_AW;        // Photodetector responsivity (A/W)
    double pdSensitivity_dBm;        // Minimum detectable power (BER=1e-12)
    // Modulator-specific:
    double modulatorEfficiency_dB;   // Modulation efficiency

    DevicePerWavelengthParams()
        : insertionLoss_dB(0.0), crosstalkToAdjacent_dB(-99.0), crosstalkToNonAdjacent_dB(-99.0),
          soaGain_dB(0.0), soaNoiseFigure_dB(0.0), soaSaturationPower_dBm(30.0),
          pdResponsivity_AW(1.0), pdSensitivity_dBm(-15.0),
          modulatorEfficiency_dB(0.0) {}
};

// ────────────────────────────────────────────────────────────
//  3. Device parameter table
//     Key = (deviceType, wavelengthIndex) → parameters
//     wavelengthIndex is 1-based (λ₁, λ₂, …, λ_n).
// ────────────────────────────────────────────────────────────
struct DeviceParamKey {
    OpticalDeviceType deviceType;
    int wavelengthIndex;          // 1-based

    bool operator<(const DeviceParamKey &other) const {
        if (deviceType != other.deviceType)
            return deviceType < other.deviceType;
        return wavelengthIndex < other.wavelengthIndex;
    }
};

typedef std::map<DeviceParamKey, DevicePerWavelengthParams> OpticalParamTable;

// Helper: look up device params; returns a default-constructed entry if not found.
const DevicePerWavelengthParams &getDeviceParams(const OpticalParamTable &table,
        OpticalDeviceType devType, int wavelengthIndex);

// ────────────────────────────────────────────────────────────
//  4. Device segment – one element on an optical path
// ────────────────────────────────────────────────────────────
struct OpticalDeviceSegment {
    OpticalDeviceType deviceType;
    int deviceIndex;             // Instance index within its host (router / NI)
    double waveguideLength_cm;   // Valid for DEV_WAVEGUIDE
    int wavelengthIndex;         // 1-based λ index carried by this segment

    OpticalDeviceSegment()
        : deviceType(DEV_NONE), deviceIndex(-1), waveguideLength_cm(0.0), wavelengthIndex(1) {}
};

// ────────────────────────────────────────────────────────────
//  5. Router turn metadata (wavelength-dependent)
//     For a 5-port microring router, each (in→out) pair has:
//       throughCount = number of rings passed in through (off-resonance) mode
//       dropCount    = number of rings used in drop (on-resonance) mode (=1)
//       bendCount    = number of 90° waveguide bends
//     throughCount is a function of wavelength index i and total λ count n.
//
//     Port mapping: 0=Local(Core), 1=West, 2=North, 3=East, 4=South
// ────────────────────────────────────────────────────────────
struct RouterTurnMetadata {
    int throughCount;   // depends on i (1-based wavelength index) and n (total λ)
    int dropCount;      // always 1 for any valid turn
    int bendCount;      // fixed per port pair (0-8)

    RouterTurnMetadata() : throughCount(0), dropCount(1), bendCount(0) {}
};

typedef std::vector<OpticalDeviceSegment> DeviceSegmentList;
typedef std::vector<std::vector<RouterTurnMetadata> > RouterTurnMetadataMatrix;

// Build a wavelength-dependent 5-port microring router turn metadata matrix.
// n = total available wavelengths (e.g. 16).
// The throughCount field must be evaluated per wavelength i at path-build time.
RouterTurnMetadataMatrix buildWavelengthDependentRouterMatrix(int n);

// Expand a RouterTurnMetadata entry into actual device segments for a given
// wavelength index i (1-based).  Appends to the provided segment list.
void expandRouterTurnToSegments(const RouterTurnMetadata &meta,
        int wavelengthIndex, int inPort, int outPort, int nodeId,
        std::vector<OpticalDeviceSegment> &segments);

// ────────────────────────────────────────────────────────────
//  5b. Modulator / Demodulator microring-chain helpers
//      Modulator: 1 drop + (i-1) through for wavelength i
//      Demodulator: 1 drop + (i-1) through, then exits (no further rings)
// ────────────────────────────────────────────────────────────
void buildModulatorSegments(int srcId, int wavelengthIndex,
        int totalWavelengths, std::vector<OpticalDeviceSegment> &segments);
void buildDemodulatorSegments(int dstId, int wavelengthIndex,
        int totalWavelengths, std::vector<OpticalDeviceSegment> &segments);

// ────────────────────────────────────────────────────────────
//  5c. Waveguide distance parameters (cm)
//      Defines physical waveguide lengths between chip components.
// ────────────────────────────────────────────────────────────
struct OpticalWaveguideDistances {
    double sourceToModulator_cm;     // Laser → modulator (within NI)
    double modulatorToRouter_cm;     // Modulator → router core port
    double routerToRouter_cm;        // Inter-router waveguide
    double routerToDemodulator_cm;   // Router core port → demodulator
    double demodulatorToPD_cm;       // Demodulator ring chain → PD

    OpticalWaveguideDistances()
        : sourceToModulator_cm(0.01),   // ~100 μm
          modulatorToRouter_cm(0.03),   // ~300 μm
          routerToRouter_cm(0.15),      // ~1.5 mm (inter-router)
          routerToDemodulator_cm(0.03), // ~300 μm
          demodulatorToPD_cm(0.005) {}  // ~50 μm
};

// ────────────────────────────────────────────────────────────
//  6. End-to-end optical path: source NI → … → destination NI
// ────────────────────────────────────────────────────────────
struct OpticalDevicePath {
    // A flat ordered list of every device segment from laser to PD.
    std::vector<OpticalDeviceSegment> segments;

    // Per-wavelength accumulated budgets (filled by computeDeviceBudget).
    // Indexed by 1-based wavelength index.
    std::map<int, double> perWavelengthTotalLoss_dB;
    std::map<int, double> perWavelengthCrosstalk_dB;
    std::map<int, double> perWavelengthReceivedPower_dBm;
    std::map<int, double> perWavelengthSNR_dB;
    std::map<int, double> perWavelengthBER;
    std::map<int, bool>   perWavelengthMeetsSensitivity;

    // Aggregate:
    double totalLoss_dB;
    double totalCrosstalk_dB;
    double worstReceivedPower_dBm;   // across all used wavelengths
    double worstSNR_dB;
    double worstBER;
    double signalMargin_dB;          // worstReceivedPower - worstSensitivity

    // Temperature-aware outputs
    double totalTuningPower_mW;      // Sum of all ring tuning powers on the path
    double maxRingDetuning_nm;       // Peak ring detuning along the path
    double tempAdjustedLoss_dB;      // Additional loss from temperature effects

    // Per-router tuning power breakdown: routerId → tuning power (mW)
    // Populated by computeDeviceLevelBudget via deviceIndex/1000 grouping.
    std::map<int, double> perRouterTuningPower_mW;

    OpticalDevicePath() : totalLoss_dB(0.0), totalCrosstalk_dB(0.0),
          worstReceivedPower_dBm(0.0), worstSNR_dB(99.0),
          worstBER(0.0), signalMargin_dB(0.0),
          totalTuningPower_mW(0.0), maxRingDetuning_nm(0.0),
          tempAdjustedLoss_dB(0.0) {}
};

// ────────────────────────────────────────────────────────────
//  7. Budget calculator: walk all segments, accumulate losses,
//     apply SOA gains with noise, compute SNR & PAM4 BER.
// ────────────────────────────────────────────────────────────

// Global constraints (configurable via INI parameters).
struct OpticalBudgetConstraints {
    double launchPower_dBm;          // Laser launch power
    double waveguideMaxPower_dBm;    // Damage threshold (14 dBm typical)
    double receiverSensitivity_dBm;  // PD minimum sensitivity
    double thermalNoiseFloor_dBm;    // Thermal noise floor per wavelength
    int    modulationBitsPerSymbol;  // 1=OOK, 2=PAM4
    bool   enableSOA;               // Whether SOAs are present in the path
    double soaNoiseFigure_dB;       // SOA noise figure (global default)
    int    totalWavelengths;         // Total available wavelengths n (for router formulas)
    OpticalWaveguideDistances wgDistances; // Physical waveguide lengths
    bool   enableDemodCrosstalk;     // Enable demodulator-side crosstalk modelling
    bool   singleDestinationPerWavelength; // If true, no crosstalk; if false, model it

    // Temperature-aware optical parameters
    bool   enableThermalEffects;          // Enable temperature-dependent losses
    double Tambient_K;                    // Reference ambient temperature (K)
    double thermoOpticCoeff_nm_per_K;     // dλ/dT for silicon microring (~0.1 nm/K)
    double tuningEfficiency_mW_per_nm;    // Thermal tuning power per nm shift
    double ringIL_TempCoeff_dB_per_K;     // Additional ring IL per degree detuning
    double soaGain_TempCoeff_dB_per_K;    // SOA gain degradation per degree
    double waveguideLoss_TempCoeff_dB_per_cm_per_K; // Waveguide excess loss per K
    // Callback: nodeId (0..numPEs-1 → PE, numPEs+ → router) → temperature (K)
    std::function<double(int)> getNodeTemperature;

    // Centre wavelengths (nm) for the WDM grid — index 0 = λ₁, …, index n-1 = λ_n
    std::vector<double> centreWavelengths_nm;

    OpticalBudgetConstraints()
        : launchPower_dBm(0.0), waveguideMaxPower_dBm(14.0),
          receiverSensitivity_dBm(-12.0), thermalNoiseFloor_dBm(-50.0),
          modulationBitsPerSymbol(2), enableSOA(true), soaNoiseFigure_dB(7.0),
          totalWavelengths(8), enableDemodCrosstalk(true),
          singleDestinationPerWavelength(false),
          enableThermalEffects(false), Tambient_K(318.15),
          thermoOpticCoeff_nm_per_K(0.1), tuningEfficiency_mW_per_nm(0.5),
          ringIL_TempCoeff_dB_per_K(0.02), soaGain_TempCoeff_dB_per_K(0.05),
          waveguideLoss_TempCoeff_dB_per_cm_per_K(0.001) {}
};

// Main budget computation.
//  - Walks the device path, accumulating per-wavelength losses.
//  - Injects SOA gain and ASE noise at each DEV_SOA.
//  - Computes SNR and PAM4 BER at the path endpoint.
//  - Checks launch power against waveguide damage threshold.
//  - Checks received power against PD sensitivity.
//  - Models demodulator-side crosstalk when enabled.
void computeDeviceLevelBudget(const OpticalDevicePath &path,
        const OpticalParamTable &paramTable,
        const OpticalBudgetConstraints &constraints,
        const RouterTurnMetadataMatrix &routerMatrix,
        OpticalDevicePath &result);

// Compute demodulator-side crosstalk penalty: for wavelength i, leakage
// from wavelength (i-1) through its ring through-port couples into ring i.
// Returns additional crosstalk noise power in dBm.
double computeDemodulatorCrosstalk_dBm(int wavelengthIndex,
        int totalWavelengths,
        double signalPower_dBm,
        const OpticalParamTable &paramTable);

// ────────────────────────────────────────────────────────────
//  8. PAM4 BER utility (ITU-T G.Sup39, optical SNR definition)
//     BER_PAM4 = (3/4) * erfc( sqrt( SNR_optical_linear / 10 ) )
//     where SNR_optical_linear = P_signal / P_noise (linear ratio)
//     and   SNR_optical_dB     = 10 * log10( SNR_optical_linear )
//
//     This formulation uses the optical-domain SNR where the noise
//     bandwidth is already accounted for in the SNR definition.
//     Equivalent per-bit formulations (e.g., Griffin 2005) use a
//     different pre-factor (3/8 instead of 3/4) because they define
//     SNR on a per-bit basis with a 2x scaling difference.
//
//     Reference: ITU-T G.Sup39 (2016), "Optical system design
//     and engineering considerations", Sec. 9.2.
// ────────────────────────────────────────────────────────────
inline double computePAM4BER(double snr_dB) {
    if (snr_dB <= -99.0) return 0.5;    // effectively no signal
    double snrLinear = std::pow(10.0, snr_dB / 10.0);
    double x = std::sqrt(snrLinear / 10.0);
    double erfcVal = std::erfc(x);
    return 0.75 * erfcVal;
}

// ────────────────────────────────────────────────────────────
//  9. SOA ASE noise power (dBm)
//     Standard formula: P_ASE = h*nu * n_sp * (G-1) * B_o
//     where n_sp = NF_linear / 2  (population inversion factor)
//     i.e.  P_ASE = h*nu * (NF_linear/2) * (G-1) * B_o
//     Simplified for simulation: ASE accumulated linearly per SOA.
// ────────────────────────────────────────────────────────────
inline double computeSOAASENoisePower_dBm(double soaGain_dB, double noiseFigure_dB,
        double bandwidth_Hz = 30e9) {
    // Default bandwidth ~30 GHz for a 25-28 Gbaud PAM4 signal
    double gainLinear = std::pow(10.0, soaGain_dB / 10.0);
    double nfLinear = std::pow(10.0, noiseFigure_dB / 10.0);
    double h = 6.62607015e-34;   // Planck constant
    double nu = 193.4e12;        // 1550 nm centre frequency
    double aseWatts = h * nu * (gainLinear - 1.0) * (nfLinear / 2.0) * bandwidth_Hz;
    if (aseWatts <= 0.0) return -199.0;
    return 10.0 * std::log10(aseWatts * 1000.0);  // convert W → dBm
}

// ────────────────────────────────────────────────────────────
// 10. Default parameter population
//     Called at startup to fill a parameter table with literature-
//     based silicon photonic defaults.  Users override via CSV/JSON.
// ────────────────────────────────────────────────────────────
void populateDefaultOpticalParams(OpticalParamTable &table,
        int numWavelengths = 8);

#endif // __HNOCS_ONOC_OPTICAL_DEVICE_MODEL_H_
