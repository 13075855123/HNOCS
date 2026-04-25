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
// TaskPE – Task-driven Processing Element
//

#include "TaskPE.h"

Define_Module(TaskPE);

// -----------------------------------------------------------------------
// initialize
// -----------------------------------------------------------------------
void TaskPE::initialize() {
    peId            = par("id");
    numVCs          = par("numVCs");
    flitSize        = par("flitSize");
    statStartTime   = par("statStartTime");
    applicationName = par("application").stringValue();

    powerIdle        = par("powerIdle");
    powerCompute     = par("powerCompute");
    powerSendPerFlit = par("powerSendPerFlit");
    powerRecvPerFlit = par("powerRecvPerFlit");
    enablePowerTrace = par("enablePowerTrace");

    currentTask   = nullptr;
    currentPower  = powerIdle;
    peakPower     = powerIdle;
    avgPower      = 0.0;
    isIdle        = true;
    lastEventTime = simTime();
    pktIdCounter  = peId << 16;

    totalTasksCompleted = 0;
    totalFlitsSent      = 0;
    totalFlitsReceived  = 0;
    totalComputeTime    = 0;
    totalIdleTime       = 0;

    credits = 0;

    powerVec.setName("power");

    // Derive clock period from outgoing link
    cGate* g = gate("out$o")->getNextGate();
    if (g && g->getChannel()) {
        cDatarateChannel* chan =
            check_and_cast<cDatarateChannel*>(g->getChannel());
        double dr = chan->getDatarate();
        tClk_s = (8.0 * flitSize) / dr;
    } else {
        tClk_s = 2e-9; // fallback: 2 ns
    }

    // Power trace
    powerTrace = new PowerTraceWriter();
    if (enablePowerTrace && peId == 0) {
        const char* traceFile   = par("powerTraceFile").stringValue();
        const char* hotspotFile = par("hotspotTraceFile").stringValue();
        powerTrace->open(traceFile, hotspotFile);
        double sampleInterval = par("powerSampleInterval");
        powerTrace->setSamplingInterval(sampleInterval);
    }

    // Self-messages
    computeCompleteMsg = new cMessage("computeComplete");
    powerSampleMsg     = new cMessage("powerSample");
    injectPopMsg       = new cMessage("injectPop");

    // Load task graph
    loadTaskGraph();

    // Periodic power sampling
    double sampleInterval = par("powerSampleInterval");
    scheduleAt(simTime() + sampleInterval, powerSampleMsg);

    // Injection pop clock (similar to synchronous source pacing)
    scheduleAt(simTime() + tClk_s, injectPopMsg);

    EV << "=== TASKPE_DEBUG_BUILD_ACTIVE pe=" << peId
       << " app=" << applicationName << " ===" << endl;

    EV << "-I- TaskPE[" << peId << "] init application=" << applicationName
       << " numVCs=" << numVCs
       << " flitSize=" << flitSize
       << "B tClk=" << tClk_s
       << " initialCredits=" << credits << endl;

    // Try first task immediately
    scheduleNextTask();
}

// -----------------------------------------------------------------------
// handleMessage
// -----------------------------------------------------------------------
void TaskPE::handleMessage(cMessage* msg) {
    if (msg == computeCompleteMsg) {
        completeComputation();
        return;
    }

    if (msg == powerSampleMsg) {
        samplePower();
        double sampleInterval = par("powerSampleInterval");
        scheduleAt(simTime() + sampleInterval, powerSampleMsg);
        return;
    }

    if (msg == injectPopMsg) {
        sendFlitFromQ();
        scheduleAt(simTime() + tClk_s, injectPopMsg);
        return;
    }

    if (msg->getKind() == NOC_CREDIT_MSG) {
        NoCCreditMsg* crd = check_and_cast<NoCCreditMsg*>(msg);
        int recvVc = crd->getVC();
        int recvFlits = crd->getFlits();

        EV << "-I- TaskPE[" << peId << "] CREDIT"
           << " vc=" << recvVc
           << " flits=" << recvFlits
           << " creditsBefore=" << credits
           << " at " << simTime() << endl;

        if (recvVc == 0) {
            credits += recvFlits;
        }

        EV << "-I- TaskPE[" << peId << "] CREDIT-UPDATED"
           << " vc=" << recvVc
           << " creditsAfter=" << credits
           << " injectQ=" << injectQ.size()
           << " at " << simTime() << endl;

        delete crd;
        sendFlitFromQ();
        return;
    }

    if (msg->getKind() == NOC_FLIT_MSG) {
        TaskMsg* taskMsg = dynamic_cast<TaskMsg*>(msg);
        if (taskMsg) {
            handleDataArrival(taskMsg);
        } else {
            delete msg;
        }
        return;
    }

    delete msg;
}

// -----------------------------------------------------------------------
// finish
// -----------------------------------------------------------------------
void TaskPE::finish() {
    simtime_t now = simTime();
    if (isIdle) {
        totalIdleTime += now - lastEventTime;
    } else {
        totalComputeTime += now - lastEventTime;
    }

    double simDuration = now.dbl();
    if (simDuration > 0) {
        avgPower = (totalComputeTime.dbl() * powerCompute +
                    totalIdleTime.dbl()    * powerIdle) / simDuration;
    }

    recordScalar("totalTasksCompleted", totalTasksCompleted);
    recordScalar("totalFlitsSent",      totalFlitsSent);
    recordScalar("totalFlitsReceived",  totalFlitsReceived);
    recordScalar("avgPower",            avgPower);
    recordScalar("peakPower",           peakPower);
    recordScalar("utilization",         getUtilization());

    if (powerTrace) {
        powerTrace->close();
        delete powerTrace;
        powerTrace = nullptr;
    }
}

// -----------------------------------------------------------------------
// Destructor
// -----------------------------------------------------------------------
TaskPE::~TaskPE() {
    cancelAndDelete(computeCompleteMsg);
    cancelAndDelete(powerSampleMsg);
    cancelAndDelete(injectPopMsg);

    for (TaskDescriptor* t : taskList) {
        delete t;
    }

    while (!injectQ.empty()) {
        delete injectQ.front();
        injectQ.pop();
    }

    if (powerTrace) {
        delete powerTrace;
        powerTrace = nullptr;
    }
}

// -----------------------------------------------------------------------
// getUtilization
// -----------------------------------------------------------------------
double TaskPE::getUtilization() const {
    double total = simTime().dbl();
    if (total <= 0) return 0.0;
    return totalComputeTime.dbl() / total;
}

// -----------------------------------------------------------------------
// loadTaskGraph – dispatcher
// -----------------------------------------------------------------------
void TaskPE::loadTaskGraph() {
    if (applicationName == "matrix_multiply") {
        loadMatrixMultiplyTasks();
    } else if (applicationName == "cnn_inference") {
        loadCNNInferenceTasks();
    } else if (applicationName == "graph_traversal") {
        loadGraphTraversalTasks();
    } else {
        throw cRuntimeError("Unknown application: %s", applicationName.c_str());
    }
}

// -----------------------------------------------------------------------
// 应用 1：矩阵乘法
// -----------------------------------------------------------------------
void TaskPE::loadMatrixMultiplyTasks() {
    const int blockSize   = 64;
    const simtime_t compT = 100e-9;

    TaskDescriptor* task = new TaskDescriptor(peId, peId, compT, blockSize);
    task->pendingDependencies = 0;
    task->state = TASK_READY;

    taskList.push_back(task);
    taskMap[peId] = task;
    readyQueue.push(task);

    EV << "-I- TaskPE[" << peId << "] loaded matrix_multiply task" << endl;
}

// -----------------------------------------------------------------------
// Application 2: CNN Inference
// -----------------------------------------------------------------------
void TaskPE::loadCNNInferenceTasks() {
    if (peId == 0) {
        TaskDescriptor* t = new TaskDescriptor(0, 0, 100e-9, 128);
        t->successors  = {1, 2, 3, 4};
        t->successorPE = {{1,1},{2,2},{3,3},{4,4}};
        t->pendingDependencies = 0;
        t->state = TASK_READY;
        taskList.push_back(t);
        taskMap[0] = t;
        readyQueue.push(t);
    } else if (peId >= 1 && peId <= 4) {
        TaskDescriptor* t = new TaskDescriptor(peId, peId, 200e-9, 64);
        t->predecessors = {0};
        t->successors   = {5};
        t->successorPE  = {{5, 5}};
        t->pendingDependencies = 1;
        t->state = TASK_WAITING;
        taskList.push_back(t);
        taskMap[peId] = t;
    } else if (peId == 5) {
        TaskDescriptor* t = new TaskDescriptor(5, 5, 150e-9, 0);
        t->predecessors = {1, 2, 3, 4};
        t->pendingDependencies = 4;
        t->state = TASK_WAITING;
        taskList.push_back(t);
        taskMap[5] = t;
    }

    EV << "-I- TaskPE[" << peId << "] loaded cnn_inference task(s)" << endl;
}

// -----------------------------------------------------------------------
// Application 3: Graph Traversal
// -----------------------------------------------------------------------
void TaskPE::loadGraphTraversalTasks() {
    struct TInfo {
        int id;
        int pe;
        double compNs;
        int dataB;
        std::vector<int> preds;
        std::vector<int> succs;
        std::map<int,int> succPE;
    };

    std::vector<TInfo> table = {
        {  0,  0,  50e-9, 64, {},    {1,2},   {{1,1},{2,2}} },
        {  1,  1,  50e-9, 64, {0},   {3,4},   {{3,3},{4,4}} },
        {  2,  2,  50e-9, 64, {0},   {5,6},   {{5,5},{6,6}} },
        {  3,  3,  50e-9, 32, {1},   {7},     {{7,7}} },
        {  4,  4,  50e-9, 32, {1},   {8},     {{8,8}} },
        {  5,  5,  50e-9, 32, {2},   {9},     {{9,9}} },
        {  6,  6,  50e-9, 32, {2},   {10},    {{10,10}} },
        {  7,  7,  50e-9,  0, {3},   {},      {} },
        {  8,  8,  50e-9,  0, {4},   {},      {} },
        {  9,  9,  50e-9,  0, {5},   {},      {} },
        { 10, 10,  50e-9,  0, {6},   {},      {} },
    };

    for (auto& info : table) {
        if (info.pe != peId) continue;

        TaskDescriptor* t = new TaskDescriptor(info.id, info.pe,
                                               info.compNs, info.dataB);
        t->predecessors        = info.preds;
        t->successors          = info.succs;
        t->successorPE         = info.succPE;
        t->pendingDependencies = (int)info.preds.size();
        t->state               = info.preds.empty() ? TASK_READY : TASK_WAITING;

        taskList.push_back(t);
        taskMap[info.id] = t;
        if (t->state == TASK_READY)
            readyQueue.push(t);
    }

    EV << "-I- TaskPE[" << peId << "] loaded graph_traversal task(s)" << endl;
}

// -----------------------------------------------------------------------
// scheduleNextTask
// -----------------------------------------------------------------------
void TaskPE::scheduleNextTask() {
    if (currentTask != nullptr) return;
    if (readyQueue.empty()) return;

    TaskDescriptor* task = readyQueue.front();
    readyQueue.pop();
    startComputation(task);
}

// -----------------------------------------------------------------------
// startComputation
// -----------------------------------------------------------------------
void TaskPE::startComputation(TaskDescriptor* task) {
    task->state     = TASK_COMPUTING;
    task->startTime = simTime();
    currentTask     = task;

    simtime_t now = simTime();
    if (isIdle) {
        totalIdleTime += now - lastEventTime;
    }
    lastEventTime = now;
    isIdle        = false;
    updatePower(powerCompute);

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_COMPUTE_START, now, powerCompute);
    }

    EV << "-I- TaskPE[" << peId << "] starts task " << task->taskId
       << " at " << simTime()
       << " computeTime=" << task->computeTime
       << " outputDataSize=" << task->outputDataSize
       << "B pendingDeps=" << task->pendingDependencies << endl;

    scheduleAt(simTime() + task->computeTime, computeCompleteMsg);
}

// -----------------------------------------------------------------------
// completeComputation
// -----------------------------------------------------------------------
void TaskPE::completeComputation() {
    if (!currentTask) return;

    TaskDescriptor* task = currentTask;
    task->state      = TASK_COMPLETED;
    task->finishTime = simTime();
    currentTask      = nullptr;
    totalTasksCompleted++;

    simtime_t now = simTime();
    totalComputeTime += now - lastEventTime;
    lastEventTime    = now;
    isIdle           = true;
    updatePower(powerIdle);

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_COMPUTE_END, now, powerIdle);
    }

    EV << "-I- TaskPE[" << peId << "] completed task " << task->taskId
       << " at " << simTime()
       << " outputDataSize=" << task->outputDataSize
       << "B successors=" << task->successors.size() << endl;

    if (task->outputDataSize > 0) {
        sendTaskData(task);
    }

    scheduleNextTask();
}

// -----------------------------------------------------------------------
// sendTaskData – create flits and queue them for injection
// -----------------------------------------------------------------------
void TaskPE::sendTaskData(TaskDescriptor* task) {
    int numFlits = calculateNumFlits(task->outputDataSize);

    for (int succTaskId : task->successors) {
        auto it = task->successorPE.find(succTaskId);
        if (it == task->successorPE.end()) continue;

        int dstPE = it->second;
        if (dstPE == peId) continue;

        pktIdCounter++;
        int pktId = pktIdCounter;

        for (int fi = 0; fi < numFlits; fi++) {
            char name[128];
            snprintf(name, sizeof(name),
                     "taskflit-s%d-t%d-task%d->%d-f%d",
                     peId, dstPE, task->taskId, succTaskId, fi);

            TaskMsg* flit = new TaskMsg(name);
            flit->setKind(NOC_FLIT_MSG);
            flit->setByteLength(flitSize);
            flit->setBitLength(8 * flitSize);
            flit->setVC(0);
            flit->setSrcId(peId);
            flit->setDstId(dstPE);
            flit->setPktId(pktId);
            flit->setFlitIdx(fi);
            flit->setFlits(numFlits);
            flit->setFirstNet(true);
            flit->setInjectTime(simTime());
            flit->setSchedulingPriority(0);

            // Single-flit packet: treat as END so receiver/scheduler can close it.
            if (fi == 0) {
                flit->setType(NOC_START_FLIT);
            } else if (fi == numFlits - 1) {
                flit->setType(NOC_END_FLIT);
            } else {
                flit->setType(NOC_MID_FLIT);
            }

            flit->setTaskId(succTaskId);
            flit->setProducerPE(peId);
            flit->setConsumerPE(dstPE);
            flit->setProducerTaskId(task->taskId);
            flit->setDataSize(task->outputDataSize);
            flit->setComputeTime(task->computeTime);

            injectQ.push(flit);
        }

        EV << "-I- TaskPE[" << peId << "] queued packet pktId=" << pktId
           << " for successorTask=" << succTaskId
           << " dstPE=" << dstPE
           << " numFlits=" << numFlits
           << " dataSize=" << task->outputDataSize
           << "B at " << simTime() << endl;
    }

    EV << "-I- TaskPE[" << peId << "] injectQ size after enqueue=" << injectQ.size()
       << " at " << simTime() << endl;

    sendFlitFromQ();
}

// -----------------------------------------------------------------------
// sendFlitFromQ – PktFifoSrc-like injection
// -----------------------------------------------------------------------
void TaskPE::sendFlitFromQ() {
    if (injectQ.empty()) {
        return;
    }

    if (credits <= 0) {
        EV << "-I- TaskPE[" << peId << "] cannot send: no credits"
           << " at " << simTime()
           << " injectQ=" << injectQ.size() << endl;
        return;
    }

    cChannel* ch = gate("out$o")->getTransmissionChannel();
    if (ch && ch->isBusy()) {
        EV << "-I- TaskPE[" << peId << "] cannot send: channel busy"
           << " at " << simTime()
           << " injectQ=" << injectQ.size()
           << " credits=" << credits << endl;
        return;
    }

    TaskMsg* flit = injectQ.front();
    injectQ.pop();

    int pktId = flit->getPktId();
    int flitIdx = flit->getFlitIdx();

    EV << "-I- TaskPE[" << peId << "] SEND"
       << " pktId=" << pktId
       << " flitIdx=" << flitIdx
       << "/" << (flit->getFlits() - 1)
       << " type=" << flit->getType()
       << " srcPE=" << flit->getSrcId()
       << " dstPE=" << flit->getDstId()
       << " producerTask=" << flit->getProducerTaskId()
       << " consumerTask=" << flit->getTaskId()
       << " vc=" << flit->getVC()
       << " creditsBefore=" << credits
       << " injectQAfterPop=" << injectQ.size()
       << " at " << simTime() << endl;

    send(flit, "out$o");
    credits--;
    totalFlitsSent++;

    EV << "-I- TaskPE[" << peId << "] SEND-DONE"
       << " pktId=" << pktId
       << " flitIdx=" << flitIdx
       << " creditsAfter=" << credits
       << " totalFlitsSent=" << totalFlitsSent
       << " at " << simTime() << endl;

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_SEND_FLIT, simTime(),
                                  powerIdle + powerSendPerFlit / tClk_s);
    }
}

// -----------------------------------------------------------------------
// handleDataArrival
// -----------------------------------------------------------------------
void TaskPE::handleDataArrival(TaskMsg* msg) {
    totalFlitsReceived++;

    EV << "-I- TaskPE[" << peId << "] RECV"
       << " pktId=" << msg->getPktId()
       << " flitIdx=" << msg->getFlitIdx()
       << "/" << (msg->getFlits() - 1)
       << " type=" << msg->getType()
       << " srcPE=" << msg->getSrcId()
       << " dstPE=" << msg->getDstId()
       << " producerTask=" << msg->getProducerTaskId()
       << " consumerTask=" << msg->getTaskId()
       << " vc=" << msg->getVC()
       << " at " << simTime() << endl;

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_RECV_FLIT, simTime(),
                                  powerIdle + powerRecvPerFlit / tClk_s);
    }

    // Only act on last flit of a multi-flit packet
    if (msg->getType() != NOC_END_FLIT && msg->getFlits() > 1) {
        delete msg;
        return;
    }

    int targetTaskId = msg->getTaskId();
    delete msg;

    auto it = taskMap.find(targetTaskId);
    if (it == taskMap.end()) {
        EV << "-W- TaskPE[" << peId << "] received data for unknown task "
           << targetTaskId << endl;
        return;
    }

    TaskDescriptor* task = it->second;
    if (task->state == TASK_COMPLETED || task->state == TASK_COMPUTING) {
        return;
    }

    receivedDependencies[targetTaskId]++;
    task->pendingDependencies--;

    EV << "-I- TaskPE[" << peId << "] dependency update"
       << " targetTask=" << targetTaskId
       << " pendingDeps=" << task->pendingDependencies
       << " receivedCount=" << receivedDependencies[targetTaskId]
       << " at " << simTime() << endl;

    if (task->pendingDependencies <= 0) {
        task->state = TASK_READY;
        readyQueue.push(task);

        EV << "-I- TaskPE[" << peId << "] task " << targetTaskId
           << " is READY at " << simTime()
           << " readyQueueSize=" << readyQueue.size() << endl;

        scheduleNextTask();
    }
}

// -----------------------------------------------------------------------
// calculateNumFlits
// -----------------------------------------------------------------------
int TaskPE::calculateNumFlits(int dataSize) const {
    if (dataSize <= 0 || flitSize <= 0) return 1;
    return (dataSize + flitSize - 1) / flitSize;
}

// -----------------------------------------------------------------------
// updatePower
// -----------------------------------------------------------------------
void TaskPE::updatePower(double newPower) {
    currentPower = newPower;
    if (currentPower > peakPower)
        peakPower = currentPower;
    powerVec.record(currentPower);
}

// -----------------------------------------------------------------------
// samplePower
// -----------------------------------------------------------------------
void TaskPE::samplePower() {
    powerVec.record(currentPower);
    if (powerTrace) {
        powerTrace->recordPEEvent(peId, isIdle ? PE_IDLE : PE_COMPUTE_START,
                                  simTime(), currentPower);
    }
}
