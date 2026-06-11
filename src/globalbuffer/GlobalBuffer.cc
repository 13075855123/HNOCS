//
// Copyright (C) 2024 HNOCS Project
//
// GlobalBuffer — task graph distribution and data relay (fixed mapping)
//

#include "GlobalBuffer.h"
#include "utils/TaskGraphParser.h"
#include "onoc/control/LogicalTopologyManager.h"
#include "onoc/common/ControlPlaneEvents.h"

Define_Module(GlobalBuffer);

static const int GB_OPTICAL_RELEASE_MSG = 9301;

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

    enableSetupHandshake = par("enableSetupHandshake");
    enableOpticalBypass = par("enableOpticalBypass");
    if (enableOpticalBypass) {
        controlQ.resize(numConnections);
        numColumns = getSystemModule()->par("columns").intValue();
        int numRows = getSystemModule()->par("rows").intValue();
        numPEs = numRows * numColumns;
        setupRetryDelay = par("setupRetryDelay");
        setupPendingTimeout = par("setupPendingTimeout");
        opticalRequiredWavelengths = par("opticalRequiredWavelengths");
        opticalWavelengthBitrate = par("opticalWavelengthBitrate");
        opticalBasePropagationDelay = par("opticalBasePropagationDelay");
        opticalPerHopDelay = par("opticalPerHopDelay");
        circuitReadyByDst.assign(numPEs, 0);
        setupPendingByDst.assign(numPEs, 0);
        nextSetupAttemptByDst.assign(numPEs, SIMTIME_ZERO);
        setupPendingExpiryByDst.assign(numPEs, SIMTIME_ZERO);
        pendingSetupTokenByDst.assign(numPEs, 0);
        activeCircuitTokenByDst.assign(numPEs, 0);
        pendingDataQ.assign(numPEs, std::vector<TaskMsg*>());
        cModule *mgr = getSystemModule()->getSubmodule("topologyManager");
        topologyManager = dynamic_cast<LogicalTopologyManager *>(mgr);
        opticalPopMsg = new cMessage("gb-optical-pop");
    }
    optPopMsg = new cMessage("gb-opt-pop");
    if (enableOpticalBypass) {
        scheduleAt(simTime() + tClk_s * 0.5, optPopMsg);
    }
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
    if (msg->getKind() == GB_OPTICAL_RELEASE_MSG) {
        handleOpticalRelease(msg);
        return;
    }

    if (msg == optPopMsg) {
        sendOpticalControlFlit();
        scheduleAt(simTime() + tClk_s, optPopMsg);
        return;
    }

    if (msg == opticalPopMsg) {
        sendFlitOptical();
        return;
    }

    if (msg == injectPopMsg) {
        sendFlitFromAllQs();
        if (enableOpticalBypass) sendFlitOptical();
        scheduleAt(simTime() + tClk_s, injectPopMsg);
        return;
    }

    if (hasGate("opticalIn") && msg->getArrivalGateId() == gate("opticalIn")->getId()) {
        TaskMsg* taskMsg = dynamic_cast<TaskMsg*>(msg);
        if (taskMsg) {
            totalFlitsReceived++;
            if (taskMsg->getType() == NOC_END_FLIT && taskMsg->getProducerPE() >= 0) {
                EV << "-I- GB optical END-flit from PE" << taskMsg->getProducerPE()
                   << " at " << simTime() << endl;
            }
            delete taskMsg;
        } else {
            delete msg;
        }
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
            // Handle SETUP_REQ or SETUP_ACK
            if (taskMsg->getTaskId() == -1 && enableOpticalBypass) {
                int srcPE = taskMsg->getSrcId();
                int pktId = taskMsg->getPktId();

                // SETUP_REQ from PE → GB reply with ACK (PE→GB direction)
                if (taskMsg->getProducerPE() >= 0 && taskMsg->getType() == NOC_END_FLIT) {
                    int gId = msg->getArrivalGateId();
                    int connIdx2 = -1;
                    for (int i2 = 0; i2 < numConnections; i2++) {
                        if (gId == gateHalf("in", cGate::INPUT, i2)->getId()) { connIdx2 = i2; break; }
                    }
                    if (connIdx2 >= 0) sendCredit(connIdx2, taskMsg->getVC(), 1);
                    int cols = getSystemModule()->par("columns").intValue();
                    int ackConnIdx = srcPE / cols;
                    int gbSrcId = baseId + ackConnIdx;
                    if (ackConnIdx >= 0 && ackConnIdx < numConnections) {
                        for (int fi = 0; fi < 2; fi++) {
                            char ackName[64];
                            snprintf(ackName, sizeof(ackName), "gb-ack-s%d-d%d-f%d", gbSrcId, srcPE, fi);
                            TaskMsg* ack = new TaskMsg(ackName);
                            ack->setKind(NOC_FLIT_MSG); ack->setByteLength(flitSize); ack->setBitLength(8*flitSize);
                            ack->setVC(0); ack->setSrcId(gbSrcId); ack->setDstId(srcPE);
                            ack->setPktId(pktId); ack->setFlitIdx(fi); ack->setFlits(2);
                            ack->setFirstNet(true); ack->setSchedulingPriority(0);
                            ack->setType(fi == 0 ? NOC_START_FLIT : NOC_END_FLIT);
                            ack->setSL(onocEncodePacketTag(ONOC_PKT_SETUP_ACK, 0, 0));
                            ack->setTaskId(-1); ack->setProducerPE(-1);
                            ack->setConsumerPE(srcPE); ack->setProducerTaskId(-1);
                            ack->setDataSize(0); ack->setComputeTime(0);
                            controlQ[ackConnIdx].insert(ack);
                        }
                    }
                    sendOpticalControlFlit();
                    delete taskMsg;
                    return;
                }

                // SETUP_ACK from PE → GB receives ACK (GB→PE direction)
                if (taskMsg->getProducerPE() < 0 && srcPE >= 0 && srcPE < numPEs) {
                    int pendingToken = pendingSetupTokenByDst[srcPE];
                    if (!circuitReadyByDst[srcPE] && setupPendingByDst[srcPE]
                            && pendingToken > 0 && pktId == pendingToken) {
                        circuitReadyByDst[srcPE] = 1;
                        setupPendingByDst[srcPE] = 0;
                        setupPendingExpiryByDst[srcPE] = SIMTIME_ZERO;
                        activeCircuitTokenByDst[srcPE] = pktId;
                        pendingSetupTokenByDst[srcPE] = 0;
                        flushPendingData(srcPE);
                    } else if (setupPendingByDst[srcPE]) {
                        if (pktId > 0 && topologyManager) {
                            topologyManager->releaseOpticalPathByToken(pktId);
                        }
                    } else if (!circuitReadyByDst[srcPE]) {
                        if (pktId > 0 && topologyManager) {
                            topologyManager->releaseOpticalPathByToken(pktId);
                        }
                    }
                    int gId2 = msg->getArrivalGateId();
                    int connIdx3 = -1;
                    for (int i3 = 0; i3 < numConnections; i3++) {
                        if (gId2 == gateHalf("in", cGate::INPUT, i3)->getId()) { connIdx3 = i3; break; }
                    }
                    if (connIdx3 >= 0) sendCredit(connIdx3, taskMsg->getVC(), 1);
                    delete taskMsg;
                    return;
                }

                // Return credit for PE→GB SETUP_REQ START_FLIT
                // (END_FLIT credit is returned at line 153 above)
                {
                    int gIdS = msg->getArrivalGateId();
                    int connIdxS = -1;
                    for (int iS = 0; iS < numConnections; iS++) {
                        if (gIdS == gateHalf("in", cGate::INPUT, iS)->getId()) { connIdxS = iS; break; }
                    }
                    if (connIdxS >= 0) sendCredit(connIdxS, taskMsg->getVC(), 1);
                }
                delete taskMsg;
                return;
            }

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
        if (t->state == TASK_COMPLETED) completedCount++;
    }
    recordScalar("totalFlitsSent",     totalFlitsSent);
    recordScalar("totalFlitsReceived", totalFlitsReceived);
    recordScalar("totalTasks",         (long)taskList.size());
    recordScalar("tasksCompleted",     (long)completedCount);
}

void GlobalBuffer::flushPendingData(int peId) {
    if (pendingDataQ[peId].empty()) return;
    if (circuitReadyByDst[peId]) {
        // Move at most ONE complete packet (up to first END_FLIT)
        // to avoid HoL blocking when multiple packets are pending for the same PE.
        auto &q = pendingDataQ[peId];
        size_t count = 0;
        for (size_t i = 0; i < q.size(); i++) {
            opticalDataQ.insert(q[i]);
            count++;
            if (q[i]->getType() == NOC_END_FLIT) break;
        }
        q.erase(q.begin(), q.begin() + count);
        sendFlitOptical();
    }
}

bool GlobalBuffer::tryReserveSetupPath(int dstPE, int &token) {
    token = 0;
    if (!topologyManager) return false;
    // Map GB source to column-0 router node
    int gbRow = dstPE / numColumns;  // which GB connector
    int gbSrcNode = gbRow * numColumns; // router at column 0 of this row
    int spatial = 0, wlMask = 0;
    bool insufficient = false;
    std::string reason;
    bool ok = topologyManager->reserveOpticalPathForSetup(gbSrcNode, dstPE,
            token, spatial, wlMask, insufficient, reason);
    return ok;
}

bool GlobalBuffer::sendFlitDirectToPE(TaskMsg *flit) {
    int dst = flit->getDstId();
    cSimpleModule *targetMod = check_and_cast<cSimpleModule *>(
            getSystemModule()->getSubmodule("pe", dst));
    flit->setInjectTime(simTime());
    flit->setFirstNet(false);
    flit->setFirstNetTime(simTime());
    // Map GB source address to its physical router (column 0 of the GB's row).
    // getSrcId() returns baseId+row; the corresponding router is at (row, col=0).
    int gbRow = flit->getSrcId() - baseId;
    int gbRouter = gbRow * numColumns;
    int hops = abs(gbRouter/numColumns - dst/numColumns) + abs(gbRouter%numColumns - dst%numColumns);
    simtime_t propDelay = opticalBasePropagationDelay + opticalPerHopDelay * hops;
    double effRate = opticalWavelengthBitrate * opticalRequiredWavelengths;
    double txSec = (8.0 * flit->getByteLength()) / effRate;
    int64_t txPs = static_cast<int64_t>(txSec * 1e12 + 0.5);
    if (txPs < 1) txPs = 1;
    simtime_t txDuration = SimTime(txPs, SIMTIME_PS);
    sendDirect(flit, propDelay, txDuration, targetMod->gate("opticalIn"));
    return true;
}

void GlobalBuffer::sendFlitOptical() {
    if (opticalDataQ.isEmpty()) return;
    if (opticalPopMsg && opticalPopMsg->isScheduled()) return;
    TaskMsg *flit = check_and_cast<TaskMsg *>(opticalDataQ.front());
    int dstPE = flit->getDstId();
    if (dstPE < 0 || dstPE >= numPEs || !circuitReadyByDst[dstPE]) return;
    opticalDataQ.pop();
    int flitType = flit->getType();  // save before sendDirect transfers ownership
    int gbRow = flit->getSrcId() - baseId;
    int gbRouter = gbRow * numColumns;
    int hops = abs(gbRouter/numColumns - dstPE/numColumns) + abs(gbRouter%numColumns - dstPE%numColumns);
    simtime_t propDelay = opticalBasePropagationDelay + opticalPerHopDelay * hops;
    double effRate = opticalWavelengthBitrate * opticalRequiredWavelengths;
    double txSec = (8.0 * flit->getByteLength()) / effRate;
    int64_t txPs = static_cast<int64_t>(txSec * 1e12 + 0.5);
    if (txPs < 1) txPs = 1;
    simtime_t txDuration = SimTime(txPs, SIMTIME_PS);
    if (!sendFlitDirectToPE(flit)) return;
    totalFlitsSent++;
    if (flitType == NOC_END_FLIT) {
        int token = activeCircuitTokenByDst[dstPE];
        circuitReadyByDst[dstPE] = 0;
        activeCircuitTokenByDst[dstPE] = 0;
        simtime_t releaseDelay = propDelay + txDuration;
        nextSetupAttemptByDst[dstPE] = simTime() + releaseDelay;
        scheduleOpticalRelease(dstPE, token, releaseDelay);
    }
    if (opticalPopMsg && !opticalPopMsg->isScheduled()) {
        scheduleAt(simTime() + txDuration, opticalPopMsg);
    }
}

void GlobalBuffer::scheduleOpticalRelease(int dstPE, int token, simtime_t delay) {
    if (token <= 0) return;

    cMessage *releaseMsg = new cMessage("gbOpticalRelease");
    releaseMsg->setKind(GB_OPTICAL_RELEASE_MSG);
    releaseMsg->addPar("dstPE") = dstPE;
    releaseMsg->addPar("token") = token;
    pendingOpticalReleaseMsgs.insert(releaseMsg);
    scheduleAt(simTime() + delay, releaseMsg);
}

void GlobalBuffer::handleOpticalRelease(cMessage *msg) {
    pendingOpticalReleaseMsgs.erase(msg);

    int dstPE = (int)msg->par("dstPE").longValue();
    int token = (int)msg->par("token").longValue();
    if (token > 0 && topologyManager) {
        topologyManager->releaseOpticalPathByToken(token);
    }

    if (dstPE >= 0 && dstPE < (int)activeCircuitTokenByDst.size()
            && activeCircuitTokenByDst[dstPE] == token) {
        activeCircuitTokenByDst[dstPE] = 0;
        circuitReadyByDst[dstPE] = 0;
    }

    delete msg;
}

void GlobalBuffer::sendOpticalControlFlit() {
    int cols = getSystemModule()->par("columns").intValue();
    for (int ci = 0; ci < numConnections; ci++) {
        if (controlQ[ci].isEmpty()) continue;
        if (credits[ci] <= 0) continue;
        cChannel* ch = gateHalf("out", cGate::OUTPUT, ci)->getTransmissionChannel();
        if (ch && ch->isBusy()) continue;
        TaskMsg *flit = check_and_cast<TaskMsg *>(controlQ[ci].pop());
        send(flit, "out$o", ci);
        credits[ci]--;
        return;
    }
}

GlobalBuffer::~GlobalBuffer() {
    cancelAndDelete(injectPopMsg);
    if (optPopMsg) cancelAndDelete(optPopMsg);
    if (opticalPopMsg) cancelAndDelete(opticalPopMsg);
    for (cMessage *releaseMsg : pendingOpticalReleaseMsgs) {
        cancelAndDelete(releaseMsg);
    }
    pendingOpticalReleaseMsgs.clear();
    while (!opticalDataQ.isEmpty()) delete opticalDataQ.pop();
    for (int d = 0; d < numPEs; d++) {
        for (TaskMsg* f : pendingDataQ[d]) delete f;
        pendingDataQ[d].clear();
    }
    for (int ci = 0; ci < numConnections; ci++) {
        while (!controlQ[ci].isEmpty()) delete controlQ[ci].pop();
    }
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

    // Explicit GB injection tasks (peId == -1). Empty GB marker rows are
    // metadata only and must not disable the legacy implicit distribution path.
    bool queuedExplicit = false;
    for (TaskDescriptor* gbTask : taskList) {
        if (gbTask->assignedPE != -1) continue;
        if (gbTask->successors.empty()) continue;

        for (int succId : gbTask->successors) {
            auto sit = gbTask->successorPE.find(succId);
            if (sit == gbTask->successorPE.end()) continue;

            int dstPE = sit->second;
            int dstRow = dstPE / columns;
            int connIdx = dstRow;
            if (dstPE < 0 || connIdx < 0 || connIdx >= numConnections) {
                throw cRuntimeError("GlobalBuffer: invalid GB successor mapping task %d -> %d on PE %d",
                        gbTask->taskId, succId, dstPE);
            }
            queueFlit(connIdx, dstPE, succId, gbTask->outputDataSize,
                      gbTask->computeTime.dbl());
            queuedExplicit = true;
        }
    }

    if (queuedExplicit) {
        sendFlitFromAllQs();
        return;
    }

    // Implicit mode (backward compat)
    for (TaskDescriptor* task : taskList) {
        if (task->assignedPE < 0) continue;
        if (!task->predecessors.empty()) continue;
        int dstPE = task->assignedPE;
        int dstRow = dstPE / columns;
        int connIdx = dstRow;
        if (connIdx < 0 || connIdx >= numConnections) {
            throw cRuntimeError("GlobalBuffer: invalid implicit destination PE %d for task %d",
                    dstPE, task->taskId);
        }
        queueFlit(connIdx, dstPE, task->taskId, task->outputDataSize,
                  task->computeTime.dbl());
    }
    sendFlitFromAllQs();
}

// -----------------------------------------------------------------------
void GlobalBuffer::handleDataArrival(int connIdx, TaskMsg* msg) {
    totalFlitsReceived++;
    sendCredit(connIdx, msg->getVC(), 1);

    // END flit from PE → one result packet arrived at GB
    if (msg->getType() == NOC_END_FLIT && msg->getProducerPE() >= 0) {
        EV << "-I- GlobalBuffer END-flit from PE" << msg->getProducerPE()
           << " at t=" << simTime() << endl;
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

        if (enableOpticalBypass && dstPE >= 0 && dstPE < numPEs) {
            pendingDataQ[dstPE].push_back(flit);
        } else {
            injectQ[connIdx].push(flit);
        }
    }

    // Initiate optical handshake for PE destinations
    if (enableOpticalBypass && dstPE >= 0 && dstPE < numPEs) {
        if (!circuitReadyByDst[dstPE] && !setupPendingByDst[dstPE]
                && simTime() >= nextSetupAttemptByDst[dstPE]) {
            int setupToken = 0;
            if (tryReserveSetupPath(dstPE, setupToken)) {
                // GB's source = column-0 router ID for path computation
                int gbSrcId = baseId + connIdx;
                int setupPktId = setupToken;
                for (int fi = 0; fi < 2; fi++) {
                    char sname[64];
                    snprintf(sname, sizeof(sname), "gb-setup-s%d-d%d-f%d", gbSrcId, dstPE, fi);
                    TaskMsg* sflit = new TaskMsg(sname);
                    sflit->setKind(NOC_FLIT_MSG);
                    sflit->setByteLength(flitSize); sflit->setBitLength(8*flitSize);
                    sflit->setVC(0); sflit->setSrcId(gbSrcId); sflit->setDstId(dstPE);
                    sflit->setPktId(setupPktId); sflit->setFlitIdx(fi); sflit->setFlits(2);
                    sflit->setFirstNet(true); sflit->setSchedulingPriority(0);
                    sflit->setType(fi==0?NOC_START_FLIT:NOC_END_FLIT);
                    sflit->setSL(onocEncodePacketTag(ONOC_PKT_SETUP_REQ, 0, 0));
                    sflit->setTaskId(-1); sflit->setProducerPE(baseId);
                    sflit->setConsumerPE(dstPE); sflit->setProducerTaskId(-1);
                    sflit->setDataSize(0); sflit->setComputeTime(0);
                    injectQ[connIdx].push(sflit);
                }
                setupPendingByDst[dstPE] = 1;
                setupPendingExpiryByDst[dstPE] = simTime() + setupPendingTimeout;
                pendingSetupTokenByDst[dstPE] = setupToken;
                nextSetupAttemptByDst[dstPE] = simTime() + setupRetryDelay;
            } else {
                nextSetupAttemptByDst[dstPE] = simTime() + setupRetryDelay;
            }
        }
    }
}

void GlobalBuffer::sendFlitFromAllQs() {
    for (int i = 0; i < numConnections; i++) sendFlitFromQ(i);
}

void GlobalBuffer::sendFlitFromQ(int connIdx) {
    // Retry timed-out setups + drain pending when circuit ready
    if (enableOpticalBypass) {
        for (int d = 0; d < numPEs; d++) {
            if (d / numColumns != connIdx) continue;  // only this connector's PEs
            if (setupPendingByDst[d] && simTime() >= setupPendingExpiryByDst[d]) {
                int pt = pendingSetupTokenByDst[d];
                if (pt > 0 && topologyManager) topologyManager->releaseOpticalPathByToken(pt);
                setupPendingByDst[d] = 0;
                setupPendingExpiryByDst[d] = SIMTIME_ZERO;
                pendingSetupTokenByDst[d] = 0;
                nextSetupAttemptByDst[d] = simTime() + setupRetryDelay;
                // Remove stale SETUP_REQ flits from injectQ to prevent
                // interleaving with the next setup's flits. If left in the
                // queue, a stale END_FLIT could trigger an ACK that the GB
                // misattributes to the new pending setup, establishing a
                // circuit with the wrong (already-released) token.
                int dstConn = d / numColumns;
                std::queue<TaskMsg*> cleanQ;
                while (!injectQ[dstConn].empty()) {
                    TaskMsg* f = injectQ[dstConn].front();
                    injectQ[dstConn].pop();
                    if (f->getDstId() == d && f->getTaskId() == -1
                            && f->getPktId() == pt)
                        delete f;
                    else
                        cleanQ.push(f);
                }
                injectQ[dstConn] = cleanQ;
            }
        }
        for (int d = 0; d < numPEs; d++) {
            if (d / numColumns != connIdx) continue;  // only this connector's PEs
            if (pendingDataQ[d].empty()) continue;
            if (circuitReadyByDst[d] || setupPendingByDst[d]) continue;
            if (simTime() < nextSetupAttemptByDst[d]) continue;
            int setupToken = 0;
            if (tryReserveSetupPath(d, setupToken)) {
                int gbSrcId2 = baseId + (d / numColumns);
                int setupPktId2 = setupToken;
                for (int fi = 0; fi < 2; fi++) {
                    char sn[64]; snprintf(sn, sizeof(sn), "gb-retry-s%d-d%d-f%d", gbSrcId2, d, fi);
                    TaskMsg* sf = new TaskMsg(sn);
                    sf->setKind(NOC_FLIT_MSG); sf->setByteLength(flitSize); sf->setBitLength(8*flitSize);
                    sf->setVC(0); sf->setSrcId(gbSrcId2); sf->setDstId(d);
                    sf->setPktId(setupPktId2); sf->setFlitIdx(fi); sf->setFlits(2);
                    sf->setFirstNet(true); sf->setSchedulingPriority(0);
                    sf->setType(fi==0?NOC_START_FLIT:NOC_END_FLIT);
                    sf->setSL(onocEncodePacketTag(ONOC_PKT_SETUP_REQ, 0, 0));
                    sf->setTaskId(-1); sf->setProducerPE(baseId);
                    sf->setConsumerPE(d); sf->setProducerTaskId(-1);
                    sf->setDataSize(0); sf->setComputeTime(0);
                    int dstConn = d / numColumns;
                    injectQ[dstConn].push(sf);
                }
                setupPendingByDst[d] = 1;
                setupPendingExpiryByDst[d] = simTime() + setupPendingTimeout;
                pendingSetupTokenByDst[d] = setupToken;
                nextSetupAttemptByDst[d] = simTime() + setupRetryDelay;
            } else {
                nextSetupAttemptByDst[d] = simTime() + setupRetryDelay;
            }
        }
    }

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
