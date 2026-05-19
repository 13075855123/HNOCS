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
    peReady.assign(numPEs, false);
    routerReady.assign(numRouters, false);

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
    if (traceFile.is_open()) {
        traceFile.close();
    }
    opened = false;
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

// ---- flush + thermal update ----------------------------------------------
void ThermalModel::tryFlush(simtime_t t)
{
    if (!opened) return;
    if (!allReady()) return;

    // 1) Update temperatures BEFORE writing trace
    //    (temperature always reflects "just computed" state after this window)
    if (currentWindowTime > 0.0) {
        simtime_t dt = t - lastTempTime;
        if (dt > 0.0)
            updateTemperature(dt);
    }
    lastTempTime = t;

    // 2) Write power trace line (HotSpot format)
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

// ---- RC thermal solver (explicit Euler step) -----------------------------
void ThermalModel::updateTemperature(simtime_t dt)
{
    double dt_s = dt.dbl();
    if (dt_s <= 0.0) return;

    std::vector<double> dTpe(numPEs, 0.0);
    std::vector<double> dTrouter(numRouters, 0.0);

    // === PE layer =========================================================
    for (int i = 0; i < numPEs; i++) {
        double heatIn = pePower[i];   // W = J/s

        // Vertical: convection to ambient
        heatIn -= (peTemp[i] - Tambient) / RconvPE;

        // Vertical: coupling to local router
        heatIn -= (peTemp[i] - routerTemp[i]) / Rpe2router;

        // Lateral: coupling to neighbour PEs
        std::vector<int> neighbours;
        getPENeighbours(i, neighbours);
        for (int n : neighbours) {
            heatIn -= (peTemp[i] - peTemp[n]) / RlateralPE;
        }

        dTpe[i] = (heatIn / Cpe) * dt_s;
    }

    // === Router layer =====================================================
    for (int i = 0; i < numRouters; i++) {
        double heatIn = routerPower[i];

        // Vertical: convection to ambient
        heatIn -= (routerTemp[i] - Tambient) / RconvRouter;

        // Vertical: coupling to local PE
        heatIn -= (routerTemp[i] - peTemp[i]) / Rpe2router;

        // Lateral: coupling to neighbour routers
        std::vector<int> neighbours;
        getRouterNeighbours(i, neighbours);
        for (int n : neighbours) {
            heatIn -= (routerTemp[i] - routerTemp[n]) / RlateralRouter;
        }

        dTrouter[i] = (heatIn / Crouter) * dt_s;
    }

    // Apply Euler step
    for (int i = 0; i < numPEs; i++)
        peTemp[i] += dTpe[i];
    for (int i = 0; i < numRouters; i++)
        routerTemp[i] += dTrouter[i];
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
