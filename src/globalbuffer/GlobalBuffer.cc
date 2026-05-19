//
// Copyright (C) 2024 HNOCS Project
//
// GlobalBuffer — dependency-driven temperature-aware task scheduling
//

#include "GlobalBuffer.h"
#include "utils/TaskGraphParser.h"
#include "thermal/ThermalTrace.h"

Define_Module(GlobalBuffer);

void GlobalBuffer::initialize() {
    numConnections  = par("numConnections");
    flitSize        = par("flitSize");
    baseId          = par("baseId");
    int initialCredits = par("initialCredits");

    totalFlitsSent     = 0;
    totalFlitsReceived = 0;
    pktIdCounter        = 0;

    injectQ.resize(numConnections);
    credits.resize(numConnections);

    tClk_s = 2e-9;

    wTemperature   = par("wTemperature");
    wHopCount      = par("wHopCount");

    int numPEs = (int)getSystemModule()->par("rows") * (int)getSystemModule()->par("columns");
    peCurrentTask.assign(numPEs, -1);
    totalDynamicTasks      = 0;
    resultPacketsExpected  = 0;
    resultPacketsReceived  = 0;

    injectPopMsg = new cMessage("injectPop");

    for (int i = 0; i < numConnections; i++) {
        cGate* g = gateHalf("in", cGate::OUTPUT, i);
        if (g && g->isConnected()) {
            sendCredit(i, 0, initialCredits);
        }
    }

    const char* csvPath = par("csvFile").stringValue();
    if (csvPath && csvPath[0] != '\0') {
        loadTaskGraphFromCSV(csvPath);
    }

    scheduleAt(simTime() + tClk_s, injectPopMsg);

    distributeTasks();

    EV << "-I- GlobalBuffer init"
       << " numConnections=" << numConnections
       << " baseId=" << baseId
       << " numTasks=" << taskList.size()
       << endl;
}

void GlobalBuffer::handleMessage(cMessage* msg) {
    if (msg == injectPopMsg) {
        sendFlitFromAllQs();
        scheduleAt(simTime() + tClk_s, injectPopMsg);
        return;
    }

    if (msg->getKind() == NOC_CREDIT_MSG) {
        NoCCreditMsg* crd = check_and_cast<NoCCreditMsg*>(msg);
        int vc = crd->getVC();
        int flits = crd->getFlits();

        int connIdx = -1;
        int gateId = msg->getArrivalGateId();
        for (int i = 0; i < numConnections; i++) {
            if (gateId == gateHalf("out", cGate::INPUT, i)->getId()) {
                connIdx = i;
                break;
            }
        }

        if (connIdx >= 0 && vc == 0) {
            credits[connIdx] += flits;
        }

        delete crd;
        if (connIdx >= 0) sendFlitFromQ(connIdx);
        return;
    }

    if (msg->getKind() == NOC_FLIT_MSG) {
        TaskMsg* taskMsg = dynamic_cast<TaskMsg*>(msg);
        if (taskMsg) {
            int connIdx = -1;
            int gateId = msg->getArrivalGateId();
            for (int i = 0; i < numConnections; i++) {
                if (gateId == gateHalf("in", cGate::INPUT, i)->getId()) {
                    connIdx = i;
                    break;
                }
            }
            if (connIdx >= 0) {
                handleDataArrival(connIdx, taskMsg);
            } else {
                delete taskMsg;
            }
        } else {
            delete msg;
        }
        return;
    }

    delete msg;
}

void GlobalBuffer::finish() {
    int completedCount = 0;
    for (TaskDescriptor* t : taskList) {
        if (t->assignedPE >= 0) completedCount++;
    }
    recordScalar("totalFlitsSent",     totalFlitsSent);
    recordScalar("totalFlitsReceived", totalFlitsReceived);
    recordScalar("totalTasks",         (long)taskList.size());
    recordScalar("tasksCompleted",     (long)completedCount);
}

GlobalBuffer::~GlobalBuffer() {
    cancelAndDelete(injectPopMsg);
    for (TaskDescriptor* t : taskList) delete t;
    for (int i = 0; i < numConnections; i++) {
        while (!injectQ[i].empty()) {
            delete injectQ[i].front();
            injectQ[i].pop();
        }
    }
}

// -----------------------------------------------------------------------
void GlobalBuffer::loadTaskGraphFromCSV(const std::string& csvPath) {
    std::vector<TaskDescriptor*> allTasks = TaskGraphParser::parse(csvPath.c_str());
    for (TaskDescriptor* t : allTasks) {
        taskList.push_back(t);
        taskMap[t->taskId] = t;
    }
    EV << "-I- GlobalBuffer loaded " << taskList.size()
       << " tasks from " << csvPath << endl;
}

// -----------------------------------------------------------------------
void GlobalBuffer::distributeTasks() {
    int columns = (int)getSystemModule()->par("columns");

    // Explicit GB injection tasks (peId == -1)
    bool hasExplicit = false;
    for (TaskDescriptor* gbTask : taskList) {
        if (gbTask->assignedPE != -1) continue;
        hasExplicit = true;

        for (int succId : gbTask->successors) {
            auto sit = gbTask->successorPE.find(succId);
            if (sit == gbTask->successorPE.end()) continue;

            int dstPE = sit->second;
            int dstRow = dstPE / columns;
            int connIdx = dstRow;
            if (connIdx < 0 || connIdx >= numConnections) continue;
            queueFlit(connIdx, dstPE, succId, gbTask->outputDataSize,
                      gbTask->computeTime.dbl());
        }
    }

    // remapToDynamic: convert peId >= 0 → -2 so static CSV works with dynamic scheduling
    if (par("remapToDynamic")) {
        for (TaskDescriptor* t : taskList) {
            if (t->assignedPE >= 0) {
                t->assignedPE = -2;
                t->pendingDependencies = (int)t->predecessors.size();
                t->state = t->predecessors.empty() ? TASK_READY : TASK_WAITING;
            }
        }
    }

    // Count dynamic tasks
    for (TaskDescriptor* t : taskList) {
        if (t->assignedPE == -2) totalDynamicTasks++;
    }

    // Each GB-injected dynamic task sends an END flit back to GB
    // (PE adds successor=-1 on receipt). Also count static tasks that send to GB.
    resultPacketsExpected = totalDynamicTasks;
    for (TaskDescriptor* t : taskList) {
        if (t->assignedPE >= 0) {
            for (int succId : t->successors) {
                if (succId == -1) { resultPacketsExpected++; break; }
            }
        }
    }

    injectReadyTasks();

    printf("[GB] totalTasks=%d resultPacketsExpected=%d totalDynamic=%d\n",
           (int)taskList.size(), resultPacketsExpected, totalDynamicTasks);

    if (hasExplicit) {
        sendFlitFromAllQs();
        return;
    }

    // Implicit mode (backward compat)
    for (TaskDescriptor* task : taskList) {
        if (!task->predecessors.empty()) continue;
        int dstPE = task->assignedPE;
        int dstRow = dstPE / columns;
        int connIdx = dstRow;
        if (connIdx < 0 || connIdx >= numConnections) continue;
        queueFlit(connIdx, dstPE, task->taskId, task->outputDataSize,
                  task->computeTime.dbl());
    }
    sendFlitFromAllQs();
}

// -----------------------------------------------------------------------
int GlobalBuffer::pickBestIdlePE(TaskDescriptor* task) {
    int columns = (int)getSystemModule()->par("columns");
    int rows    = (int)getSystemModule()->par("rows");
    int numPEs  = rows * columns;
    double Tambient = getSystemModule()->par("Tambient");

    int bestPE = -1;
    double bestCost = 1e99;

    for (int pe = 0; pe < numPEs; pe++) {
        if (peCurrentTask[pe] != -1) continue;

        int hops = pe % columns;
        double Tpe = getThermalModel()->getPEPerature(pe);
        double cost = wTemperature * (Tpe - Tambient) + wHopCount * hops;

        if (cost < bestCost) {
            bestCost = cost;
            bestPE = pe;
        }
    }

    if (bestPE >= 0) {
        EV << "-I- GlobalBuffer assigned task " << task->taskId
           << " to PE[" << bestPE << "]"
           << " T=" << (getThermalModel()->getPEPerature(bestPE) - 273.15) << "C"
           << " cost=" << bestCost << endl;
    }
    return bestPE;
}

// -----------------------------------------------------------------------
void GlobalBuffer::injectTask(TaskDescriptor* task, int dstPE) {
    task->assignedPE = dstPE;
    int cols = (int)getSystemModule()->par("columns");
    int dstRow = dstPE / cols;
    int connIdx = dstRow;

    if (connIdx < 0 || connIdx >= numConnections) return;

    peCurrentTask[dstPE] = task->taskId;

    queueFlit(connIdx, dstPE, task->taskId,
              task->outputDataSize, task->computeTime.dbl());
    sendFlitFromAllQs();

    EV << "-I- GlobalBuffer injected task " << task->taskId
       << " → PE[" << dstPE << "]"
       << " pendingDeps=" << task->pendingDependencies
       << " at " << simTime() << endl;
}

// -----------------------------------------------------------------------
void GlobalBuffer::injectReadyTasks() {
    if (totalDynamicTasks == 0) return;

    for (TaskDescriptor* task : taskList) {
        if (task->assignedPE != -2) continue;
        if (task->pendingDependencies > 0) continue;

        int dstPE = pickBestIdlePE(task);
        if (dstPE < 0) break;

        injectTask(task, dstPE);
    }

}

// -----------------------------------------------------------------------
void GlobalBuffer::handleDataArrival(int connIdx, TaskMsg* msg) {
    totalFlitsReceived++;
    sendCredit(connIdx, msg->getVC(), 1);

    // END flit → one full result packet arrived at GB (static + dynamic unified)
    if (msg->getType() == NOC_END_FLIT && msg->getProducerPE() >= 0) {
        resultPacketsReceived++;
        printf("[GB] END-flit from PE%d → recv=%d/%d at t=%.3fus\n",
               msg->getProducerPE(), resultPacketsReceived,
               resultPacketsExpected, simTime().dbl()*1e6);
        if (resultPacketsExpected > 0 && resultPacketsReceived >= resultPacketsExpected) {
            printf("[GB] ALL RESULTS ARRIVED (%d/%d) endSimulation at t=%.3fus\n",
                   resultPacketsReceived, resultPacketsExpected, simTime().dbl()*1e6);
            recordScalar("allResultsArrivedAt", simTime());
            endSimulation();
        }
        injectReadyTasks();
    }

    // START flit → PE finished computing (for dynamic task tracking)
    if (msg->getType() == NOC_START_FLIT && msg->getProducerPE() >= 0) {
        int completedPE = msg->getProducerPE();

        if (peCurrentTask[completedPE] >= 0) {
            int doneTaskId = peCurrentTask[completedPE];

            EV << "-I- GlobalBuffer task " << doneTaskId
               << " completed on PE[" << completedPE << "]"
               << " at " << simTime() << endl;

            peCurrentTask[completedPE] = -1;

            // Mark task complete and release its successors
            auto it = taskMap.find(doneTaskId);
            if (it != taskMap.end()) {
                TaskDescriptor* doneTask = it->second;
                doneTask->state = TASK_COMPLETED;

                // Decrement pendingDependencies for all successors
                for (int succId : doneTask->successors) {
                    auto succIt = taskMap.find(succId);
                    if (succIt != taskMap.end()) {
                        TaskDescriptor* succ = succIt->second;
                        if (succ->pendingDependencies > 0) {
                            succ->pendingDependencies--;
                            EV << "-I- GlobalBuffer task " << succId
                               << " deps remaining: " << succ->pendingDependencies
                               << endl;
                        }
                    }
                }
            }

            // Try to inject newly-ready tasks
            injectReadyTasks();
        }
    }

    delete msg;
}

// -----------------------------------------------------------------------
void GlobalBuffer::queueFlit(int connIdx, int dstPE, int taskId,
                              int dataSize, double computeTime) {
    int numFlits = calculateNumFlits(dataSize);
    int pktId = makePktId();

    for (int fi = 0; fi < numFlits; fi++) {
        char name[128];
        snprintf(name, sizeof(name), "gbflit-c%d-d%d-t%d-f%d",
                 connIdx, dstPE, taskId, fi);

        TaskMsg* flit = new TaskMsg(name);
        flit->setKind(NOC_FLIT_MSG);
        flit->setByteLength(flitSize);
        flit->setBitLength(8 * flitSize);
        flit->setVC(0);
        flit->setSrcId(baseId + connIdx);
        flit->setDstId(dstPE);
        flit->setPktId(pktId);
        flit->setFlitIdx(fi);
        flit->setFlits(numFlits);
        flit->setFirstNet(true);
        flit->setInjectTime(simTime());
        flit->setSchedulingPriority(0);

        if (fi == 0) flit->setType(NOC_START_FLIT);
        else if (fi == numFlits - 1) flit->setType(NOC_END_FLIT);
        else flit->setType(NOC_MID_FLIT);

        flit->setTaskId(taskId);
        flit->setProducerPE(-1);
        flit->setConsumerPE(dstPE);
        flit->setProducerTaskId(-1);
        flit->setDataSize(dataSize);
        flit->setComputeTime(computeTime);

        injectQ[connIdx].push(flit);
    }
}

void GlobalBuffer::sendFlitFromAllQs() {
    for (int i = 0; i < numConnections; i++) sendFlitFromQ(i);
}

void GlobalBuffer::sendFlitFromQ(int connIdx) {
    if (connIdx < 0 || connIdx >= numConnections) return;
    if (injectQ[connIdx].empty()) return;
    if (credits[connIdx] <= 0) return;

    cGate* g = gateHalf("out", cGate::OUTPUT, connIdx);
    if (!g) return;

    cChannel* ch = g->getTransmissionChannel();
    if (ch && ch->isBusy()) return;

    TaskMsg* flit = injectQ[connIdx].front();
    injectQ[connIdx].pop();

    send(flit, "out$o", connIdx);
    credits[connIdx]--;
    totalFlitsSent++;
}

void GlobalBuffer::sendCredit(int connIdx, int vc, int numFlits) {
    if (connIdx < 0 || connIdx >= numConnections) return;
    cGate* g = gateHalf("in", cGate::OUTPUT, connIdx);
    if (!g || !g->isConnected()) return;

    char credName[64];
    sprintf(credName, "gbcred-c%d-vc%d-f%d", connIdx, vc, numFlits);
    NoCCreditMsg *crd = new NoCCreditMsg(credName);
    crd->setKind(NOC_CREDIT_MSG);
    crd->setVC(vc);
    crd->setFlits(numFlits);
    crd->setSchedulingPriority(0);
    send(crd, "in$o", connIdx);
}

int GlobalBuffer::calculateNumFlits(int dataSize) const {
    int n = 1;
    if (dataSize > 0 && flitSize > 0) n = (dataSize + flitSize - 1) / flitSize;
    return (n < 2) ? 2 : n;
}

int GlobalBuffer::makePktId() {
    return (baseId << 12) | (++pktIdCounter & 0xFFF);
}
