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
#include "thermal/ThermalTrace.h"
#include "utils/TaskGraphParser.h"
#include "onoc/control/LogicalTopologyManager.h"

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

    // Dynamic energy from electrical flit events
    // (optical energy added directly in sendOpticalFlitFromQ / handleDataArrival)
    windowDynamicEnergyJ +=
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

// File-scope optical statistics accumulator
static long globalOpticalTotal = 0;
static int  globalFinishCount = 0;

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
    opticalModulatorEnergyPerFlit = par("opticalModulatorEnergyPerFlit");
    opticalReceiverEnergyPerFlit  = par("opticalReceiverEnergyPerFlit");
    enablePowerTrace = par("enablePowerTrace");
    computeDensity   = par("computeDensity");

    // NEW
    energyWindow = par("energyWindow");
    dvfsTickInterval = energyWindow;  // re-check temperature each energy window

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
    dvfsTickMsg        = new cMessage("dvfsTick");

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

    // Optical bypass initialization
    enableSetupHandshake = par("enableSetupHandshake");
    enableOpticalBypass = par("enableOpticalBypass");
    if (enableSetupHandshake) {
        cModule *managerModule = getSystemModule()->getSubmodule("topologyManager");
        topologyManager = dynamic_cast<LogicalTopologyManager *>(managerModule);
        if (!topologyManager) {
            throw cRuntimeError("TaskPE[%d]: topologyManager not found with setup handshake enabled", peId);
        }
        numRows = getSystemModule()->par("rows").intValue();
        numNodes = numRows * numColumns + numRows; // PEs + GB connector rows
        setupRetryDelay = par("setupRetryDelay");
        setupPendingTimeout = par("setupPendingTimeout");
        opticalRequiredWavelengths = par("opticalRequiredWavelengths");
        opticalWavelengthBitrate = par("opticalWavelengthBitrate");
        opticalBasePropagationDelay = par("opticalBasePropagationDelay");
        opticalPerHopDelay = par("opticalPerHopDelay");
        opticalBurstSize = par("opticalBurstSize");

        circuitReadyByDst.assign(numNodes, 0);
        setupPendingByDst.assign(numNodes, 0);
        pendingDataQ.assign(numNodes, std::vector<TaskMsg*>());
        nextSetupAttemptByDst.assign(numNodes, SIMTIME_ZERO);
        setupPendingExpiryByDst.assign(numNodes, SIMTIME_ZERO);
        pendingSetupTokenByDst.assign(numNodes, 0);
        activeCircuitTokenByDst.assign(numNodes, 0);
        setupReqRxCount = 0;
        setupAckRxCount = 0;
        opticalPacketsSent = 0;
        lastOpticalSendTime = SIMTIME_ZERO;
        setupAckAcceptedCount = 0;
        setupAckStaleCount = 0;
        setupReserveFailCount = 0;
        setupPendingTimeoutCount = 0;

        setupReqEventSignal = registerSignal("onoc-setup-req-event");
        setupAckEventSignal = registerSignal("onoc-setup-ack-event");
        getSimulation()->getSystemModule()->subscribe("onoc-setup-req-event", this);
        getSimulation()->getSystemModule()->subscribe("onoc-setup-ack-event", this);

        char controlPopName[32];
        sprintf(controlPopName, "control-pop-pe%d", peId);
        controlPopMsg = new cMessage(controlPopName);
        controlPopMsg->setKind(NOC_POP_MSG);
        scheduleAt(simTime() + tClk_s * 0.5, controlPopMsg);

        char opticalPopName[32];
        sprintf(opticalPopName, "optical-pop-pe%d", peId);
        opticalPopMsg = new cMessage(opticalPopName);
        opticalPopMsg->setKind(NOC_CLK_MSG);

    } else {
        numRows = 0;
        numNodes = 0;
        topologyManager = nullptr;
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

    if (msg == dvfsTickMsg) {
        handleDvfsTick();
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

    if (msg == controlPopMsg) {
        sendControlFlitFromQ();
        scheduleAt(simTime() + tClk_s, controlPopMsg);
        return;
    }

    if (msg == opticalPopMsg) {
        sendOpticalFlitFromQ();
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

        delete crd;
        // Try controlQ first (priority), then regular injectQ
        sendControlFlitFromQ();
        sendFlitFromQ();
        return;
    }

    if (strcmp(msg->getName(), "checkStop") == 0) {
        // Check if all PEs have finished flushing pending data
        bool allDone = true;
        int numPEs = getSystemModule()->par("rows").intValue()
                   * getSystemModule()->par("columns").intValue();
        for (int pid = 0; pid < numPEs; pid++) {
            cModule *pe = getSystemModule()->getSubmodule("pe", pid);
            if (!pe) continue;
            TaskPE *tpe = dynamic_cast<TaskPE *>(pe);
            if (!tpe) continue;
            if (!tpe->isAllDataSent()) { allDone = false; break; }
        }
        if (allDone) {
            cancelAndDelete(msg);
            endSimulation();
            return;
        }
        scheduleAt(simTime() + SimTime(50, SIMTIME_NS), msg);
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
// updateOpticalLabel — update module display for Qtenv visibility
// -----------------------------------------------------------------------
void TaskPE::updateOpticalLabel() {
    if (!enableSetupHandshake || numNodes <= 0) return;

    int nReady = 0, nPending = 0;
    for (int d = 0; d < numNodes; d++) {
        if (circuitReadyByDst[d]) nReady++;
        if (setupPendingByDst[d]) nPending++;
    }

    // Colored icon: green dot=active, gold dot=pending, default=idle
    // Format: i=<iconname>,<color>
    if (nReady > 0) {
        getDisplayString().setTagArg("i", 0, "");
        getDisplayString().setTagArg("i", 1, "green");
    } else if (nPending > 0) {
        getDisplayString().setTagArg("i", 0, "");
        getDisplayString().setTagArg("i", 1, "gold");
    } else {
        getDisplayString().setTagArg("i", 1, "");  // clear color, keep default icon
    }

    // Text label
    char buf[64];
    if (nReady > 0) {
        snprintf(buf, sizeof(buf), "OPT:%ld", opticalPacketsSent);
    } else if (nPending > 0) {
        snprintf(buf, sizeof(buf), "SETUP");
    } else if (opticalPacketsSent > 0) {
        snprintf(buf, sizeof(buf), "OPT:%ld", opticalPacketsSent);
    } else {
        buf[0] = '\0';
    }
    getDisplayString().setTagArg("t", 0, buf);
}

// -----------------------------------------------------------------------
// refreshDisplay — const_cast to call non-const updateOpticalLabel
// -----------------------------------------------------------------------
void TaskPE::refreshDisplay() const {
    const_cast<TaskPE*>(this)->updateOpticalLabel();
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

    // Optical statistics
    if (enableSetupHandshake) {
        getSimulation()->getSystemModule()->unsubscribe(setupReqEventSignal, this);
        getSimulation()->getSystemModule()->unsubscribe(setupAckEventSignal, this);
        recordScalar("pe-setup-req-rx", static_cast<double>(setupReqRxCount));
        recordScalar("pe-setup-ack-rx", static_cast<double>(setupAckRxCount));
        recordScalar("pe-setup-ack-accepted", static_cast<double>(setupAckAcceptedCount));
        recordScalar("pe-setup-ack-stale", static_cast<double>(setupAckStaleCount));
        recordScalar("pe-setup-reserve-fail", static_cast<double>(setupReserveFailCount));
        recordScalar("pe-setup-pending-timeout", static_cast<double>(setupPendingTimeoutCount));
        recordScalar("pe-optical-packets-sent", static_cast<double>(opticalPacketsSent));
    }

    // DVFS throttling statistics
    recordScalar("totalComputeTimeNominal", totalComputeTimeNominal);
    recordScalar("totalThrottlePenalty",    totalThrottlePenalty);
    double penaltyRatio = 0.0;
    if (totalComputeTimeNominal.dbl() > 0.0)
        penaltyRatio = totalThrottlePenalty.dbl() / totalComputeTimeNominal.dbl();
    recordScalar("throttlePenaltyRatio",    penaltyRatio);

    // ── Optical bypass statistics (printf to console) ──
    if (enableSetupHandshake && opticalPacketsSent > 0) {
        printf("[OPTICAL-STATS] PE%d  optical-flits=%ld  setup-req-rx=%ld  setup-ack-rx=%ld  setup-ack-ok=%ld\n",
               peId, opticalPacketsSent, setupReqRxCount, setupAckRxCount, setupAckAcceptedCount);
        fflush(stdout);
    }
    globalOpticalTotal += opticalPacketsSent;
    globalFinishCount++;
    // Print grand total when the last PE finishes (16 PEs in 4x4 mesh)
    if (enableSetupHandshake && globalFinishCount >= 16) {
        printf("[OPTICAL-STATS] ===== GRAND TOTAL: %ld optical flits sent via sendDirect =====\n",
               globalOpticalTotal);
        fflush(stdout);
    }

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
    cancelAndDelete(energyWindowMsg);
    cancelAndDelete(dvfsTickMsg);
    if (controlPopMsg) cancelAndDelete(controlPopMsg);
    if (opticalPopMsg) cancelAndDelete(opticalPopMsg);

    for (TaskDescriptor* t : taskList) {
        delete t;
    }

    while (!injectQ.empty()) {
        delete injectQ.front();
        injectQ.pop();
    }
    while (!controlQ.isEmpty()) {
        delete controlQ.pop();
    }
    while (!opticalDataQ.isEmpty()) {
        delete opticalDataQ.pop();
    }
    for (int d = 0; d < (int)pendingDataQ.size(); d++) {
        for (TaskMsg* f : pendingDataQ[d]) delete f;
        pendingDataQ[d].clear();
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

// =======================================================================
// Optical bypass helpers
// =======================================================================
void TaskPE::ensureOpticalStateSize(int dst) {
    if (dst < 0 || dst >= numNodes) return;
    (void)dst;
}

bool TaskPE::tryReserveSetupPath(int dst, int &token) {
    token = 0;
    if (!enableSetupHandshake || !topologyManager) return false;
    // Map GB ID to column-0 router node for path computation
    int numPEs_try = numRows * numColumns;
    int mappedDst = dst;
    if (dst >= bufferBaseId && dst < bufferBaseId + numRows) {
        int gbRow = dst - bufferBaseId;
        mappedDst = gbRow * numColumns;
    } else if (dst >= numPEs_try && dst < numPEs_try + numRows) {
        int gbRow = dst - numPEs_try;
        mappedDst = gbRow * numColumns;
    }
    int spatial = 0, wlMask = 0;
    bool insufficient = false;
    std::string reason;
    bool ok = topologyManager->reserveOpticalPathForSetup(peId, mappedDst,
            token, spatial, wlMask, insufficient, reason);
    if (!ok) {
        EV_WARN << "TaskPE[" << peId << "] setup reserve FAIL "
                << peId << "->" << dst << ": " << reason << endl;
        return false;
    }
    return true;
}

// -----------------------------------------------------------------------
// sendControlFlitFromQ — sends SETUP_REQ/ACK flits via electrical network
// -----------------------------------------------------------------------
void TaskPE::sendControlFlitFromQ() {
    // Periodic: retry timed-out setups (matches PktFifoSrc — no electrical fallback)
    if (enableSetupHandshake && numNodes > 0) {
        for (int d = 0; d < numNodes; d++) {
            if (setupPendingByDst[d] && simTime() >= setupPendingExpiryByDst[d]) {
                setupPendingTimeoutCount++;
                int pt = pendingSetupTokenByDst[d];
                if (pt > 0 && topologyManager)
                    topologyManager->releaseOpticalPathByToken(pt);
                setupPendingByDst[d] = 0;
                setupPendingExpiryByDst[d] = SIMTIME_ZERO;
                pendingSetupTokenByDst[d] = 0;
                nextSetupAttemptByDst[d] = simTime();
            }
        }
        // Retry handshakes for destinations with pending data but no circuit/setup
        for (int d = 0; d < numNodes; d++) {
            if (pendingDataQ[d].empty()) continue;
            if (circuitReadyByDst[d] || setupPendingByDst[d]) continue;
            if (simTime() < nextSetupAttemptByDst[d]) continue;
            int setupToken = 0;
            if (tryReserveSetupPath(d, setupToken)) {
                int setupPktId = setupToken;
                // Map internal GB index back to raw GB ID for network routing
                int numPEs_r = numRows * numColumns;
                int netDst = (d >= numPEs_r) ? (bufferBaseId + (d - numPEs_r)) : d;
                for (int fi = 0; fi < 2; fi++) {
                    char sname[64];
                    snprintf(sname, sizeof(sname), "retry-s%d-d%d-f%d", peId, netDst, fi);
                    TaskMsg* sflit = new TaskMsg(sname);
                    sflit->setKind(NOC_FLIT_MSG);
                    sflit->setByteLength(flitSize);
                    sflit->setBitLength(8 * flitSize);
                    sflit->setVC(0);
                    sflit->setSrcId(peId); sflit->setDstId(netDst);
                    sflit->setPktId(setupPktId);
                    sflit->setFlitIdx(fi); sflit->setFlits(2);
                    sflit->setFirstNet(true); sflit->setSchedulingPriority(0);
                    sflit->setType(fi == 0 ? NOC_START_FLIT : NOC_END_FLIT);
                    sflit->setTaskId(-1); sflit->setProducerPE(peId);
                    sflit->setConsumerPE(d); sflit->setProducerTaskId(-1);
                    sflit->setDataSize(0); sflit->setComputeTime(0);
                    controlQ.insert(sflit);
                }
                setupPendingByDst[d] = 1;
                setupPendingExpiryByDst[d] = simTime() + setupPendingTimeout;
                pendingSetupTokenByDst[d] = setupToken;
                nextSetupAttemptByDst[d] = simTime() + setupRetryDelay;
                // Flit will be sent on next periodic controlPopMsg — no recursive call
            } else {
                setupReserveFailCount++;
                nextSetupAttemptByDst[d] = simTime() + setupRetryDelay;
            }
        }
    }

    if (controlQ.isEmpty()) return;
    if (credits <= 0) return;

    cChannel* ch = gate("out$o")->getTransmissionChannel();
    if (ch && ch->isBusy()) return;

    TaskMsg *flit = check_and_cast<TaskMsg *>(controlQ.pop());
    send(flit, "out$o");
    credits--;
}

// -----------------------------------------------------------------------
// sendOpticalFlitFromQ — sends data flits via optical bypass (sendDirect)
// -----------------------------------------------------------------------
void TaskPE::sendOpticalFlitFromQ() {
    if (opticalDataQ.isEmpty()) return;
    if (opticalPopMsg->isScheduled()) return;

    // Find the first flit whose circuit is ready
    TaskMsg *flit = nullptr;
    for (int i = 0; i < opticalDataQ.getLength(); i++) {
        TaskMsg *candidate = check_and_cast<TaskMsg *>(opticalDataQ.get(i));
        int rawDst = candidate->getDstId();
        int dstPE = rawDst;
        int numPEs_opt = numRows * numColumns;
        if (rawDst >= bufferBaseId && rawDst < bufferBaseId + numRows) {
            dstPE = numPEs_opt + (rawDst - bufferBaseId);
        }
        if (dstPE >= 0 && dstPE < numNodes && circuitReadyByDst[dstPE]) {
            flit = candidate;
            break;
        }
    }
    if (!flit) return;  // no ready circuit for any queued packet

    opticalDataQ.remove(flit);

    int dstPE_orig = flit->getDstId();
    int numPEs_release = numRows * numColumns;
    int dstIdx = dstPE_orig;
    if (dstPE_orig >= bufferBaseId && dstPE_orig < bufferBaseId + numRows) {
        dstIdx = numPEs_release + (dstPE_orig - bufferBaseId);
    }

    if (flit->getFlitIdx() % 100 == 0 || flit->getType() == NOC_END_FLIT) {
        printf("[OPTICAL] PE%d SEND-OPTICAL pktId=%d flitIdx=%d/%d dstPE=%d at t=%.6fus\n",
               peId, flit->getPktId(), flit->getFlitIdx(),
               flit->getFlits() - 1, dstPE_orig, simTime().dbl() * 1e6);
    }

    flit->setInjectTime(simTime());
    lastOpticalSendTime = simTime();

    int flitType = flit->getType();  // save before sendDirect transfers ownership
    simtime_t txDuration = computeOpticalTxDuration(flit);  // save before sendDirect transfers ownership

    if (!sendFlitDirectToSink(flit)) {
        throw cRuntimeError("TaskPE[%d] optical sendDirect failed to PE%d", peId, dstPE_orig);
    }

    totalFlitsSent++;
    windowDynamicEnergyJ += opticalModulatorEnergyPerFlit;
    opticalPacketsSent++;
    updateOpticalLabel();   // update Qtenv display

    // On END flit, release circuit
    if (flitType == NOC_END_FLIT) {
        int token = activeCircuitTokenByDst[dstIdx];
        if (token > 0 && topologyManager) {
            topologyManager->releaseOpticalPathByToken(token);
        }
        circuitReadyByDst[dstIdx] = 0;
        activeCircuitTokenByDst[dstIdx] = 0;
        printf("[OPTICAL] PE%d TEARDOWN circuit to dst=%d token=%d at t=%.6fus\n",
               peId, dstIdx, token, simTime().dbl() * 1e6);
        updateOpticalLabel();
    }

    scheduleAt(simTime() + txDuration, opticalPopMsg);
}

void TaskPE::flushPendingData(int dst) {
    if (pendingDataQ[dst].empty()) return;
    if (circuitReadyByDst[dst]) {
        for (TaskMsg* flit : pendingDataQ[dst]) {
            opticalDataQ.insert(flit);
        }
        printf("[OPTICAL] PE%d flush %d pending flits to opticalDataQ for dst=%d at t=%.6fus\n",
               peId, (int)pendingDataQ[dst].size(), dst, simTime().dbl() * 1e6);
        pendingDataQ[dst].clear();
        sendOpticalFlitFromQ();
    }
    // Else: keep waiting for circuit (matching PktFifoSrc — no electrical fallback)
}

int TaskPE::meshHopDistance(int src, int dst) const {
    if (numRows <= 0 || numColumns <= 0) return 0;
    int srcRow = src / numColumns, srcCol = src % numColumns;
    int dstRow = dst / numColumns, dstCol = dst % numColumns;
    return abs(srcRow - dstRow) + abs(srcCol - dstCol);
}

simtime_t TaskPE::computeOpticalPropagationDelay(int src, int dst) const {
    return opticalBasePropagationDelay + opticalPerHopDelay * meshHopDistance(src, dst);
}

simtime_t TaskPE::computeOpticalTxDuration(const TaskMsg *flit) const {
    if (!flit) return SIMTIME_ZERO;
    int wlCount = opticalRequiredWavelengths;
    if (wlCount <= 0) wlCount = 1;
    double effRate = opticalWavelengthBitrate * wlCount;
    double txSec = (8.0 * flit->getByteLength()) / effRate;
    int64_t txPs = static_cast<int64_t>(txSec * 1e12 + 0.5);
    if (txPs < 1) txPs = 1;
    return SimTime(txPs, SIMTIME_PS);
}

bool TaskPE::sendFlitDirectToSink(TaskMsg *flit) {
    if (!flit) return false;
    int dst = flit->getDstId();
    cSimpleModule *targetMod = nullptr;
    if (dst >= bufferBaseId && dst < bufferBaseId + numRows) {
        targetMod = check_and_cast<cSimpleModule *>(
                getSystemModule()->getSubmodule("globalBuffer"));
    } else {
        targetMod = check_and_cast<cSimpleModule *>(
                getSystemModule()->getSubmodule("pe", dst));
    }
    flit->setFirstNet(false);
    flit->setFirstNetTime(simTime());
    simtime_t propDelay = computeOpticalPropagationDelay(flit->getSrcId(), flit->getDstId());
    simtime_t txDuration = computeOpticalTxDuration(flit);
    sendDirect(flit, propDelay, txDuration, targetMod->gate("opticalIn"));
    return true;
}

cSimpleModule *TaskPE::getDestinationPEModule(int dst) const {
    cModule *peMod = getSystemModule()->getSubmodule("pe", dst);
    if (!peMod) {
        throw cRuntimeError("TaskPE[%d]: pe[%d] not found for optical", peId, dst);
    }
    return check_and_cast<cSimpleModule *>(peMod);
}

void TaskPE::handleControlEvent(int eventType, int requesterId,
        int targetId, int token) {
    // Handled via handleDataArrival for TaskPE (SETUP_REQ/ACK are flits)
    (void)eventType; (void)requesterId; (void)targetId; (void)token;
}

void TaskPE::receiveSignal(cComponent *source, simsignal_t signalID,
        intval_t value, cObject *details) {
    (void)source; (void)details;
    Enter_Method_Silent("TaskPE::receiveSignal()");
    if (!enableSetupHandshake) return;
    if (signalID != setupReqEventSignal && signalID != setupAckEventSignal) return;
    int eventType = 0, requesterId = -1, targetId = -1, token = 0, spatial = 0, wlMask = 0;
    onocDecodeControlEvent(value, eventType, requesterId, targetId, token, spatial, wlMask);
    handleControlEvent(eventType, requesterId, targetId, token);
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

    // Periodic DVFS thermal throttling: re-check temperature each tick
    // Instead of computing a fixed actualTime once, advance nominal work
    // per tick: remainingNominalWork -= dvfsTickInterval / dvfsScale(T_current)
    remainingNominalWork = nominalTime;
    totalComputeTimeNominal += nominalTime;

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_COMPUTE_START, now, powerCompute);
    }

    double dvfsScale = getDvfsScaleFactor();
    double TpeC = getThermalModel()->getPEPerature(peId) - 273.15;
    printf("[PE%d] task=%d START at t=%.3fus nominalTime=%.3fus dvfs=%.3f Tpe=%.1fC (periodic)\n",
           peId, task->taskId, now.dbl()*1e6, nominalTime.dbl()*1e6,
           dvfsScale, TpeC);

    scheduleAt(simTime() + dvfsTickInterval, dvfsTickMsg);
}

// -----------------------------------------------------------------------
// handleDvfsTick — periodic DVFS re-check during computation
// -----------------------------------------------------------------------
void TaskPE::handleDvfsTick() {
    if (!currentTask || remainingNominalWork <= 0.0) {
        // Task completed or was preempted — fall through to complete
        completeComputation();
        return;
    }

    // Read current PE temperature and compute DVFS scale
    double dvfsScale = getDvfsScaleFactor();
    double Tpe = getThermalModel()->getPEPerature(peId);

    // Advance nominal work: dt_real / dvfsScale
    // At dvfsScale=1.0, 100ns tick → 100ns nominal progress
    // At dvfsScale=2.0, 100ns tick → 50ns nominal progress (slower)
    double workDone = dvfsTickInterval.dbl() / dvfsScale;
    remainingNominalWork -= workDone;

    // Track throttle penalty: the extra real time spent this tick
    // penalty = real_time - nominal_progress = dt - workDone
    totalThrottlePenalty += dvfsTickInterval - workDone;

    if (remainingNominalWork <= 0.0) {
        completeComputation();
    } else {
        scheduleAt(simTime() + dvfsTickInterval, dvfsTickMsg);
    }
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

    printf("[PE%d] task=%d DONE at t=%.3fus actualCompute=%.3fus output=%dB successors=%d\n",
           peId, task->taskId, now.dbl()*1e6,
           (task->finishTime - task->startTime).dbl()*1e6,
           task->outputDataSize, (int)task->successors.size());

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
        // Start a periodic check: wait until all pending data is flushed
        scheduleAt(simTime(), new cMessage("checkStop"));
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

        // dstPE == -1 means the successor PE is the GlobalBuffer (GB sink);
        // convert to the actual GB network address for this PE's row.
        if (dstPE == -1) {
            int row = peId / numColumns;
            dstPE = bufferBaseId + row;
        }

        if (dstPE == peId) continue;

        bool toGB = (dstPE >= bufferBaseId && dstPE < bufferBaseId + numRows);
        int numPEs = numRows * numColumns;
        int optIdx = toGB ? (numPEs + (dstPE - bufferBaseId)) : dstPE;

        if (enableSetupHandshake && enableOpticalBypass && optIdx >= 0 && optIdx < numNodes) {
            ensureOpticalStateSize(optIdx);

            // Check for pending timeout
            if (setupPendingByDst[optIdx] && simTime() >= setupPendingExpiryByDst[optIdx]) {
                setupPendingTimeoutCount++;
                int pendingToken = pendingSetupTokenByDst[optIdx];
                if (pendingToken > 0 && topologyManager) {
                    topologyManager->releaseOpticalPathByToken(pendingToken);
                }
                setupPendingByDst[optIdx] = 0;
                setupPendingExpiryByDst[optIdx] = SIMTIME_ZERO;
                pendingSetupTokenByDst[optIdx] = 0;
                nextSetupAttemptByDst[optIdx] = simTime();
            }

            // Initiate optical circuit with SETUP_REQ/ACK handshake
            if (!circuitReadyByDst[optIdx] && !setupPendingByDst[optIdx]
                    && simTime() >= nextSetupAttemptByDst[optIdx]) {
                int setupToken = 0;
                if (tryReserveSetupPath(dstPE, setupToken)) {
                    // Enqueue SETUP_REQ 2-flit packet in controlQ (electrical)
                    int setupPktId = setupToken; // use circuit token as pktId for ACK matching
                    for (int fi = 0; fi < 2; fi++) {
                        char sname[64];
                        snprintf(sname, sizeof(sname), "setup-s%d-d%d-f%d", peId, dstPE, fi);
                        TaskMsg* sflit = new TaskMsg(sname);
                        sflit->setKind(NOC_FLIT_MSG);
                        sflit->setByteLength(flitSize);
                        sflit->setBitLength(8 * flitSize);
                        sflit->setVC(0);
                        sflit->setSrcId(peId);
                        sflit->setDstId(dstPE);
                        sflit->setPktId(setupPktId);
                        sflit->setFlitIdx(fi); sflit->setFlits(2);
                        sflit->setFirstNet(true);
                        sflit->setSchedulingPriority(0);
                        sflit->setType(fi == 0 ? NOC_START_FLIT : NOC_END_FLIT);
                        sflit->setTaskId(-1);
                        sflit->setProducerPE(peId);
                        sflit->setConsumerPE(dstPE);
                        sflit->setProducerTaskId(-1);
                        sflit->setDataSize(0); sflit->setComputeTime(0);
                        controlQ.insert(sflit);
                    }
                    setupPendingByDst[optIdx] = 1;
                    setupPendingExpiryByDst[optIdx] = simTime() + setupPendingTimeout;
                    pendingSetupTokenByDst[optIdx] = setupToken;
                    nextSetupAttemptByDst[optIdx] = simTime() + setupRetryDelay;
                    sendControlFlitFromQ();
                    printf("[OPTICAL] PE%d SETUP_REQ -> PE%d token=%d at t=%.6fus\n",
                           peId, dstPE, setupToken, simTime().dbl() * 1e6);
                    updateOpticalLabel();
                } else {
                    setupReserveFailCount++;
                    nextSetupAttemptByDst[optIdx] = simTime() + setupRetryDelay;
                }
            }

        }

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

            // Put data in pending buffer — flushed when circuit ready (optical) or timeout (electrical)
            pendingDataQ[optIdx].push_back(flit);
        }

        EV << "-I- TaskPE[" << peId << "] queued PENDING packet pktId=" << pktId
           << " dstPE=" << dstPE << " numFlits=" << numFlits
           << " pendingSize=" << pendingDataQ[optIdx].size() << endl;

        // Flush if circuit already ready
        if (circuitReadyByDst[optIdx]) {
            flushPendingData(optIdx);
        }
    }

    sendFlitFromQ();
    sendOpticalFlitFromQ();
}

// -----------------------------------------------------------------------
// sendFlitFromQ – PktFifoSrc-like injection
// -----------------------------------------------------------------------
void TaskPE::sendFlitFromQ() {
    if (injectQ.empty()) {
        return;
    }

    // Don't interleave: wait until all control flits are sent
    if (!controlQ.isEmpty()) {
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

    EV << "-I- TaskPE[" << peId << "] SEND-ELECTRICAL"
       << " pktId=" << pktId << " flitIdx=" << flitIdx
       << "/" << (flit->getFlits() - 1)
       << " dstPE=" << flit->getDstId()
       << " at " << simTime() << endl;

    send(flit, "out$o");
    credits--;
    totalFlitsSent++;
    windowSendFlits++;

    if (powerTrace) {
        powerTrace->recordPEEvent(peId, PE_SEND_FLIT, simTime(),
                                  powerIdle + powerSendPerFlit / tClk_s);
    }
}

// -----------------------------------------------------------------------
// handleDataArrival
// -----------------------------------------------------------------------
void TaskPE::handleDataArrival(TaskMsg* msg) {
    // ── Handle SETUP control flits (taskId == -1) ──
    if (msg->getTaskId() == -1 && enableSetupHandshake) {
        int srcPE = msg->getSrcId();
        int pktId = msg->getPktId();
        sendCredit(msg->getVC(), 1);

        // SETUP_REQ from another PE → reply ACK only on END flit (1 response per circuit)
        if (msg->getProducerPE() >= 0 && srcPE != peId && msg->getType() == NOC_END_FLIT) {
            setupReqRxCount++;
            ensureOpticalStateSize(srcPE);
            intval_t eventVal = onocEncodeControlEvent(ONOC_EVT_SETUP_REQ,
                    srcPE, peId, pktId, 0, 0);
            emit(setupReqEventSignal, eventVal);

            // Send SETUP_ACK back through controlQ
            if (topologyManager) {
                for (int fi = 0; fi < 2; fi++) {
                    char ackName[64];
                    snprintf(ackName, sizeof(ackName), "ack-s%d-d%d-f%d", peId, srcPE, fi);
                    TaskMsg* ack = new TaskMsg(ackName);
                    ack->setKind(NOC_FLIT_MSG);
                    ack->setByteLength(flitSize);
                    ack->setBitLength(8 * flitSize);
                    ack->setVC(0); ack->setSrcId(peId); ack->setDstId(srcPE);
                    ack->setPktId(pktId); ack->setFlitIdx(fi); ack->setFlits(2);
                    ack->setFirstNet(true); ack->setSchedulingPriority(0);
                    ack->setType(fi == 0 ? NOC_START_FLIT : NOC_END_FLIT);
                    ack->setTaskId(-1); ack->setProducerPE(-1);
                    ack->setConsumerPE(srcPE); ack->setProducerTaskId(-1);
                    ack->setDataSize(0); ack->setComputeTime(0);
                    controlQ.insert(ack);
                }
                sendControlFlitFromQ();
                printf("[OPTICAL] PE%d SETUP_REQ rcvd from PE%d -> ACK sent at t=%.6fus\n",
                       peId, srcPE, simTime().dbl() * 1e6);
            }
        }

        // SETUP_ACK from another PE or GB (response to our SETUP_REQ)
        if (msg->getProducerPE() < 0 && srcPE != peId) {
            setupAckRxCount++;
            // Map GB ID to internal index
            int numPEs_ack = numRows * numColumns;
            int srcIdx = srcPE;
            if (srcPE >= bufferBaseId && srcPE < bufferBaseId + numRows) {
                srcIdx = numPEs_ack + (srcPE - bufferBaseId);
            }
            ensureOpticalStateSize(srcIdx);
            if (!circuitReadyByDst[srcIdx] && setupPendingByDst[srcIdx]) {
                setupAckAcceptedCount++;
                circuitReadyByDst[srcIdx] = 1;
                setupPendingByDst[srcIdx] = 0;
                setupPendingExpiryByDst[srcIdx] = SIMTIME_ZERO;
                activeCircuitTokenByDst[srcIdx] = pktId;
                printf("[OPTICAL] PE%d SETUP_ACK rcvd from PE%d -> CIRCUIT READY token=%d at t=%.6fus\n",
                       peId, srcPE, pktId, simTime().dbl() * 1e6);
                updateOpticalLabel();
                flushPendingData(srcIdx);
            } else if (!circuitReadyByDst[srcIdx]) {
                setupAckStaleCount++;
            }
            // Release old token if this ACK carries one
            if (pktId > 0 && pktId != activeCircuitTokenByDst[srcIdx] && topologyManager) {
                topologyManager->releaseOpticalPathByToken(pktId);
            }
        }

        delete msg;
        return;
    }

    totalFlitsReceived++;

    // Return one receive-side credit to router
    sendCredit(msg->getVC(), 1);

    // Optical flits: PD+TIA energy; electrical flits: standard recv energy
    if (!msg->getFirstNet()) {
        windowDynamicEnergyJ += opticalReceiverEnergyPerFlit;
    } else {
        windowRecvFlits++;
    }

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
