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

#ifndef __HNOCS_TASK_PE_H_
#define __HNOCS_TASK_PE_H_

#include <omnetpp.h>
#include <queue>
#include <map>
#include <vector>
#include "TaskDescriptor.h"
#include "PowerTrace.h"
#include "NoCs_m.h"

using namespace omnetpp;

// Forward declaration
class TaskMsg;

//
// Task-driven Processing Element (PE).
//
// Replaces the random-traffic source+sink pair with a realistic
// computation-communication model driven by a user-defined task graph.
// Implements the NI_Ifc interface so that it can be plugged into any
// topology that uses NI_Ifc cores.
//
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
    // Maps taskId -> number of dependency messages already received
    std::map<int, int> receivedDependencies;

    // === Self-messages ===
    cMessage* computeCompleteMsg;
    cMessage* powerSampleMsg;

    // === Statistics ===
    long totalTasksCompleted;
    long totalFlitsSent;
    long totalFlitsReceived;
    simtime_t totalComputeTime;
    simtime_t totalIdleTime;
    simtime_t lastEventTime;
    bool isIdle;

    // Instantaneous power
    double currentPower;    // current power (W)
    double peakPower;       // peak power (W)
    double avgPower;        // average power (W)

    // Power model parameters
    double powerIdle;           // idle power (W)
    double powerCompute;        // compute power (W)
    double powerSendPerFlit;    // energy per sent flit (J)
    double powerRecvPerFlit;    // energy per received flit (J)

    // Power trace
    PowerTraceWriter* powerTrace;
    bool enablePowerTrace;

    // OMNeT++ output vectors / scalars
    cOutVector powerVec;

    // Global packet-id counter (shared across all flits of one data transfer)
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
    void handleDataArrival(TaskMsg* msg);
    int  calculateNumFlits(int dataSize) const;

    void updatePower(double newPower);
    void samplePower();

    double tClk_s;   // clock period derived from output link

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
