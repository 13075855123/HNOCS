//
// Copyright (C) 2024 HNOCS Project
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

#include "PowerTrace.h"
#include <iomanip>
#include <stdexcept>

void PowerTraceWriter::open(const char* filename, const char* hotspotFilename) {
    traceFile.open(filename);
    if (!traceFile.is_open()) {
        throw cRuntimeError("Cannot open power trace file: %s", filename);
    }
    // CSV header
    traceFile << "Time(ns),ComponentType,ComponentID,EventType,Value\n";

    if (hotspotFilename && hotspotFilename[0] != '\0') {
        hotspotFile.open(hotspotFilename);
        if (!hotspotFile.is_open()) {
            throw cRuntimeError("Cannot open HotSpot trace file: %s", hotspotFilename);
        }
    }

    enabled = true;
    lastRecordTime = 0;
}

void PowerTraceWriter::close() {
    if (traceFile.is_open()) {
        traceFile.close();
    }
    if (hotspotFile.is_open()) {
        hotspotFile.close();
    }
    enabled = false;
}

void PowerTraceWriter::recordPEEvent(int peId, PowerEventType type,
                                     simtime_t time, double value) {
    if (!enabled) return;

    const char* eventName;
    switch (type) {
        case PE_COMPUTE_START: eventName = "COMPUTE_START"; break;
        case PE_COMPUTE_END:   eventName = "COMPUTE_END";   break;
        case PE_SEND_FLIT:     eventName = "SEND_FLIT";     break;
        case PE_RECV_FLIT:     eventName = "RECV_FLIT";     break;
        case PE_IDLE:          eventName = "IDLE";           break;
        default:               eventName = "UNKNOWN";
    }

    traceFile << std::fixed << std::setprecision(2)
              << time.dbl() * 1e9 << ",PE," << peId << ","
              << eventName << "," << value << "\n";
}

void PowerTraceWriter::recordRouterEvent(int routerId, int portId,
                                         const char* component, long count,
                                         simtime_t time) {
    if (!enabled) return;

    traceFile << std::fixed << std::setprecision(2)
              << time.dbl() * 1e9 << ",Router," << routerId << "."
              << portId << "." << component << ",COUNT," << count << "\n";
}

void PowerTraceWriter::flushHotSpotTrace(int numPEs, int numRouters,
                                         simtime_t currentTime,
                                         const std::vector<double>& pePower,
                                         const std::vector<double>& routerPower) {
    if (!hotspotFile.is_open()) return;
    if (currentTime - lastRecordTime < samplingInterval) return;

    for (int i = 0; i < numPEs; i++) {
        hotspotFile << pePower[i] << " ";
    }
    for (int i = 0; i < numRouters; i++) {
        hotspotFile << routerPower[i] << " ";
    }
    hotspotFile << "\n";

    lastRecordTime = currentTime;
}
