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

class GlobalBuffer : public cSimpleModule {
private:
    int numConnections;
    int flitSize;
    int baseId;

    std::vector<TaskDescriptor*> taskList;
    std::map<int, TaskDescriptor*> taskMap;

    std::vector<std::queue<TaskMsg*>> injectQ;
    std::vector<int> credits;

    cMessage* injectPopMsg;
    long totalFlitsSent;
    long totalFlitsReceived;
    int pktIdCounter;
    double tClk_s;

    // Dynamic temperature-aware PE assignment
    double wTemperature;
    double wHopCount;

    // Scheduling state
    std::vector<int> peCurrentTask;   // taskId or -1 (idle)
    int totalDynamicTasks;            // count of peId=-2 tasks from CSV
    int resultPacketsExpected;        // tasks that send results back to GB
    int resultPacketsReceived;        // END flits received for those tasks

    int pickBestIdlePE(TaskDescriptor* task);
    void injectTask(TaskDescriptor* task, int dstPE);
    void injectReadyTasks();          // inject all ready (deps satisfied) peId=-2 tasks

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
