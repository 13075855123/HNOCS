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

#ifndef __HNOCS_ONOC_OPTICAL_PARAM_LOADER_H_
#define __HNOCS_ONOC_OPTICAL_PARAM_LOADER_H_

#include <omnetpp.h>

#include <string>

using namespace omnetpp;

#include "OpticalDeviceModel.h"

// Loads device parameters from a CSV file.
//
// Expected CSV format (header row required):
//   device_type,wavelength_index,insertion_loss_dB,crosstalk_adjacent_dB,
//   crosstalk_nonadjacent_dB,soa_gain_dB,soa_noise_figure_dB,
//   soa_saturation_power_dBm,pd_responsivity_AW,pd_sensitivity_dBm,
//   modulator_efficiency_dB
//
// device_type must match one of the OpticalDeviceType names:
//   modulator, ring_through, ring_drop, waveguide, waveguide_bend,
//   mux, demux, soa, photodetector
//
// wavelength_index=0 means "all wavelengths" (fallback default).
//
// Lines starting with '#' are comments.
//
// Returns true on success; on failure populates errorMsg.
bool loadOpticalParamsFromCSV(const char *filename,
        OpticalParamTable &table,
        std::string &errorMsg);

// Convenience: load from CSV, falling back to defaults on failure.
void loadOpticalParamsOrDefault(const char *filename,
        OpticalParamTable &table,
        int numWavelengths = 8);

#endif // __HNOCS_ONOC_OPTICAL_PARAM_LOADER_H_
