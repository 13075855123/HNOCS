#ifndef __HNOCS_TASK_PE_H_
#define __HNOCS_TASK_PE_H_

#include <omnetpp.h>
#include <queue>
#include <map>
#include <vector>
#include "TaskDescriptor.h"
#include "PowerTrace.h"
#include "NoCs_m.h"
#include "messages/TaskMsg_m.h"
#include "thermal/ThermalTrace.h"


using namespace omnetpp;

class TaskPE : public cSimpleModule {
private:
    // === Parameters ===
    int peId;
    int numVCs;
    int flitSize;
    simtime_t statStartTime;
    int bufferBaseId;
    int numColumns;

    // === Task management ===
    std::vector<TaskDescriptor*> taskList;
    std::queue<TaskDescriptor*> readyQueue;
    std::map<int, TaskDescriptor*> taskMap;
    TaskDescriptor* currentTask;

    // === Receive buffer: accumulate flits per packet until END flit ===
    std::map<int, std::vector<TaskMsg*>> recvBuffer;

    // === Dependency tracking ===
    std::map<int, int> receivedDependencies;

    // === Self-messages ===
    cMessage* computeCompleteMsg;
    cMessage* powerSampleMsg;
    cMessage* injectPopMsg;

    // NEW: periodic energy window timer
    cMessage* energyWindowMsg;

    // === Injection-side state ===
    std::queue<TaskMsg*> injectQ;
    int credits;   // send-side credits on VC0

    // === Statistics ===
    long totalTasksCompleted;
    long totalFlitsSent;
    long totalFlitsReceived;
    simtime_t totalComputeTime;
    simtime_t totalIdleTime;
    simtime_t totalThrottlePenalty;   // extra time due to thermal throttling
    simtime_t totalComputeTimeNominal; // base compute time (no throttling)
    simtime_t lastEventTime;
    bool isIdle;

    // Instantaneous power
    double currentPower;
    double peakPower;
    double avgPower;

    // Power model parameters
    double powerIdle;
    double powerCompute;
    double powerSendPerFlit;
    double powerRecvPerFlit;

    double computeDensity;  // ns/B, 0=use CSV computeTime

    // NEW: window-based energy parameters/state
    simtime_t energyWindow;
    simtime_t lastEnergyUpdateTime;
    long windowSendFlits;
    long windowRecvFlits;
    double windowEnergyJ;
    double totalEnergyJ;

    // Separate static vs dynamic energy tracking
    double windowStaticEnergyJ;
    double windowDynamicEnergyJ;
    double totalStaticEnergyJ;
    double totalDynamicEnergyJ;

    // Power trace
    PowerTraceWriter* powerTrace;
    bool enablePowerTrace;

    // OMNeT++ output vectors / scalars
    cOutVector powerVec;

    // NEW: energy vectors
    cOutVector windowEnergyVec;
    cOutVector cumulativeEnergyVec;
    cOutVector windowAvgPowerVec;
    // Separate static / dynamic energy vectors
    cOutVector windowStaticEnergyVec;
    cOutVector windowDynamicEnergyVec;
    cOutVector cumulativeStaticEnergyVec;
    cOutVector cumulativeDynamicEnergyVec;

    // Global packet-id counter
    int pktIdCounter;

    // === Helpers ===
    void loadTaskGraphFromCSV(const std::string& csvPath);

    void scheduleNextTask();
    void startComputation(TaskDescriptor* task);
    void completeComputation();
    void sendTaskData(TaskDescriptor* task);
    void sendFlitFromQ();
    void handleDataArrival(TaskMsg* msg);
    int  calculateNumFlits(int dataSize) const;

    void updatePower(bool isIdlePower);
    void samplePower();
    double getTemperatureCorrectedPower(bool idle) const;
    double getDvfsScaleFactor() const;   // 1.0 at safe temp, >1.0 above threshold

    // NEW: PE energy helpers
    void accumulatePEStaticEnergy(simtime_t now);
    void finalizeEnergyWindow(simtime_t now);

    // Temperature-based display color update
    void updateThermalDisplay();

    // Per-PE temperature output vector
    cOutVector peTempVec;

    // Global task completion tracking (shared across all PEs)
    static int systemTotalTasks;
    static int systemCompletedTasks;
    static bool systemStopScheduled;

    // return credits to router when TaskPE is receiver
    void sendCredit(int vc, int numFlits);

    double tClk_s;

protected:
    virtual void initialize() override;
    virtual void handleMessage(cMessage* msg) override;
    virtual void finish() override;

public:
    virtual ~TaskPE();

    double getCurrentPower()  const { return currentPower; }
    double getUtilization()   const;
};

#endif // __HNOCS_TASK_PE_H_
