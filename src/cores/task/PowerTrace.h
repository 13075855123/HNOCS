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

#ifndef __HNOCS_POWER_TRACE_H_
#define __HNOCS_POWER_TRACE_H_

#include <omnetpp.h>
#include <fstream>
#include <string>
#include <vector>

using namespace omnetpp;

// Power event categories
enum PowerEventType {
    PE_COMPUTE_START,
    PE_COMPUTE_END,
    PE_SEND_FLIT,
    PE_RECV_FLIT,
    PE_IDLE
};

// Records power events to CSV and optionally generates HotSpot-format traces
class PowerTraceWriter {
private:
    std::ofstream traceFile;
    std::ofstream hotspotFile;
    bool enabled;
    simtime_t lastRecordTime;
    double samplingInterval;  // sampling interval (seconds)

public:
    PowerTraceWriter() : enabled(false), lastRecordTime(0), samplingInterval(1e-6) {}

    void open(const char* filename, const char* hotspotFilename = nullptr);
    void close();

    // Record a PE power event
    void recordPEEvent(int peId, PowerEventType type, simtime_t time, double value = 0.0);

    // Record a router activity event
    void recordRouterEvent(int routerId, int portId, const char* component,
                           long count, simtime_t time);

    // Append one HotSpot power sample line
    void flushHotSpotTrace(int numPEs, int numRouters, simtime_t currentTime,
                           const std::vector<double>& pePower,
                           const std::vector<double>& routerPower);

    bool isEnabled() const { return enabled; }
    void setSamplingInterval(double interval) { samplingInterval = interval; }
};

#endif // __HNOCS_POWER_TRACE_H_
