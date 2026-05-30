//
// Copyright (C) 2024 HNOCS Project
//

#ifndef __HNOCS_GLOBAL_BUFFER_H_
#define __HNOCS_GLOBAL_BUFFER_H_

#include <omnetpp.h>
#include <queue>
#include <map>
#include <vector>
#include "cores/task/TaskDescriptor.h"
#include "NoCs_m.h"
#include "messages/TaskMsg_m.h"

using namespace omnetpp;

class LogicalTopologyManager;

class GlobalBuffer : public cSimpleModule {
private:
    int numConnections;
    int flitSize;
    int baseId;
    int numColumns;

    std::vector<TaskDescriptor*> taskList;
    std::map<int, TaskDescriptor*> taskMap;

    std::vector<std::queue<TaskMsg*>> injectQ;
    std::vector<int> credits;

    cMessage* injectPopMsg;
    long totalFlitsSent;
    long totalFlitsReceived;
    int pktIdCounter;
    double tClk_s;

    // ── Optical bypass for GB→PE ──
    bool enableSetupHandshake;
    bool enableOpticalBypass;
    int numPEs;
    LogicalTopologyManager *topologyManager = nullptr;
    std::vector<unsigned char> circuitReadyByDst;
    std::vector<unsigned char> setupPendingByDst;
    std::vector<simtime_t> nextSetupAttemptByDst;
    std::vector<simtime_t> setupPendingExpiryByDst;
    std::vector<int> pendingSetupTokenByDst;
    std::vector<int> activeCircuitTokenByDst;
    std::vector<std::vector<TaskMsg*>> pendingDataQ;
    cQueue opticalDataQ;                // data flits for sendDirect
    cMessage* opticalPopMsg = nullptr;  // paces optical send
    std::vector<cQueue> controlQ;       // per-connector ACK queue
    cMessage* optPopMsg = nullptr;
    simtime_t setupRetryDelay;
    simtime_t setupPendingTimeout;
    int opticalRequiredWavelengths;
    double opticalWavelengthBitrate;
    simtime_t opticalBasePropagationDelay;
    simtime_t opticalPerHopDelay;

    void sendOpticalControlFlit();
    void sendFlitOptical();             // send from opticalDataQ via sendDirect
    bool sendFlitDirectToPE(TaskMsg *flit);
    bool tryReserveSetupPath(int dstPE, int &token);
    void flushPendingData(int peId);

    void loadTaskGraphFromCSV(const std::string& csvPath);
    void distributeTasks();
    void queueFlit(int connIdx, int dstPE, int taskId, int dataSize, double computeTime);
    void sendFlitFromAllQs();
    void sendFlitFromQ(int connIdx);
    void sendCredit(int connIdx, int vc, int numFlits);
    void handleDataArrival(int connIdx, TaskMsg* msg);
    int  calculateNumFlits(int dataSize) const;
    int  makePktId();

protected:
    virtual void initialize() override;
    virtual void handleMessage(cMessage* msg) override;
    virtual void finish() override;

public:
    virtual ~GlobalBuffer();
};

#endif
