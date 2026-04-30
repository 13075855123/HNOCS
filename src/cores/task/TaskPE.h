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
#include "../thermal/ThermalTrace.h"


using namespace omnetpp;

class TaskPE : public cSimpleModule {
private:
    // === Parameters ===
    int peId;
    int numVCs;
    int flitSize;
    simtime_t statStartTime;
    std::string applicationName;

    // === Task management ===
    std::vector<TaskDescriptor*> taskList;
    std::queue<TaskDescriptor*> readyQueue;
    std::map<int, TaskDescriptor*> taskMap;
    TaskDescriptor* currentTask;

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

    // NEW: window-based energy parameters/state
    simtime_t energyWindow;
    simtime_t lastEnergyUpdateTime;
    long windowSendFlits;
    long windowRecvFlits;
    double windowEnergyJ;
    double totalEnergyJ;

    // Power trace
    PowerTraceWriter* powerTrace;
    bool enablePowerTrace;

    // OMNeT++ output vectors / scalars
    cOutVector powerVec;

    // NEW: energy vectors
    cOutVector windowEnergyVec;
    cOutVector cumulativeEnergyVec;
    cOutVector windowAvgPowerVec;

    // Global packet-id counter
    int pktIdCounter;

    // === Helpers ===
    void loadTaskGraph();
    void loadMatrixMultiplyTasks();
    void loadCNNInferenceTasks();
    void loadGraphTraversalTasks();

    void scheduleNextTask();
    void startComputation(TaskDescriptor* task);
    void completeComputation();
    void sendTaskData(TaskDescriptor* task);
    void sendFlitFromQ();
    void handleDataArrival(TaskMsg* msg);
    int  calculateNumFlits(int dataSize) const;

    void updatePower(double newPower);
    void samplePower();

    // NEW: PE energy helpers
    void accumulatePEStaticEnergy(simtime_t now);
    void finalizeEnergyWindow(simtime_t now);

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
