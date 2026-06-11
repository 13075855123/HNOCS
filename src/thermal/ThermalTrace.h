/*
 * ThermalTrace.h - unified power collection + RC thermal model
 *
 *  Created on: 2026年4月27日
 *  Updated:    2026年5月10日 — add closed-loop thermal solver
 */

#ifndef THERMAL_THERMALTRACE_H_
#define THERMAL_THERMALTRACE_H_

#include <omnetpp.h>
#include <fstream>
#include <vector>
#include <string>

using namespace omnetpp;

// ---------------------------------------------------------------------------
// ThermalModel — collects per-node power and solves an RC thermal network
//                 in lockstep with the simulation (every energy window).
// ---------------------------------------------------------------------------
class ThermalModel
{
  private:
    // --- geometry ---
    int numPEs;
    int numRouters;
    int rows;
    int cols;

    // --- power input buffers (filled by submit*Power) ---
    std::vector<double> pePower;      // W
    std::vector<double> routerPower;  // W
    std::vector<bool>   peReady;
    std::vector<bool>   routerReady;
    std::vector<std::vector<double> > routerPortPower; // W per router port
    std::vector<std::vector<bool> > routerPortReady;
    std::vector<std::vector<bool> > routerPortFinalReady;
    std::vector<simtime_t> routerPortWindowTime;

    // --- optical device power superimposed onto routers (persistent) ---
    std::vector<double> routerOpticalPower;  // W
    std::vector<double> pendingOpticalPower; // W — cached before open() is called

    // --- temperature state (K) ---
    std::vector<double> peTemp;
    std::vector<double> routerTemp;

    // --- RC thermal parameters (K/W, J/K) ---
    double RconvPE;          // vertical convection PE → ambient
    double RconvRouter;      // vertical convection router → ambient
    double RlateralPE;       // lateral PE↔PE neighbour
    double RlateralRouter;   // lateral router↔router neighbour
    double Rpe2router;       // vertical PE↔local router
    double Cpe;              // thermal capacitance PE (J/K)
    double Crouter;          // thermal capacitance router (J/K)
    double Tambient;         // ambient temperature (K)

    // --- solver state ---
    simtime_t lastTempTime;
    simtime_t pendingDt;      // accumulated dt from skipped (unflushed) windows

    // --- HotSpot trace output ---
    std::ofstream traceFile;
    bool opened;
    bool headerWritten;
    double currentWindowTime;
    std::vector<bool> peFinished;
    std::vector<bool> routerFinished;
    int finishedPEs;
    int finishedRouters;

  public:
    ThermalModel();
    ~ThermalModel();

    // ---- lifecycle -------------------------------------------------------
    void open(const char* hotspotFilename, int rows, int cols);
    void close();
    void writeThermalSnapshot();  // dump final PE temps as JSON

    // ---- power submission (called from TaskPE / InPortSync windows) -------
    void submitPEPower(int peId, simtime_t t, double avgPower);
    void submitRouterPower(int routerId, simtime_t t, double avgPower);
    void submitRouterPortPower(int routerId, int portId, int numPorts,
                               simtime_t t, double avgPower,
                               bool finalWindow = false);
    void markPEFinished(int peId);

    // ---- optical device power on routers ---------------------------------
    void addRouterOpticalPower(int routerId, double power_W);
    void removeRouterOpticalPower(int routerId, double power_W);

    // ---- temperature queries (called by routing / display) ---------------
    double getPEPerature(int peId) const;
    double getRouterTemperature(int routerId) const;

    // ---- thermal-parameter setters (called once from initialize) ----------
    void setThermalParams(double rconvPE, double rconvRtr,
                          double rlatPE, double rlatRtr,
                          double rp2r,   double cPE,
                          double cRtr,   double tamb);

  private:
    void writeHeader();
    bool allReady() const;
    void tryFlush(simtime_t t);
    void updateTemperature(simtime_t dt);
    void closeIfFinished();

    // neighbour indices for the 2-D mesh
    void getPENeighbours(int peId, std::vector<int>& neighbours) const;
    void getRouterNeighbours(int routerId, std::vector<int>& neighbours) const;
};

// Global singleton (lazy) — accessible from any module
ThermalModel* getThermalModel();

#endif /* THERMAL_THERMALTRACE_H_ */
