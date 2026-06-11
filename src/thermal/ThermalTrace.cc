/*
 * ThermalTrace.cc - unified power collection + RC thermal solver
 *
 *  Created on: 2026/04/27
 *  Updated:    2026/05/10 — closed-loop RC thermal model
 */

#include "ThermalTrace.h"
#include <algorithm>
#include <cmath>

// Global singleton
static ThermalModel* thermalModelInstance = nullptr;

ThermalModel* getThermalModel()
{
    if (!thermalModelInstance)
        thermalModelInstance = new ThermalModel();
    return thermalModelInstance;
}

// ---- constructor / destructor --------------------------------------------
ThermalModel::ThermalModel()
{
    opened = false;
    headerWritten = false;
    finishedPEs = 0;
    finishedRouters = 0;
    numPEs = 0;
    numRouters = 0;
    rows = 0;
    cols = 0;
    currentWindowTime = -1.0;

    // thermal defaults (overwritten by setThermalParams)
    RconvPE        = 10.0;      // K/W
    RconvRouter    = 10.0;      // K/W
    RlateralPE     = 5.0;       // K/W
    RlateralRouter = 5.0;       // K/W
    Rpe2router     = 2.0;       // K/W
    Cpe            = 1e-6;      // J/K
    Crouter        = 1e-7;      // J/K
    Tambient       = 318.15;    // 45 °C

    lastTempTime   = 0.0;
    pendingDt      = 0.0;
}

ThermalModel::~ThermalModel()
{
    close();
}

// ---- lifecycle -----------------------------------------------------------
void ThermalModel::open(const char* filename, int r, int c)
{
    if (opened) return;

    rows = r;
    cols = c;
    numPEs     = rows * cols;
    numRouters = rows * cols;

    pePower.assign(numPEs, 0.0);
    routerPower.assign(numRouters, 0.0);
    routerOpticalPower.assign(numRouters, 0.0);
    peReady.assign(numPEs, false);
    routerReady.assign(numRouters, false);
    routerPortPower.assign(numRouters, std::vector<double>());
    routerPortReady.assign(numRouters, std::vector<bool>());
    routerPortFinalReady.assign(numRouters, std::vector<bool>());
    routerPortWindowTime.assign(numRouters, SIMTIME_ZERO);
    peFinished.assign(numPEs, false);
    routerFinished.assign(numRouters, false);
    finishedPEs = 0;
    finishedRouters = 0;

    // Flush any optical power submitted before open() was called
    // (solves the LTM/TaskPE initialization order race)
    for (size_t i = 0; i < pendingOpticalPower.size() && i < (size_t)numRouters; ++i)
        routerOpticalPower[i] += pendingOpticalPower[i];
    pendingOpticalPower.clear();

    // Start all nodes at ambient temperature (steady-state assumption)
    peTemp.assign(numPEs, Tambient);
    routerTemp.assign(numRouters, Tambient);

    lastTempTime = 0.0;

    if (filename && filename[0] != '\0') {
        traceFile.open(filename);
    }
    // File creation is optional; continue even if skipped

    opened = true;
    headerWritten = false;
    currentWindowTime = -1.0;
}

void ThermalModel::close()
{
    if (!opened) return;

    if (traceFile.is_open()) {
        traceFile.close();
    }
    opened = false;
    writeThermalSnapshot();
}

void ThermalModel::writeThermalSnapshot()
{
    if (numPEs <= 0) return;

    std::ofstream out("thermal_snapshot.json");
    if (!out.is_open()) return;

    out << "{\n";
    out << "  \"pe_temperatures_K\": [";
    for (int i = 0; i < numPEs; i++) {
        if (i > 0) out << ", ";
        out << peTemp[i];
    }
    out << "],\n";
    out << "  \"router_temperatures_K\": [";
    for (int i = 0; i < numRouters; i++) {
        if (i > 0) out << ", ";
        out << routerTemp[i];
    }
    out << "],\n";
    out << "  \"Tambient_K\": " << Tambient << ",\n";
    out << "  \"rows\": " << rows << ",\n";
    out << "  \"cols\": " << cols << "\n";
    out << "}\n";
    out.close();
}

// ---- thermal parameters --------------------------------------------------
void ThermalModel::setThermalParams(double rconvPE, double rconvRtr,
                                     double rlatPE, double rlatRtr,
                                     double rp2r,   double cPE,
                                     double cRtr,   double tamb)
{
    RconvPE        = rconvPE;
    RconvRouter    = rconvRtr;
    RlateralPE     = rlatPE;
    RlateralRouter = rlatRtr;
    Rpe2router     = rp2r;
    Cpe            = cPE;
    Crouter        = cRtr;
    Tambient       = tamb;

    // Re-init temperatures to ambient if already opened
    if (opened) {
        peTemp.assign(numPEs, Tambient);
        routerTemp.assign(numRouters, Tambient);
        lastTempTime = 0.0;
    }
}

// ---- temperature queries -------------------------------------------------
double ThermalModel::getPEPerature(int peId) const
{
    if (peId < 0 || peId >= numPEs) return Tambient;
    return peTemp[peId];
}

double ThermalModel::getRouterTemperature(int routerId) const
{
    if (routerId < 0 || routerId >= numRouters) return Tambient;
    return routerTemp[routerId];
}

// ---- power submission ----------------------------------------------------
void ThermalModel::submitPEPower(int peId, simtime_t t, double avgPower)
{
    if (!opened) return;

    if (currentWindowTime < 0.0)
        currentWindowTime = t.dbl();

    // New window: flush previous
    if (t.dbl() != currentWindowTime) {
        tryFlush(SimTime(currentWindowTime));
        currentWindowTime = t.dbl();
    }

    if (peId < 0 || peId >= numPEs)
        throw cRuntimeError("Invalid PE id %d for thermal trace", peId);

    pePower[peId] = avgPower;
    peReady[peId] = true;

    tryFlush(t);
}

void ThermalModel::submitRouterPower(int routerId, simtime_t t, double avgPower)
{
    if (!opened) return;

    if (currentWindowTime < 0.0)
        currentWindowTime = t.dbl();

    if (t.dbl() != currentWindowTime) {
        tryFlush(SimTime(currentWindowTime));
        currentWindowTime = t.dbl();
    }

    if (routerId < 0 || routerId >= numRouters)
        throw cRuntimeError("Invalid router id %d for thermal trace", routerId);

    routerPower[routerId] = avgPower;
    routerReady[routerId] = true;

    tryFlush(t);
}

void ThermalModel::submitRouterPortPower(int routerId, int portId, int numPorts,
                                         simtime_t t, double avgPower,
                                         bool finalWindow)
{
    if (!opened) return;

    if (routerId < 0 || routerId >= numRouters)
        throw cRuntimeError("Invalid router id %d for thermal trace", routerId);
    if (numPorts <= 0)
        throw cRuntimeError("Invalid port count %d for router %d thermal trace",
                            numPorts, routerId);
    if (portId < 0 || portId >= numPorts)
        throw cRuntimeError("Invalid port id %d for router %d thermal trace",
                            portId, routerId);

    if ((int)routerPortPower[routerId].size() != numPorts) {
        routerPortPower[routerId].assign(numPorts, 0.0);
        routerPortReady[routerId].assign(numPorts, false);
        routerPortFinalReady[routerId].assign(numPorts, false);
        routerPortWindowTime[routerId] = t;
    }

    if (routerPortWindowTime[routerId] != t) {
        std::fill(routerPortPower[routerId].begin(), routerPortPower[routerId].end(), 0.0);
        std::fill(routerPortReady[routerId].begin(), routerPortReady[routerId].end(), false);
        std::fill(routerPortFinalReady[routerId].begin(), routerPortFinalReady[routerId].end(), false);
        routerPortWindowTime[routerId] = t;
    }

    routerPortPower[routerId][portId] = avgPower;
    routerPortReady[routerId][portId] = true;
    if (finalWindow)
        routerPortFinalReady[routerId][portId] = true;

    bool allPortsReady = true;
    double routerAvgPower = 0.0;
    for (int i = 0; i < numPorts; i++) {
        if (!routerPortReady[routerId][i]) {
            allPortsReady = false;
            break;
        }
        routerAvgPower += routerPortPower[routerId][i];
    }
    if (!allPortsReady)
        return;

    submitRouterPower(routerId, t, routerAvgPower);

    bool allPortsFinal = finalWindow;
    if (allPortsFinal) {
        for (int i = 0; i < numPorts; i++) {
            if (!routerPortFinalReady[routerId][i]) {
                allPortsFinal = false;
                break;
            }
        }
    }

    if (allPortsFinal && !routerFinished[routerId]) {
        routerFinished[routerId] = true;
        finishedRouters++;
        closeIfFinished();
    }
}

void ThermalModel::markPEFinished(int peId)
{
    if (!opened) return;
    if (peId < 0 || peId >= numPEs)
        throw cRuntimeError("Invalid PE id %d for thermal finish", peId);
    if (peFinished[peId])
        return;
    peFinished[peId] = true;
    finishedPEs++;
    closeIfFinished();
}

void ThermalModel::closeIfFinished()
{
    if (!opened) return;
    if (numPEs <= 0 || numRouters <= 0) return;
    if (finishedPEs >= numPEs && finishedRouters >= numRouters)
        close();
}

// ---- optical device power on routers --------------------------------------
void ThermalModel::addRouterOpticalPower(int routerId, double power_W)
{
    if (routerId < 0)
        return;

    // Buffer submissions that arrive before open() has initialised the arrays
    // (LogicalTopologyManager may initialise before TaskPE[0] calls open()).
    if (numRouters == 0) {
        if (routerId >= (int)pendingOpticalPower.size())
            pendingOpticalPower.resize(routerId + 1, 0.0);
        pendingOpticalPower[routerId] += power_W;
        return;
    }

    if (routerId >= numRouters)
        return;
    routerOpticalPower[routerId] += power_W;
}

void ThermalModel::removeRouterOpticalPower(int routerId, double power_W)
{
    if (routerId < 0 || routerId >= numRouters)
        return;
    routerOpticalPower[routerId] -= power_W;
    if (routerOpticalPower[routerId] < 0.0)
        routerOpticalPower[routerId] = 0.0;
}

// ---- flush + thermal update ----------------------------------------------
void ThermalModel::tryFlush(simtime_t t)
{
    if (!opened) return;

    // Window not yet complete: accumulate its time span so the next
    // successful flush can account for all skipped windows in one Euler step.
    if (!allReady()) {
        pendingDt += t - lastTempTime;
        lastTempTime = t;
        return;
    }

    // 1) Incorporate persistent optical device power into router power
    //    (electrical router power is overwritten each window; optical power
    //     persists across windows and is added on top each flush)
    for (int i = 0; i < numRouters; i++)
        routerPower[i] += routerOpticalPower[i];

    // 2) Update temperatures BEFORE writing trace
    //    (temperature always reflects "just computed" state after this window)
    if (currentWindowTime > 0.0) {
        simtime_t dt = t - lastTempTime + pendingDt;
        pendingDt = 0.0;
        if (dt > 0.0)
            updateTemperature(dt);
    }
    lastTempTime = t;

    // 3) Write power trace line (HotSpot format)
    writeHeader();

    bool first = true;
    for (int i = 0; i < numPEs; i++) {
        if (!first) traceFile << " ";
        traceFile << pePower[i];
        first = false;
    }
    for (int i = 0; i < numRouters; i++) {
        if (!first) traceFile << " ";
        traceFile << routerPower[i];
        first = false;
    }
    traceFile << "\n";

    // 3) Reset ready flags for next window
    for (int i = 0; i < numPEs; i++)     peReady[i] = false;
    for (int i = 0; i < numRouters; i++) routerReady[i] = false;

    currentWindowTime = t.dbl();
}

// ---- RC thermal solver (explicit Euler step with stability sub-stepping) -----
void ThermalModel::updateTemperature(simtime_t dt)
{
    double dt_s = dt.dbl();
    if (dt_s <= 0.0) return;

    // Compute the most restrictive thermal time constant across all nodes
    // for Forward Euler stability: dt < 2 * C_i / G_i  where G_i = sum(1/R_ij)
    double minTau = 1e100;
    double maxNeighbours = 4.0;  // interior mesh node

    // Router layer (smaller C → more restrictive)
    double G_router = 1.0 / RconvRouter + 1.0 / Rpe2router + maxNeighbours / RlateralRouter;
    double tau_router = Crouter / G_router;
    if (tau_router < minTau) minTau = tau_router;

    // PE layer
    double G_pe = 1.0 / RconvPE + 1.0 / Rpe2router + maxNeighbours / RlateralPE;
    double tau_pe = Cpe / G_pe;
    if (tau_pe < minTau) minTau = tau_pe;

    double maxStableDt = 2.0 * minTau;  // Forward Euler stability limit

    // Sub-step if needed
    int nSteps = 1;
    if (dt_s > maxStableDt) {
        nSteps = static_cast<int>(std::ceil(dt_s / (maxStableDt * 0.9)));  // 10% margin
    }
    double subDt = dt_s / nSteps;

    for (int step = 0; step < nSteps; step++) {
        std::vector<double> dTpe(numPEs, 0.0);
        std::vector<double> dTrouter(numRouters, 0.0);

        // === PE layer =========================================================
        for (int i = 0; i < numPEs; i++) {
            double heatIn = pePower[i];

            heatIn -= (peTemp[i] - Tambient) / RconvPE;
            heatIn -= (peTemp[i] - routerTemp[i]) / Rpe2router;

            std::vector<int> neighbours;
            getPENeighbours(i, neighbours);
            for (int n : neighbours) {
                heatIn -= (peTemp[i] - peTemp[n]) / RlateralPE;
            }

            dTpe[i] = (heatIn / Cpe) * subDt;
        }

        // === Router layer =====================================================
        for (int i = 0; i < numRouters; i++) {
            double heatIn = routerPower[i];

            heatIn -= (routerTemp[i] - Tambient) / RconvRouter;
            heatIn -= (routerTemp[i] - peTemp[i]) / Rpe2router;

            std::vector<int> neighbours;
            getRouterNeighbours(i, neighbours);
            for (int n : neighbours) {
                heatIn -= (routerTemp[i] - routerTemp[n]) / RlateralRouter;
            }

            dTrouter[i] = (heatIn / Crouter) * subDt;
        }

        // Apply sub-step
        for (int i = 0; i < numPEs; i++) {
            peTemp[i] += dTpe[i];
            if (peTemp[i] < Tambient) peTemp[i] = Tambient;
        }
        for (int i = 0; i < numRouters; i++) {
            routerTemp[i] += dTrouter[i];
            if (routerTemp[i] < Tambient) routerTemp[i] = Tambient;
        }
    }
}

// ---- mesh neighbour helpers ----------------------------------------------
void ThermalModel::getPENeighbours(int peId, std::vector<int>& neighbours) const
{
    neighbours.clear();
    int r = peId / cols;
    int c = peId % cols;

    if (r > 0)            neighbours.push_back((r - 1) * cols + c);
    if (r < rows - 1)     neighbours.push_back((r + 1) * cols + c);
    if (c > 0)            neighbours.push_back(r * cols + (c - 1));
    if (c < cols - 1)     neighbours.push_back(r * cols + (c + 1));
}

void ThermalModel::getRouterNeighbours(int routerId,
                                       std::vector<int>& neighbours) const
{
    // Same mesh topology as PEs
    getPENeighbours(routerId, neighbours);
}

// ---- HotSpot header ------------------------------------------------------
void ThermalModel::writeHeader()
{
    if (headerWritten) return;

    bool first = true;
    for (int i = 0; i < numPEs; i++) {
        if (!first) traceFile << " ";
        traceFile << "PE" << i;
        first = false;
    }
    for (int i = 0; i < numRouters; i++) {
        if (!first) traceFile << " ";
        traceFile << "R" << i;
        first = false;
    }
    traceFile << "\n";
    headerWritten = true;
}

// ---- ready check ---------------------------------------------------------
bool ThermalModel::allReady() const
{
    for (int i = 0; i < numPEs; i++)
        if (!peReady[i]) return false;
    for (int i = 0; i < numRouters; i++)
        if (!routerReady[i]) return false;
    return true;
}
