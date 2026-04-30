/*
 * ThermalTrace.h
 *
 *  Created on: 2026年4月27日
 *      Author: lenovo
 */

#ifndef THERMAL_THERMALTRACE_H_
#define THERMAL_THERMALTRACE_H_


#include <omnetpp.h>
#include <fstream>
#include <vector>
#include <string>

using namespace omnetpp;

class ThermalTraceWriter
{
  private:
    bool opened;
    bool headerWritten;
    std::ofstream trace;

    int numPEs;
    int numRouters;

    std::vector<double> pePower;
    std::vector<double> routerPower;
    std::vector<bool> peReady;
    std::vector<bool> routerReady;

    double currentWindowTime;

  public:
    ThermalTraceWriter();
    ~ThermalTraceWriter();

    void open(const char* filename, int pes, int routers);
    void close();

    void submitPEPower(int peId, simtime_t t, double avgPower);
    void submitRouterPower(int routerId, simtime_t t, double avgPower);

  private:
    void tryFlush(simtime_t t);
    void writeHeader();
    bool allReady() const;
};

ThermalTraceWriter* getThermalTraceWriter();


#endif /* THERMAL_THERMALTRACE_H_ */
