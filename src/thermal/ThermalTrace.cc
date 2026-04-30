#include "ThermalTrace.h"
#include <algorithm>

// Global singleton writer (lazy initialization)
static ThermalTraceWriter* gThermalTraceWriter = nullptr;

ThermalTraceWriter* getThermalTraceWriter()
{
    if (!gThermalTraceWriter) {
        gThermalTraceWriter = new ThermalTraceWriter();
    }
    return gThermalTraceWriter;
}

ThermalTraceWriter::ThermalTraceWriter()
{
    opened = false;
    headerWritten = false;
    numPEs = 0;
    numRouters = 0;
    currentWindowTime = -1.0;   // FIXED: use double, not simtime_t
}

ThermalTraceWriter::~ThermalTraceWriter()
{
    close();
}

void ThermalTraceWriter::open(const char* filename, int pes, int routers)
{
    if (opened)
        return;

    numPEs = pes;
    numRouters = routers;

    pePower.assign(numPEs, 0.0);
    routerPower.assign(numRouters, 0.0);
    peReady.assign(numPEs, false);
    routerReady.assign(numRouters, false);

    trace.open(filename);
    if (!trace.is_open()) {
        throw cRuntimeError("Failed to open thermal trace file: %s", filename);
    }

    opened = true;
    headerWritten = false;
    currentWindowTime = -1.0;   // FIXED
}

void ThermalTraceWriter::close()
{
    if (trace.is_open()) {
        trace.close();
    }
    opened = false;
}

void ThermalTraceWriter::writeHeader()
{
    if (headerWritten) return;

    bool first = true;

    for (int i = 0; i < numPEs; i++) {
        if (!first) trace << " ";
        trace << "PE" << i;
        first = false;
    }

    for (int i = 0; i < numRouters; i++) {
        if (!first) trace << " ";
        trace << "R" << i;
        first = false;
    }

    trace << "\n";
    headerWritten = true;
}

bool ThermalTraceWriter::allReady() const
{
    for (bool b : peReady) {
        if (!b) return false;
    }
    for (bool b : routerReady) {
        if (!b) return false;
    }
    return true;
}

void ThermalTraceWriter::submitPEPower(int peId, simtime_t t, double avgPower)
{
    if (!opened) return;

    if (currentWindowTime < 0.0) {
        currentWindowTime = t.dbl();
    }

    if (t.dbl() != currentWindowTime) {
        tryFlush(SimTime(currentWindowTime));
        currentWindowTime = t.dbl();
    }

    if (peId < 0 || peId >= numPEs) {
        throw cRuntimeError("Invalid PE id %d for thermal trace", peId);
    }

    pePower[peId] = avgPower;
    peReady[peId] = true;

    tryFlush(t);
}

void ThermalTraceWriter::submitRouterPower(int routerId, simtime_t t, double avgPower)
{
    if (!opened) return;

    if (currentWindowTime < 0.0) {
        currentWindowTime = t.dbl();
    }

    if (t.dbl() != currentWindowTime) {
        tryFlush(SimTime(currentWindowTime));
        currentWindowTime = t.dbl();
    }

    if (routerId < 0 || routerId >= numRouters) {
        throw cRuntimeError("Invalid router id %d for thermal trace", routerId);
    }

    routerPower[routerId] = avgPower;
    routerReady[routerId] = true;

    tryFlush(t);
}

void ThermalTraceWriter::tryFlush(simtime_t t)
{
    if (!opened) return;
    if (!allReady()) return;

    writeHeader();

    bool first = true;
    for (int i = 0; i < numPEs; i++) {
        if (!first) trace << " ";
        trace << pePower[i];
        first = false;
    }
    for (int i = 0; i < numRouters; i++) {
        if (!first) trace << " ";
        trace << routerPower[i];
        first = false;
    }
    trace << "\n";

    for (size_t i = 0; i < peReady.size(); i++) peReady[i] = false;
    for (size_t i = 0; i < routerReady.size(); i++) routerReady[i] = false;

    currentWindowTime = t.dbl();
}
