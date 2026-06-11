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

#ifndef __HNOCS_ONOC_OPTICAL_PATH_METRICS_H_
#define __HNOCS_ONOC_OPTICAL_PATH_METRICS_H_

#include <omnetpp.h>

#include <map>
#include <string>
#include <vector>

using namespace omnetpp;

// Forward declaration
struct OpticalDeviceSegment;

// Packet-level optical budget summary propagated alongside bypass traffic.
// ── Hop-level fields (retained for backward compatibility) ──
// ── Device-level fields (added for per-device physical modelling) ──
class OpticalPathMetrics : public cObject {
  public:
    // ── Identification ──
    int srcId;
    int dstId;
    int pktId;
    int spatialChannel;
    bool opticalPath;
    std::vector<int> wavelengths;           // 1-based wavelength ids

    // ── Hop-level (deprecated, kept for compatibility) ──
    int hopCount;
    int wavelengthCount;

    // ── Power budget – hop-level (legacy) ──
    double launchPower_dBm;
    double receiverSensitivity_dBm;
    double sourceModulatorLoss_dB;
    double hopInsertionLoss_dB;
    double hopCrosstalkLoss_dB;
    double receiverDemodulatorLoss_dB;
    double totalLoss_dB;
    double receivedPower_dBm;
    double signalMargin_dB;
    bool meetsSensitivity;

    // ── Device-level power budget (new) ──
    // Per-device-type accumulated losses
    double modulatorLoss_dB;             // DEV_MODULATOR total
    double muxDemuxLoss_dB;              // DEV_MUX + DEV_DEMUX total
    double waveguidePropagationLoss_dB;  // DEV_WAVEGUIDE total
    double waveguideBendingLoss_dB;      // DEV_WAVEGUIDE_BEND total
    double waveguideCrossingLoss_dB;     // DEV_WAVEGUIDE_CROSSING total
    double ringThroughLoss_dB;           // DEV_RING_THROUGH total
    double ringDropLoss_dB;              // DEV_RING_DROP total
    double soaGainTotal_dB;              // DEV_SOA total gain (positive)
    double soaASENoise_dBm;              // Accumulated ASE noise power (dBm)
    double detectorLoss_dB;              // DEV_PHOTODETECTOR loss

    // Per-wavelength breakdown (indexed by 1-based wavelength id)
    std::map<int, double> perWavelengthTotalLoss_dB;
    std::map<int, double> perWavelengthCrosstalk_dB; // legacy name; value is summed crosstalk noise power in dBm
    std::map<int, double> perWavelengthCrosstalkNoise_dBm;
    std::map<int, double> perWavelengthReceivedPower_dBm;
    std::map<int, double> perWavelengthSNR_dB;
    std::map<int, double> perWavelengthBER;

    // Overall device-level aggregate
    double totalCrosstalk_dB;            // legacy name; value is worst summed crosstalk noise power in dBm
    double totalCrosstalkNoise_dBm;
    double estimatedSNR_dB;              // worst across wavelengths
    double estimatedBER;                 // worst across wavelengths

    // Named wavelength identifiers (e.g. "lambda_1", "lambda_2")
    std::vector<std::string> wavelengthNames;

    // Budget-driven rerouting flag
    bool budgetRerouteTriggered;

    // Temperature-aware optical metrics
    double totalTuningPower_mW;         // Sum of ring tuning power on path
    double maxRingDetuning_nm;          // Max ring wavelength detuning
    double tempAdjustedLoss_dB;         // Additional loss from temperature
    std::map<int, double> perRouterTuningPower_mW; // routerId → tuning power (mW)

  public:
    OpticalPathMetrics()
        : srcId(-1), dstId(-1), pktId(-1), spatialChannel(-1),
          opticalPath(false),
          hopCount(0), wavelengthCount(0),
          launchPower_dBm(0.0), receiverSensitivity_dBm(0.0),
          sourceModulatorLoss_dB(0.0), hopInsertionLoss_dB(0.0),
          hopCrosstalkLoss_dB(0.0), receiverDemodulatorLoss_dB(0.0),
          totalLoss_dB(0.0), receivedPower_dBm(0.0), signalMargin_dB(0.0),
          meetsSensitivity(false),
          modulatorLoss_dB(0.0), muxDemuxLoss_dB(0.0),
          waveguidePropagationLoss_dB(0.0), waveguideBendingLoss_dB(0.0),
          waveguideCrossingLoss_dB(0.0), ringThroughLoss_dB(0.0), ringDropLoss_dB(0.0),
          soaGainTotal_dB(0.0), soaASENoise_dBm(-199.0),
          detectorLoss_dB(0.0),
          totalCrosstalk_dB(-199.0), totalCrosstalkNoise_dBm(-199.0),
          estimatedSNR_dB(99.0),
          estimatedBER(0.0),
          budgetRerouteTriggered(false),
          totalTuningPower_mW(0.0), maxRingDetuning_nm(0.0),
          tempAdjustedLoss_dB(0.0) {}

    virtual OpticalPathMetrics *dup() const override { return new OpticalPathMetrics(*this); }
};

#endif
