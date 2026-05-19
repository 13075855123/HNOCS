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
#include "thermal/ThermalTrace.h"   // NEW
#include "utils/TaskGraphParser.h"

Define_Module(TaskPE);

int TaskPE::systemTotalTasks = 0;
int TaskPE::systemCompletedTasks = 0;
bool TaskPE::systemStopScheduled = false;

// NEW
void TaskPE::sendCredit(int vc, int numFlits) {
    if (gate("in$o")->getPathEndGate()->getType() != cGate::INPUT) {
        return;
    }

    char credName[64];
    sprintf(credName, "cred-%d-%d", vc, numFlits);
    NoCCreditMsg *crd = new NoCCreditMsg(credName);
    crd->setKind(NOC_CREDIT_MSG);
    crd->setVC(vc);
    crd->setFlits(numFlits);
    crd->setSchedulingPriority(0);

    EV << "-I- TaskPE[" << peId << "] SEND-CREDIT"
       << " vc=" << vc
       << " flits=" << numFlits
       << " at " << simTime() << endl;

    send(crd, "in$o");
}

// NEW
void TaskPE::accumulatePEStaticEnergy(simtime_t now) {
    if (now <= lastEnergyUpdateTime) return;

    simtime_t dt = now - lastEnergyUpdateTime;
    windowStaticEnergyJ += currentPower * dt.dbl();
    lastEnergyUpdateTime = now;
}

// NEW
void TaskPE::finalizeEnergyWindow(simtime_t now) {
    // Refresh currentPower with latest temperature before accumulating
    if (isIdle)
        currentPower = getTemperatureCorrectedPower(true);
    else
        currentPower = getTemperatureCorrectedPower(false);

    accumulatePEStaticEnergy(now);

    // Dynamic energy from flit events
    windowDynamicEnergyJ =
        windowSendFlits * powerSendPerFlit +
        windowRecvFlits * powerRecvPerFlit;

    // Total window energy = static + dynamic
    windowEnergyJ = windowStaticEnergyJ + windowDynamicEnergyJ;

    totalStaticEnergyJ  += windowStaticEnergyJ;
    totalDynamicEnergyJ += windowDynamicEnergyJ;
    totalEnergyJ        += windowEnergyJ;

    // Record combined + separated energy vectors
    windowEnergyVec.record(windowEnergyJ);
    windowStaticEnergyVec.record(windowStaticEnergyJ);
    windowDynamicEnergyVec.record(windowDynamicEnergyJ);
    cumulativeEnergyVec.record(totalEnergyJ);
    cumulativeStaticEnergyVec.record(totalStaticEnergyJ);
    cumulativeDynamicEnergyVec.record(totalDynamicEnergyJ);

    double windowAvgPower = 0.0;
    if (energyWindow.dbl() > 0) {
        windowAvgPower = windowEnergyJ / energyWindow.dbl();
        windowAvgPowerVec.record(windowAvgPower);
    } else {
        windowAvgPowerVec.record(0.0);
    }

    // Submit PE average power to unified HotSpot trace
    getThermalModel()->submitPEPower(peId, now, windowAvgPower);

    EV << "-I- TaskPE[" << peId << "] ENERGY-WINDOW"
       << " at " << now
       << " windowEnergyJ=" << windowEnergyJ
       << " staticJ=" << windowStaticEnergyJ
       << " dynamicJ=" << windowDynamicEnergyJ
       << " totalEnergyJ=" << totalEnergyJ
       << " totalStaticJ=" << totalStaticEnergyJ
       << " totalDynamicJ=" << totalDynamicEnergyJ
       << " windowSendFlits=" << windowSendFlits
       << " windowRecvFlits=" << windowRecvFlits
       << " currentPower=" << currentPower
       << " isIdle=" << isIdle << endl;

    windowSendFlits = 0;
    windowRecvFlits = 0;
    windowStaticEnergyJ  = 0.0;
    windowDynamicEnergyJ = 0.0;
    windowEnergyJ = 0.0;

    updateThermalDisplay();
}

void TaskPE::updateThermalDisplay() {
    double t = getThermalModel()->getPEPerature(peId);
    peTempVec.record(t);

    char tmp[32];
    snprintf(tmp, sizeof(tmp), "%.1fC", t - 273.15);
    getDisplayString().setTagArg("t", 0, tmp);
}

// -----------------------------------------------------------------------
// initialize
// -----------------------------------------------------------------------
void TaskPE::initialize() {
    peId            = par("id");
    numVCs          = par("numVCs");
    flitSize        = par("flitSize");
    statStartTime   = par("statStartTime");
    bufferBaseId    = par("bufferBaseId");
    numColumns      = getSystemModule()->par("columns");

    powerIdle        = par("powerIdle");
    powerCompute     = par("powerCompute");
    powerSendPerFlit = par("powerSendPerFlit");
    powerRecvPerFlit = par("powerRecvPerFlit");
    enablePowerTrace = par("enablePowerTrace");
    computeDensity   = par("computeDensity");

    // NEW
    energyWindow = par("energyWindow");

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
    totalComputeTime     = 0;
    totalIdleTime        = 0;
    totalThrottlePenalty  = 0;
    totalComputeTimeNominal = 0;

    // NEW
    lastEnergyUpdateTime = simTime();
    windowSendFlits = 0;
    windowRecvFlits = 0;
    windowEnergyJ   = 0.0;
    totalEnergyJ    = 0.0;

    windowStaticEnergyJ  = 0.0;
    windowDynamicEnergyJ = 0.0;
    totalStaticEnergyJ   = 0.0;
    totalDynamicEnergyJ  = 0.0;

    credits = 0;

    powerVec.setName("power");

    // NEW
    windowEnergyVec.setName("pe-window-energy");
    cumulativeEnergyVec.setName("pe-cumulative-energy");
    windowAvgPowerVec.setName("pe-window-avg-power");
    windowStaticEnergyVec.setName("pe-window-static-energy");
    windowDynamicEnergyVec.setName("pe-window-dynamic-energy");
    cumulativeStaticEnergyVec.setName("pe-cumulative-static-energy");
    cumulativeDynamicEnergyVec.setName("pe-cumulative-dynamic-energy");

    peTempVec.setName("pe-die-temperature");

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

    // NEW: open unified thermal trace once
    if (peId == 0) {
        int rows = getSystemModule()->par("rows");
        int columns = getSystemModule()->par("columns");
        const char* hotspotFile = par("hotspotTraceFile").stringValue();
        getThermalModel()->open(hotspotFile, rows, columns);

        // Configure RC thermal parameters from ini
        cModule* net = getSystemModule();
        double RconvPE     = net->par("RconvPE");
        double RconvRouter = net->par("RconvRouter");
        double RlateralPE  = net->par("RlateralPE");
        double RlateralRtr = net->par("RlateralRouter");
        double Rpe2router  = net->par("Rpe2router");
        double Cpe         = net->par("Cpe");
        double Crouter     = net->par("Crouter");
        double Tambient    = net->par("Tambient");
        getThermalModel()->setThermalParams(
            RconvPE, RconvRouter, RlateralPE, RlateralRtr,
            Rpe2router, Cpe, Crouter, Tambient);
    }

    // Self-messages
    computeCompleteMsg = new cMessage("computeComplete");
    powerSampleMsg     = new cMessage("powerSample");
    injectPopMsg       = new cMessage("injectPop");

    // NEW
    energyWindowMsg    = new cMessage("energyWindow");

    // Always load task graph from CSV for full successor/predecessor info
    {
        const char* csvPath = par("csvFile").stringValue();
        if (csvPath && csvPath[0] != '\0') {
            loadTaskGraphFromCSV(csvPath);
            systemTotalTasks += taskList.size();
        } else {
            throw cRuntimeError("TaskPE[%d]: csvFile parameter is required", peId);
        }
    }

    // Periodic power sampling
    double sampleInterval = par("powerSampleInterval");
    scheduleAt(simTime() + sampleInterval, powerSampleMsg);

    // NEW
    if (par("enableEnergyWindow")) {
        scheduleAt(simTime() + energyWindow, energyWindowMsg);
    }

    // Injection pop clock (similar to synchronous source pacing)
    scheduleAt(simTime() + tClk_s, injectPopMsg);

    // NEW: initial receive-side credits for router -> TaskPE direction
    int initialRecvCredits = 4;
    for (int vc = 0; vc < numVCs; vc++) {
        sendCredit(vc, initialRecvCredits);
    }

    EV << "-I- TaskPE[" << peId << "] init"
       << " numVCs=" << numVCs
       << " flitSize=" << flitSize
       << "B tClk=" << tClk_s
       << " initialCredits=" << credits
       << " energyWindow=" << energyWindow
       << endl;

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

    // NEW
    if (msg == energyWindowMsg) {
        finalizeEnergyWindow(simTime());
        scheduleAt(simTime() + energyWindow, energyWindowMsg);
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

    // NEW
    finalizeEnergyWindow(now);

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

    // NEW
    recordScalar("totalEnergyJ",        totalEnergyJ);
    recordScalar("totalStaticEnergyJ",  totalStaticEnergyJ);
    recordScalar("totalDynamicEnergyJ", totalDynamicEnergyJ);

    // DVFS throttling statistics
    recordScalar("totalComputeTimeNominal", totalComputeTimeNominal);
    recordScalar("totalThrottlePenalty",    totalThrottlePenalty);
    double penaltyRatio = 0.0;
    if (totalComputeTimeNominal.dbl() > 0.0)
        penaltyRatio = totalThrottlePenalty.dbl() / totalComputeTimeNominal.dbl();
    recordScalar("throttlePenaltyRatio",    penaltyRatio);

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

    // NEW
    cancelAndDelete(energyWindowMsg);

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
// loadTaskGraphFromCSV – load tasks assigned to this PE
// -----------------------------------------------------------------------
void TaskPE::loadTaskGraphFromCSV(const std::string& csvPath) {
    std::vector<TaskDescriptor*> allTasks = TaskGraphParser::parse(csvPath.c_str());

    int loaded = 0;
    for (TaskDescriptor* t : allTasks) {
        // Skip GB injection tasks (peId == -1) and dynamic tasks (peId == -2)
        if (t->assignedPE == -1 || t->assignedPE == -2) {
            delete t;
            continue;
        }
        // remapToDynamic mode: GB handles all peId >= 0 tasks
        if (par("remapToDynamic")) {
            delete t;
            continue;
        }
        if (t->assignedPE != peId) {
            delete t;
            continue;
        }

        // Count same-PE predecessors (dependencies resolved locally via sendTaskData)
        int localPreds = 0;
        for (int predId : t->predecessors) {
            for (TaskDescriptor* other : allTasks) {
                if (other->taskId == predId && other->assignedPE == peId) {
                    localPreds++;
                    break;
                }
            }
        }
        t->pendingDependencies -= localPreds;

        if (t->pendingDependencies == 0) {
            t->state = TASK_READY;
            readyQueue.push(t);
        } else {
            t->state = TASK_WAITING;
        }

        taskList.push_back(t);
        taskMap[t->taskId] = t;
        loaded++;
    }

    EV << "-I- TaskPE[" << peId << "] loaded " << loaded
       << " tasks from " << csvPath << endl;
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

    // NEW
    accumulatePEStaticEnergy(now);

    if (isIdle) {
        totalIdleTime += now - lastEventTime;
    }
    lastEventTime = now;
    isIdle        = false;
    updatePower(false);

    // Nominal compute time: derive from data size if computeDensity > 0
    simtime_t nominalTime;
    if (computeDensity > 0.0 && task->outputDataSize > 0) {
        nominalTime = task->outputDataSize * computeDensity * 1e-9;
    } else {
        nominalTime = task->computeTime;
    }

    // DVFS thermal throttling: scale compute time by temperature
    double dvfsScale = getDvfsScaleFactor();
    simtime_t actualTime  = nominalTime * dvfsScale;
    totalComputeTimeNominal += nominalTime;
    totalThrottlePenalty    += (actualTime - nominalTime);

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_COMPUTE_START, now, powerCompute);
    }

    EV << "-I- TaskPE[" << peId << "] starts task " << task->taskId
       << " at " << simTime()
       << " nominalTime=" << nominalTime
       << " dvfsScale=" << dvfsScale
       << " actualTime=" << actualTime
       << " Tpe=" << getThermalModel()->getPEPerature(peId)
       << " outputDataSize=" << task->outputDataSize
       << "B pendingDeps=" << task->pendingDependencies << endl;

    scheduleAt(simTime() + actualTime, computeCompleteMsg);
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

    // NEW
    accumulatePEStaticEnergy(now);

    totalComputeTime += now - lastEventTime;
    lastEventTime    = now;
    isIdle           = true;
    updatePower(true);

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_COMPUTE_END, now, powerIdle);
    }

    printf("[PE%d] task=%d DONE computeTime=%.3fus output=%dB successors=%d at t=%.3fus\n",
           peId, task->taskId, task->computeTime.dbl()*1e6,
           task->outputDataSize, (int)task->successors.size(), now.dbl()*1e6);

    if (task->outputDataSize > 0 || !task->successors.empty()) {
        int nf = calculateNumFlits(task->outputDataSize);
        printf("[PE%d] task=%d SENDING %d flits\n", peId, task->taskId, nf);
        sendTaskData(task);
    }

    systemCompletedTasks++;
    if (systemTotalTasks > 0 && systemCompletedTasks >= systemTotalTasks
        && !systemStopScheduled) {
        systemStopScheduled = true;
        recordScalar("allTasksCompletedAt", simTime());
        // Self-contained task (no successors): stop now.
        // Task returning to GB: GB's END flit counting handles endSimulation.
        if (task->successors.empty()) {
            endSimulation();
        }
    }

    scheduleNextTask();
}

// -----------------------------------------------------------------------
// sendTaskData – create flits and queue them for injection
// -----------------------------------------------------------------------
void TaskPE::sendTaskData(TaskDescriptor* task) {
    int numFlits = calculateNumFlits(task->outputDataSize);

    for (int succTaskId : task->successors) {
        int dstPE;

        // succTaskId == -1: send to GlobalBuffer instead of a PE
        if (succTaskId == -1) {
            int row = peId / numColumns;
            dstPE = bufferBaseId + row;   // route to GB on this row
        } else {
            auto it = task->successorPE.find(succTaskId);
            if (it == task->successorPE.end()) continue;
            dstPE = it->second;
        }

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
            flit->setComputeTime(task->computeTime.dbl());

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

    // NEW
    windowSendFlits++;

    EV << "-I- TaskPE[" << peId << "] SEND-DONE"
       << " pktId=" << pktId
       << " flitIdx=" << flitIdx
       << " creditsAfter=" << credits
       << " totalFlitsSent=" << totalFlitsSent
       << " windowSendFlits=" << windowSendFlits
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

    // Return one receive-side credit to router
    sendCredit(msg->getVC(), 1);

    windowRecvFlits++;

    int pktId = msg->getPktId();
    int flitIdx = msg->getFlitIdx();
    int totalFlits = msg->getFlits();
    int flitType = msg->getType();

    EV << "-I- TaskPE[" << peId << "] RECV"
       << " pktId=" << pktId
       << " flitIdx=" << flitIdx << "/" << (totalFlits - 1)
       << " type=" << flitType
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

    // Accumulate flit in receive buffer — all flits represent real data
    recvBuffer[pktId].push_back(msg);

    // Wait until the entire packet arrives
    if (flitType != NOC_END_FLIT && totalFlits > 1) {
        EV << "-I- TaskPE[" << peId << "] buffered flit " << flitIdx
           << "/" << (totalFlits - 1)
           << " pktId=" << pktId
           << " bufferSize=" << recvBuffer[pktId].size()
           << endl;
        return;
    }

    // END flit: packet complete, assemble data from buffered flits
    int targetTaskId = msg->getTaskId();
    int producerPE = msg->getProducerPE();
    simtime_t compTime = msg->getComputeTime();
    int dataSize = msg->getDataSize();

    EV << "-I- TaskPE[" << peId << "] PACKET-COMPLETE"
       << " pktId=" << pktId
       << " totalFlits=" << recvBuffer[pktId].size()
       << " targetTask=" << targetTaskId
       << " producerPE=" << producerPE
       << " at " << simTime() << endl;

    // Free all buffered flits for this packet
    for (TaskMsg* f : recvBuffer[pktId]) {
        delete f;
    }
    recvBuffer.erase(pktId);

    auto it = taskMap.find(targetTaskId);
    if (it == taskMap.end()) {
        // If from GlobalBuffer (producerPE == -1), the task must already
        // exist from CSV loading. GB flit completion triggers the task.
        if (producerPE == -1) {
            TaskDescriptor* task = new TaskDescriptor(targetTaskId, peId,
                                                       compTime, dataSize);
            task->pendingDependencies = 0;
            task->state = TASK_READY;
            // Default: send results back to GB (successor taskId=-1, peId=-1)
            task->successors.push_back(-1);
            task->successorPE[-1] = -1;
            taskList.push_back(task);
            taskMap[targetTaskId] = task;
            readyQueue.push(task);

            EV << "-I- TaskPE[" << peId << "] created task " << targetTaskId
               << " from GlobalBuffer (fallback) at " << simTime() << endl;

            scheduleNextTask();
            return;
        }

        EV << "-W- TaskPE[" << peId << "] received data for unknown task "
           << targetTaskId << endl;
        return;
    }

    TaskDescriptor* task = it->second;

    // GB packet complete: activate a CSV-loaded task
    if (producerPE == -1) {
        if (task->state == TASK_WAITING) {
            task->state = TASK_READY;
            readyQueue.push(task);

            EV << "-I- TaskPE[" << peId << "] task " << targetTaskId
               << " activated by GlobalBuffer at " << simTime()
               << " readyQueueSize=" << readyQueue.size() << endl;

            scheduleNextTask();
        }
        return;
    }

    // PE→PE dependency flit: decrement pending counter
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
    int n = 1;
    if (dataSize > 0 && flitSize > 0) n = (dataSize + flitSize - 1) / flitSize;
    return (n < 2) ? 2 : n;  // minimum 2 flits for proper START→END handshake
}

// -----------------------------------------------------------------------
// DVFS scaling: how much slower due to temperature
// Returns 1.0 at safe temperature, >1.0 when throttling
double TaskPE::getDvfsScaleFactor() const {
    double Tthrottle = getSystemModule()->par("Tthrottle");
    double beta = getSystemModule()->par("throttleBeta");
    double Tpe = getThermalModel()->getPEPerature(peId);

    if (Tpe <= Tthrottle) return 1.0;
    return 1.0 + beta * (Tpe - Tthrottle);
}

// Temperature-corrected power (leakage ~doubles every 10°C)
double TaskPE::getTemperatureCorrectedPower(bool idle) const {
    double Tambient = getSystemModule()->par("Tambient");
    double Tpe = getThermalModel()->getPEPerature(peId);
    double leakageFactor = exp((Tpe - Tambient) / 15.0);
    double leakageNow = powerIdle * leakageFactor;

    if (idle) {
        return leakageNow;
    } else {
        double dynamicSwitching = powerCompute - powerIdle;
        return dynamicSwitching + leakageNow;
    }
}

// updatePower
// -----------------------------------------------------------------------
void TaskPE::updatePower(bool isIdlePower) {
    currentPower = getTemperatureCorrectedPower(isIdlePower);
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
