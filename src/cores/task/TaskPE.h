#ifndef __HNOCS_TASK_PE_H_
#define __HNOCS_TASK_PE_H_

#include <omnetpp.h>
#include <queue>
#include <map>
#include <set>
#include <vector>
#include "TaskDescriptor.h"
#include "PowerTrace.h"
#include "NoCs_m.h"
#include "messages/TaskMsg_m.h"
#include "thermal/ThermalTrace.h"
#include "onoc/common/ControlPlaneEvents.h"

using namespace omnetpp;

class LogicalTopologyManager;

class TaskPE : public cSimpleModule, public cListener {
private:
    // === Parameters ===
    int peId;
    int numVCs;
    int flitSize;
    simtime_t statStartTime;
    int bufferBaseId;
    int numColumns;
    int numRows;

    // === Optical bypass parameters ===
    bool enableSetupHandshake;
    bool enableOpticalBypass;
    simtime_t setupRetryDelay;
    simtime_t setupPendingTimeout;
    int opticalRequiredWavelengths;
    double opticalWavelengthBitrate;
    simtime_t opticalBasePropagationDelay;
    simtime_t opticalPerHopDelay;

    // === Optical state ===
    int numNodes;
    LogicalTopologyManager *topologyManager = nullptr;
    std::vector<unsigned char> circuitReadyByDst;
    std::vector<unsigned char> setupPendingByDst;
    std::vector<simtime_t> nextSetupAttemptByDst;
    std::vector<simtime_t> setupPendingExpiryByDst;
    std::vector<int> pendingSetupTokenByDst;
    std::vector<int> activeCircuitTokenByDst;
    std::set<cMessage*> pendingOpticalReleaseMsgs;
    long setupReqRxCount;
    long setupAckRxCount;
    mutable long opticalPacketsSent;
    mutable simtime_t lastOpticalSendTime;
    long setupAckAcceptedCount;
    long setupAckStaleCount;
    long setupReserveFailCount;
    long setupPendingTimeoutCount;
    simsignal_t setupReqEventSignal;
    simsignal_t setupAckEventSignal;

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
    cMessage* powerSampleMsg = nullptr;
    cMessage* injectPopMsg = nullptr;
    cMessage* energyWindowMsg = nullptr;
    cMessage* controlPopMsg = nullptr;   // drives controlQ (SETUP_REQ/ACK)
    cMessage* opticalPopMsg = nullptr;   // drives opticalDataQ (sendDirect)
    cMessage* dvfsTickMsg = nullptr;     // periodic DVFS temperature re-check

    // === Periodic DVFS throttling ===
    simtime_t remainingNominalWork;  // how much nominal compute time left
    simtime_t dvfsTickInterval;      // interval between DVFS re-checks (default 100ns)
    simtime_t lastDvfsUpdateTime;    // last time nominal work was advanced

    // === Injection-side state ===
    std::queue<TaskMsg*> injectQ;       // regular data via router (GB)
    cQueue controlQ;                     // SETUP_REQ/ACK via router
    cQueue opticalDataQ;                 // PE→PE data via sendDirect (circuit ready)
    std::vector<std::vector<TaskMsg*>> pendingDataQ; // per-dst pending data (wait ACK)
    int credits;   // send-side credits on VC0 (shared: injectQ + controlQ)

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
    double opticalModulatorEnergyPerFlit;
    double opticalReceiverEnergyPerFlit;

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

    // === Optical helpers ===
    void ensureOpticalStateSize(int dst);
    bool tryReserveSetupPath(int dst, int &token);
    void sendControlFlitFromQ();
    void sendOpticalFlitFromQ();
    void flushPendingData(int dst);
    int  meshHopDistance(int src, int dst) const;
    simtime_t computeOpticalPropagationDelay(int src, int dst) const;
    simtime_t computeOpticalTxDuration(const TaskMsg *flit) const;
    bool sendFlitDirectToSink(TaskMsg *flit);
    cSimpleModule *getDestinationPEModule(int dst) const;
    void handleControlEvent(int eventType, int requesterId, int targetId, int token);
    void purgeControlFlitsForSetup(int token);
    void scheduleControlPopIfNeeded(simtime_t minDelay);
    void scheduleOpticalRelease(int dstIdx, int token, simtime_t delay);
    void handleOpticalRelease(cMessage *msg);

    // === Helpers ===
    void loadTaskGraphFromCSV(const std::string& csvPath);

    void scheduleNextTask();
    void startComputation(TaskDescriptor* task);
    void handleDvfsTick();
    void completeComputation();
    void markDependencySatisfied(int targetTaskId, int producerTaskId,
            const char *source, bool scheduleImmediately);
    void sendTaskData(TaskDescriptor* task);
    void sendFlitFromQ();
    void handleDataArrival(TaskMsg* msg);
    int  calculateNumFlits(int dataSize) const;

    void updatePower(bool isIdlePower);
    void samplePower();
    double getTemperatureCorrectedPower(bool idle) const;
    double getDvfsScaleFactor() const;

    void accumulatePEStaticEnergy(simtime_t now);
    void finalizeEnergyWindow(simtime_t now);
    void updateThermalDisplay();

    cOutVector peTempVec;

    static int systemTotalTasks;
    static int systemCompletedTasks;
    static bool systemStopScheduled;

    void sendCredit(int vc, int numFlits);

    double tClk_s;

protected:
    virtual void initialize() override;
    virtual void handleMessage(cMessage* msg) override;
    virtual void finish() override;
    virtual void refreshDisplay() const override;
    virtual void receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details) override;

private:
    void updateOpticalLabel();

public:
    virtual ~TaskPE();

    double getCurrentPower()  const { return currentPower; }
    double getUtilization()   const;
    bool isAllDataSent() const {
        // All send queues must be drained
        if (!injectQ.empty() || !controlQ.isEmpty() || !opticalDataQ.isEmpty())
            return false;
        for (int d = 0; d < (int)pendingDataQ.size(); d++)
            if (!pendingDataQ[d].empty()) return false;
        // No in-flight sendDirect transmission
        if (opticalPopMsg && opticalPopMsg->isScheduled()) return false;
        // Allow 500ns grace for last sendDirect to reach GB
        if (simTime() - lastOpticalSendTime < SimTime(500, SIMTIME_NS)) return false;
        return true;
    }
};

#endif // __HNOCS_TASK_PE_H_
