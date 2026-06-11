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

#include "OpticalParamLoader.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <map>
#include <sstream>
#include <vector>

// ────────────────────────────────────────────────────────────
//  Helper: trim whitespace
// ────────────────────────────────────────────────────────────
namespace {
std::string trim(const std::string &s) {
    size_t start = 0;
    while (start < s.size() && (s[start] == ' ' || s[start] == '\t' || s[start] == '\r')) {
        ++start;
    }
    size_t end = s.size();
    while (end > start && (s[end - 1] == ' ' || s[end - 1] == '\t' || s[end - 1] == '\r')) {
        --end;
    }
    return s.substr(start, end - start);
}

OpticalDeviceType parseDeviceType(const std::string &name) {
    static std::map<std::string, OpticalDeviceType> nameMap;
    if (nameMap.empty()) {
        for (int i = DEV_NONE; i < DEV_COUNT; ++i) {
            OpticalDeviceType t = static_cast<OpticalDeviceType>(i);
            nameMap[opticalDeviceTypeName(t)] = t;
        }
    }
    std::string lower = name;
    for (size_t i = 0; i < lower.size(); ++i) {
        lower[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(lower[i])));
    }
    std::map<std::string, OpticalDeviceType>::const_iterator it = nameMap.find(lower);
    if (it != nameMap.end()) return it->second;

    // Allow common synonyms
    if (lower == "mod")          return DEV_MODULATOR;
    if (lower == "ring_through") return DEV_RING_THROUGH;
    if (lower == "ring_drop")    return DEV_RING_DROP;
    if (lower == "wg")           return DEV_WAVEGUIDE;
    if (lower == "bend")         return DEV_WAVEGUIDE_BEND;
    if (lower == "crossing")     return DEV_WAVEGUIDE_CROSSING;
    if (lower == "waveguide_cross") return DEV_WAVEGUIDE_CROSSING;
    if (lower == "wg_crossing")  return DEV_WAVEGUIDE_CROSSING;
    if (lower == "pd")           return DEV_PHOTODETECTOR;
    if (lower == "detector")     return DEV_PHOTODETECTOR;
    return DEV_NONE;
}

// Split a line by commas, respecting no quoting for simplicity.
std::vector<std::string> splitCSVLine(const std::string &line) {
    std::vector<std::string> fields;
    std::string current;
    for (size_t i = 0; i < line.size(); ++i) {
        if (line[i] == ',') {
            fields.push_back(trim(current));
            current.clear();
        } else {
            current += line[i];
        }
    }
    fields.push_back(trim(current));
    return fields;
}
} // anonymous namespace

// ────────────────────────────────────────────────────────────
bool loadOpticalParamsFromCSV(const char *filename,
        OpticalParamTable &table,
        std::string &errorMsg) {
    errorMsg.clear();
    if (!filename || filename[0] == '\0') {
        errorMsg = "empty filename";
        return false;
    }

    std::ifstream file(filename);
    if (!file.is_open()) {
        errorMsg = std::string("cannot open file: ") + filename;
        return false;
    }

    int lineNo = 0;
    int loadedCount = 0;
    std::string line;

    // Expected column order
    enum Col {
        COL_DEV_TYPE = 0,
        COL_WL_INDEX,
        COL_INS_LOSS_DB,
        COL_XTALK_ADJ_DB,
        COL_XTALK_NONADJ_DB,
        COL_SOA_GAIN_DB,
        COL_SOA_NF_DB,
        COL_SOA_SAT_DBM,
        COL_PD_RESP_AW,
        COL_PD_SENS_DBM,
        COL_MOD_EFF_DB,
        COL_COUNT
    };

    while (std::getline(file, line)) {
        ++lineNo;
        std::string trimmedLine = trim(line);
        if (trimmedLine.empty() || trimmedLine[0] == '#') {
            continue; // skip empty and comment lines
        }

        std::vector<std::string> fields = splitCSVLine(trimmedLine);

        // Skip header row by checking if first field is "device_type"
        if (lineNo == 1 && !fields.empty()) {
            std::string f0 = fields[0];
            for (size_t i = 0; i < f0.size(); ++i)
                f0[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(f0[i])));
            if (f0 == "device_type" || f0 == "devicetype") {
                continue; // header row
            }
        }

        if (static_cast<int>(fields.size()) < COL_COUNT) {
            std::ostringstream oss;
            oss << filename << ":" << lineNo << ": expected " << COL_COUNT
                << " fields, got " << fields.size();
            errorMsg = oss.str();
            return false;
        }

        OpticalDeviceType devType = parseDeviceType(fields[COL_DEV_TYPE]);
        if (devType == DEV_NONE) {
            std::ostringstream oss;
            oss << filename << ":" << lineNo << ": unknown device type '"
                << fields[COL_DEV_TYPE] << "'";
            errorMsg = oss.str();
            return false;
        }

        DeviceParamKey key;
        key.deviceType = devType;
        key.wavelengthIndex = static_cast<int>(std::strtol(fields[COL_WL_INDEX].c_str(), NULL, 10));

        DevicePerWavelengthParams params;
        params.insertionLoss_dB          = std::strtod(fields[COL_INS_LOSS_DB].c_str(), NULL);
        params.crosstalkToAdjacent_dB    = std::strtod(fields[COL_XTALK_ADJ_DB].c_str(), NULL);
        params.crosstalkToNonAdjacent_dB = std::strtod(fields[COL_XTALK_NONADJ_DB].c_str(), NULL);
        params.soaGain_dB                = std::strtod(fields[COL_SOA_GAIN_DB].c_str(), NULL);
        params.soaNoiseFigure_dB         = std::strtod(fields[COL_SOA_NF_DB].c_str(), NULL);
        params.soaSaturationPower_dBm    = std::strtod(fields[COL_SOA_SAT_DBM].c_str(), NULL);
        params.pdResponsivity_AW         = std::strtod(fields[COL_PD_RESP_AW].c_str(), NULL);
        params.pdSensitivity_dBm         = std::strtod(fields[COL_PD_SENS_DBM].c_str(), NULL);
        params.modulatorEfficiency_dB    = std::strtod(fields[COL_MOD_EFF_DB].c_str(), NULL);

        table[key] = params;
        ++loadedCount;
    }

    if (loadedCount == 0) {
        errorMsg = std::string("no valid parameter rows found in ") + filename;
        return false;
    }

    EV_INFO << "Loaded " << loadedCount << " optical device parameter entries from "
            << filename << std::endl;
    return true;
}

// ────────────────────────────────────────────────────────────
void loadOpticalParamsOrDefault(const char *filename,
        OpticalParamTable &table,
        int numWavelengths) {
    // Always start with defaults
    populateDefaultOpticalParams(table, numWavelengths);

    if (!filename || filename[0] == '\0') {
        EV_INFO << "No optical device parameter file specified; using defaults." << std::endl;
        return;
    }

    std::string errorMsg;
    if (!loadOpticalParamsFromCSV(filename, table, errorMsg)) {
        EV_WARN << "Failed to load optical device parameters from '"
                << filename << "': " << errorMsg
                << ".  Falling back to defaults." << std::endl;
    }
}
