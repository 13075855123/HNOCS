//
// Copyright (C) 2010-2011 Eitan Zahavi, The Technion EE Department
// Copyright (C) 2010-2011 Yaniv Ben-Itzhak, The Technion EE Department
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

#include "PktFifoSrc.h"

#include <cstdlib>

#include "onoc/common/OpticalPathMetrics.h"
#include "onoc/control/LogicalTopologyManager.h"

Define_Module(PktFifoSrc);

static const int NOC_VISUAL_CLEANUP_MSG = 9101;

void PktFifoSrc::initialize() {
    credits = 0;
    pktIdx = 0;
    flitIdx = 0;
    flitSize_B = par("flitSize");
    maxQueuedPkts = par("maxQueuedPkts");
    statStartTime = par("statStartTime");
    isSynchronous = par("isSynchronous");
    enableSetupHandshake = par("enableSetupHandshake");
    singlePacketPerMessage = par("singlePacketPerMessage");
    setupControlPktLen = par("setupControlPktLen");
    dataPktLenWhenHandshake = par("dataPktLenWhenHandshake");
    setupRetryDelay = par("setupRetryDelay");
    setupPendingTimeout = par("setupPendingTimeout");
    enableOpticalBypass = par("enableOpticalBypass");
    enableTrafficVisualization = par("enableTrafficVisualization");
    visualLinkHoldTime = par("visualLinkHoldTime");
    opticalRequiredWavelengths = par("opticalRequiredWavelengths");
    opticalWavelengthBitrate = par("opticalWavelengthBitrate");
    opticalBasePropagationDelay = par("opticalBasePropagationDelay");
    opticalPerTorusHopDelay = par("opticalPerTorusHopDelay");
    opticalBurstSize = par("opticalBurstSize");

    numNodes = 0;
    numRows = 0;
    numColumns = 0;
    topologyManager = NULL;

    setupReqRxCount = 0;
    setupAckRxCount = 0;
    setupAckAcceptedCount = 0;
    setupAckStaleCount = 0;
    setupReserveFailCount = 0;
    setupPendingTimeoutCount = 0;

    setupReqEventSignal = registerSignal("onoc-setup-req-event");
    setupAckEventSignal = registerSignal("onoc-setup-ack-event");

    if (setupControlPktLen < 2) {
        throw cRuntimeError("setupControlPktLen must be >= 2 to preserve SoP/EoP semantics");
    }
    if (dataPktLenWhenHandshake < 2) {
        throw cRuntimeError("dataPktLenWhenHandshake must be >= 2 to preserve SoP/EoP semantics");
    }
    if (setupRetryDelay <= SIMTIME_ZERO) {
        throw cRuntimeError("setupRetryDelay must be > 0");
    }
    if (setupPendingTimeout <= setupRetryDelay) {
        throw cRuntimeError("setupPendingTimeout must be > setupRetryDelay");
    }
    if (visualLinkHoldTime <= SIMTIME_ZERO) {
        throw cRuntimeError("visualLinkHoldTime must be > 0");
    }

    if (enableSetupHandshake) {
        cModule *managerModule = getSystemModule()->getSubmodule("topologyManager");
        topologyManager = dynamic_cast<LogicalTopologyManager *>(managerModule);
        if (!topologyManager) {
            throw cRuntimeError("Could not find topologyManager while setup handshake is enabled");
        }

        numRows = getSystemModule()->par("rows").intValue();
        numColumns = getSystemModule()->par("columns").intValue();
        numNodes = numRows * numColumns;
        if (numNodes <= 0) {
            throw cRuntimeError("Invalid topology size while setup handshake is enabled");
        }

        circuitReadyByDst.assign(numNodes, 0);
        setupPendingByDst.assign(numNodes, 0);
        nextSetupAttemptByDst.assign(numNodes, SIMTIME_ZERO);
        setupPendingExpiryByDst.assign(numNodes, SIMTIME_ZERO);
        pendingSetupTokenByDst.assign(numNodes, 0);
        pendingSetupSpatialByDst.assign(numNodes, 0);
        pendingSetupWavelengthMaskByDst.assign(numNodes, 0);
        activeCircuitTokenByDst.assign(numNodes, 0);
        activeSpatialByDst.assign(numNodes, 0);
        activeWavelengthMaskByDst.assign(numNodes, 0);

        getSimulation()->getSystemModule()->subscribe("onoc-setup-req-event", this);
        getSimulation()->getSystemModule()->subscribe("onoc-setup-ack-event", this);
    }

    numQueuedPkts = 0;
    controlQueuedPkts = 0;
    opticalQueuedPkts = 0;
    WATCH(numQueuedPkts);
    WATCH(controlQueuedPkts);
    WATCH(opticalQueuedPkts);
    WATCH(curPktLen);

    srcId = par("srcId");
    curPktLen = 1;
    curPktId = srcId << 16;

    controlPopMsg = NULL;
    opticalPopMsg = NULL;
    numSentPackets = 0;
    numSentPkt.setName("number-sent-packets");
    numGenPackets = 0;
    numGenPkt.setName("number-generated-packets");
    totalNumQPackets = 0;
    numQPkt.setName("number-queue-packets");
    lossProb.setName("loss-probability");

    controlPacketsEnqueued = 0;
    opticalPacketsEnqueued = 0;
    controlPacketsSent = 0;
    opticalPacketsSent = 0;
    opticalBudgetViolationCount = 0;
    budgetRerouteCount = 0;

    controlQueueSize.setName("control-queue-size-percent");
    opticalQueueSize.setName("optical-queue-size-percent");
    controlQueueSizeVec.setName("control-queue-size-percent-vec");
    opticalQueueSizeVec.setName("optical-queue-size-percent-vec");
    opticalPathHopCount.setName("optical-path-hop-count");
    opticalPathWavelengthCount.setName("optical-path-wavelength-count");
    opticalPathInsertionLossDb.setName("optical-path-insertion-loss-dB");
    opticalPathCrosstalkLossDb.setName("optical-path-crosstalk-loss-dB");
    opticalPathTotalLossDb.setName("optical-path-total-loss-dB");
    opticalPathReceivedPowerDbm.setName("optical-path-received-power-dBm");
    opticalPathMarginDb.setName("optical-path-margin-dB");
    opticalPathSNRDb.setName("optical-path-snr-dB");
    opticalPathBER.setName("optical-path-ber");
    opticalPathModulatorLossDb.setName("optical-path-modulator-loss-dB");
    opticalPathMuxDemuxLossDb.setName("optical-path-mux-demux-loss-dB");
    opticalPathWaveguideLossDb.setName("optical-path-waveguide-loss-dB");
    opticalPathBendingLossDb.setName("optical-path-bending-loss-dB");
    opticalPathRingThroughLossDb.setName("optical-path-ring-through-loss-dB");
    opticalPathRingDropLossDb.setName("optical-path-ring-drop-loss-dB");
    opticalPathSOAGainDb.setName("optical-path-soa-gain-dB");
    opticalPathDetectorLossDb.setName("optical-path-detector-loss-dB");

    FullQueueIndicator.setName("Full_Queue_Indicator");
    FullQueueIndicator.collect(0);

    queueSize.setName("source-queue-size-percent");

    dstId = par("dstId");
    if (dstId < 0) {
        EV << "-I- " << getFullPath() << " is turned OFF" << endl;
    } else {
        char genMsgName[32];
        sprintf(genMsgName, "gen-%d", srcId);
        genMsg = new cMessage(genMsgName);
        scheduleAt(simTime(), genMsg);

        dstIdHist.setName("dstId-Hist");
        dstIdHist.setMode(cHistogram::MODE_INTEGERS);
        dstIdHist.setBinSizeHint(1.0);
        dstIdHist.setRange(0, NAN);
        dstIdVec.setName("dstId");

        cGate *g = gate("out$o")->getNextGate();
        if (!g->getChannel()) {
            throw cRuntimeError("-E- no out$o 0 gate for module %s ???", g->getFullPath().c_str());
        }
        cDatarateChannel *chan = check_and_cast<cDatarateChannel *>(g->getChannel());
        double data_rate = chan->getDatarate();
        tClk_s = (8 * flitSize_B) / data_rate;
        EV << "-I- " << getFullPath() << " Channel rate is:" << data_rate << " Clock is:" << tClk_s << endl;

        char controlPopMsgName[32];
        sprintf(controlPopMsgName, "control-pop-src-%d", srcId);
        controlPopMsg = new NoCPopMsg(controlPopMsgName);
        controlPopMsg->setKind(NOC_POP_MSG);
        scheduleAt(tClk_s * 0.5, controlPopMsg);

        char opticalPopMsgName[32];
        sprintf(opticalPopMsgName, "optical-pop-src-%d", srcId);
        opticalPopMsg = new NoCPopMsg(opticalPopMsgName);
        opticalPopMsg->setKind(NOC_CLK_MSG);

        curPktIdx = 0;
        curMsgLen = 0;

        isTrace = par("isTrace");
        if (isTrace) {
            FILE *traceFile;
            traceIndex = 1;
            packetArrivalDelayArraySize = 0;
            int tmp;

            for (int i = 0; i < MAXTRACESIZE; i++) {
                packetArrivalDelayArray[i] = 0;
            }

            const char *traceFileName = par("fileName").stringValue();
            traceFile = fopen(traceFileName, "r");
            if (traceFile == NULL) {
                throw cRuntimeError("Error opening output file");
            }

            while ((fscanf(traceFile, "%u\n", &tmp) != EOF) && (packetArrivalDelayArraySize < MAXTRACESIZE)) {
                packetArrivalDelayArray[packetArrivalDelayArraySize] = 1e-9 * tmp;
                packetArrivalDelayArraySize++;
            }
        }
    }
}

void PktFifoSrc::sendControlFlitFromQ() {
    if (controlQ.isEmpty() || (credits <= 0))
        return;
    if (!isSynchronous && controlPopMsg->isScheduled())
        return;

    NoCFlitMsg *flit = (NoCFlitMsg *)controlQ.pop();
    int packetClass = onocGetPacketClass(flit->getSL());
    bool dataOnControlPath = (packetClass == ONOC_PKT_DATA);

    if (flit->getType() == NOC_END_FLIT) {
        if (packetClass != ONOC_PKT_SETUP_ACK) {
            numQueuedPkts--;
        }
        controlQueuedPkts--;
        controlPacketsSent++;
        if (dataOnControlPath) {
            numSentPackets++;
        }
    }

    flit->setInjectTime(simTime());

    if (packetClass == ONOC_PKT_SETUP_REQ || packetClass == ONOC_PKT_SETUP_ACK || dataOnControlPath) {
        drawTransientTrafficLine(flit->getDstId(), false);
    }

    send(flit, "out$o");
    credits--;

    if (!isSynchronous) {
        simtime_t txFinishTime = gate("out$o")->getTransmissionChannel()->getTransmissionFinishTime();
        if (txFinishTime < simTime()) {
            throw cRuntimeError("-E- BUG - We just sent - must be busy!");
        }
        scheduleAt(txFinishTime, controlPopMsg);
    }

    recordQueueStats();
}

void PktFifoSrc::sendOpticalFlitFromQ() {
    if (opticalQ.isEmpty())
        return;
    if (!isSynchronous && opticalPopMsg->isScheduled())
        return;

    NoCFlitMsg *flit = (NoCFlitMsg *)opticalQ.pop();
    int packetClass = onocGetPacketClass(flit->getSL());
    if (packetClass != ONOC_PKT_DATA) {
        throw cRuntimeError("Optical queue received non-data packet class %d", packetClass);
    }

    if (flit->getType() == NOC_END_FLIT) {
        numQueuedPkts--;
        opticalQueuedPkts--;
        opticalPacketsSent++;
        numSentPackets++;
    }

    flit->setInjectTime(simTime());
    drawTransientTrafficLine(flit->getDstId(), true);

    if (!sendFlitDirectToSink(flit)) {
        throw cRuntimeError("Failed to send optical bypass flit from %d to %d", flit->getSrcId(), flit->getDstId());
    }

    simtime_t txFinishTime = simTime() + computeOpticalTxDuration(flit);
    scheduleAt(txFinishTime, opticalPopMsg);

    recordQueueStats();
}

cSimpleModule *PktFifoSrc::getDestinationSinkModule(int dst) const {
    cModule *coreModule = getSystemModule()->getSubmodule("core", dst);
    if (!coreModule) {
        throw cRuntimeError("Could not locate core[%d] for optical bypass", dst);
    }
    cModule *sinkModule = coreModule->getSubmodule("sink");
    if (!sinkModule) {
        throw cRuntimeError("Could not locate sink submodule for core[%d]", dst);
    }
    return check_and_cast<cSimpleModule *>(sinkModule);
}

int PktFifoSrc::meshHopDistance(int src, int dst) const {
    if (numRows <= 0 || numColumns <= 0) {
        return 0;
    }
    int srcRow = src / numColumns;
    int srcCol = src % numColumns;
    int dstRow = dst / numColumns;
    int dstCol = dst % numColumns;
    int rowDelta = abs(srcRow - dstRow);
    int colDelta = abs(srcCol - dstCol);
    return rowDelta + colDelta;
}

int PktFifoSrc::countSetBits(int value) const {
    int count = 0;
    while (value != 0) {
        count += value & 1;
        value >>= 1;
    }
    return count;
}

simtime_t PktFifoSrc::computeOpticalPropagationDelay(int src, int dst) const {
    int hopCount = meshHopDistance(src, dst);
    return opticalBasePropagationDelay + (opticalPerTorusHopDelay * hopCount);
}

simtime_t PktFifoSrc::computeOpticalTxDuration(const NoCFlitMsg *flit) const {
    if (!flit) {
        return SIMTIME_ZERO;
    }
    int wavelengthMask = 0;
    int packetClass = 0;
    int spatialChannel = 0;
    onocDecodePacketTag(flit->getSL(), packetClass, spatialChannel, wavelengthMask);
    (void)packetClass;
    (void)spatialChannel;
    int wavelengthCount = countSetBits(wavelengthMask);
    if (wavelengthCount < opticalRequiredWavelengths) {
        wavelengthCount = opticalRequiredWavelengths;
    }
    if (wavelengthCount <= 0) {
        wavelengthCount = opticalRequiredWavelengths > 0 ? opticalRequiredWavelengths : 1;
    }
    double effectiveRate = opticalWavelengthBitrate * wavelengthCount;
    double txSeconds = (8.0 * flit->getByteLength()) / effectiveRate;
    int64_t txPicoseconds = static_cast<int64_t>(txSeconds * 1.0e12 + 0.5);
    if (txPicoseconds < 1) {
        txPicoseconds = 1;
    }
    return SimTime(txPicoseconds, SIMTIME_PS);
}

bool PktFifoSrc::sendFlitDirectToSink(NoCFlitMsg *flit) {
    if (!flit) {
        return false;
    }
    cSimpleModule *sinkModule = getDestinationSinkModule(flit->getDstId());
    flit->setFirstNet(false);
    flit->setFirstNetTime(simTime());

    if (enableSetupHandshake && enableOpticalBypass && topologyManager && flit->getControlInfo() == nullptr) {
        OpticalPathMetrics *metrics = new OpticalPathMetrics();
        if (topologyManager->getOpticalPathMetrics(flit->getPktId(), *metrics)) {
            flit->setControlInfo(metrics);
        } else {
            delete metrics;
        }
    }

    simtime_t propDelay = computeOpticalPropagationDelay(flit->getSrcId(), flit->getDstId());
    simtime_t txDuration = computeOpticalTxDuration(flit);
    sendDirect(flit, propDelay, txDuration, sinkModule->gate("opticalIn"));
    return true;
}

void PktFifoSrc::applyFlitVisualStyle(NoCFlitMsg *flit, int packetClass, bool opticalQueue) const {
    if (!flit) {
        return;
    }

    const char *fillColor = "grey";
    switch (packetClass) {
        case ONOC_PKT_SETUP_REQ:
            fillColor = "blue";
            break;
        case ONOC_PKT_SETUP_ACK:
            fillColor = "orange";
            break;
        case ONOC_PKT_DATA:
            fillColor = opticalQueue ? "yellow" : "green";
            break;
        default:
            break;
    }

    // display string not supported in OMNeT++ 6.x for cMessage
}

void PktFifoSrc::drawTransientTrafficLine(int dstNodeId, bool opticalData) {
    if (!enableTrafficVisualization) {
        return;
    }
    if (getEnvir()->isExpressMode()) {
        return;
    }
    cModule *sys = getSystemModule();
    if (!sys || !sys->getCanvas()) {
        return;
    }

    cModule *srcCore = getParentModule();
    cModule *dstCore = sys->getSubmodule("core", dstNodeId);
    if (!srcCore || !dstCore) {
        return;
    }

    const char *sx = srcCore->getDisplayString().getTagArg("p", 0);
    const char *sy = srcCore->getDisplayString().getTagArg("p", 1);
    const char *dx = dstCore->getDisplayString().getTagArg("p", 0);
    const char *dy = dstCore->getDisplayString().getTagArg("p", 1);
    if (!sx || !sy || !dx || !dy) {
        return;
    }

    double srcX = atof(sx);
    double srcY = atof(sy);
    double dstX = atof(dx);
    double dstY = atof(dy);

    char figureName[128];
    sprintf(figureName, "traffic-%d-%d-%lld", srcId, dstNodeId, (long long)simTime().raw());

    cLineFigure *line = new cLineFigure(figureName);
    line->setStart(cFigure::Point(srcX, srcY));
    line->setEnd(cFigure::Point(dstX, dstY));
    line->setLineWidth(2);
    line->setZoomLineWidth(false);
    if (opticalData) {
        line->setLineColor(cFigure::Color("yellow"));
    } else {
        line->setLineColor(cFigure::Color("green"));
    }
    sys->getCanvas()->addFigure(line);

    cMessage *cleanupMsg = new cMessage("visual-cleanup", NOC_VISUAL_CLEANUP_MSG);
    visualLinkCleanup[cleanupMsg] = line;
    scheduleAt(simTime() + visualLinkHoldTime, cleanupMsg);
}

void PktFifoSrc::handleVisualCleanup(cMessage *msg) {
    std::map<cMessage *, cFigure *>::iterator it = visualLinkCleanup.find(msg);
    if (it != visualLinkCleanup.end()) {
        cFigure *figure = it->second;
        if (figure && getSystemModule() && getSystemModule()->getCanvas()) {
            getSystemModule()->getCanvas()->removeFigure(figure);
        }
        delete figure;
        visualLinkCleanup.erase(it);
    }
    delete msg;
}

void PktFifoSrc::ensureDstStateSize(int dst) {
    if (!enableSetupHandshake) {
        return;
    }
    if (dst < 0 || dst >= numNodes) {
        throw cRuntimeError("Destination %d out of range [0,%d)", dst, numNodes);
    }
}

bool PktFifoSrc::enqueuePacket(int dst,
        int pktLen,
        int vc,
        int packetClass,
        int spatialChannel,
        int wavelengthMask,
        int circuitToken,
        const char *namePrefix) {
    if (pktLen < 2) {
        throw cRuntimeError("pktLen must be >= 2, got %d", pktLen);
    }

    pktIdx++;
    curPktId = (srcId << 16) + pktIdx;
    if (circuitToken > 0) {
        curPktId = circuitToken;
    }

    int packetTag = onocEncodePacketTag(packetClass, spatialChannel, wavelengthMask);
    bool opticalQueue = enableOpticalBypass && enableSetupHandshake && packetClass == ONOC_PKT_DATA;
    cQueue *queue = opticalQueue ? &opticalQ : &controlQ;

    OpticalPathMetrics opticalPathMetrics;
    bool haveOpticalPathMetrics = false;
    if (opticalQueue && topologyManager && circuitToken > 0) {
        haveOpticalPathMetrics = topologyManager->getOpticalPathMetrics(circuitToken, opticalPathMetrics);
        if (haveOpticalPathMetrics) {
            opticalPathHopCount.collect(opticalPathMetrics.hopCount);
            opticalPathWavelengthCount.collect(opticalPathMetrics.wavelengthCount);
            opticalPathInsertionLossDb.collect(opticalPathMetrics.hopInsertionLoss_dB + opticalPathMetrics.sourceModulatorLoss_dB + opticalPathMetrics.receiverDemodulatorLoss_dB);
            opticalPathCrosstalkLossDb.collect(opticalPathMetrics.hopCrosstalkLoss_dB);
            opticalPathTotalLossDb.collect(opticalPathMetrics.totalLoss_dB);
            opticalPathReceivedPowerDbm.collect(opticalPathMetrics.receivedPower_dBm);
            opticalPathMarginDb.collect(opticalPathMetrics.signalMargin_dB);

            // Device-level statistics
            opticalPathSNRDb.collect(opticalPathMetrics.estimatedSNR_dB);
            opticalPathBER.collect(opticalPathMetrics.estimatedBER);
            opticalPathModulatorLossDb.collect(opticalPathMetrics.modulatorLoss_dB);
            opticalPathMuxDemuxLossDb.collect(opticalPathMetrics.muxDemuxLoss_dB);
            opticalPathWaveguideLossDb.collect(opticalPathMetrics.waveguidePropagationLoss_dB);
            opticalPathBendingLossDb.collect(opticalPathMetrics.waveguideBendingLoss_dB);
            opticalPathRingThroughLossDb.collect(opticalPathMetrics.ringThroughLoss_dB);
            opticalPathRingDropLossDb.collect(opticalPathMetrics.ringDropLoss_dB);
            opticalPathSOAGainDb.collect(opticalPathMetrics.soaGainTotal_dB);
            opticalPathDetectorLossDb.collect(opticalPathMetrics.detectorLoss_dB);

            if (!opticalPathMetrics.meetsSensitivity) {
                opticalBudgetViolationCount++;
                EV_WARN << "Optical path budget violation for pkt=" << circuitToken
                        << " src=" << srcId
                        << " dst=" << dst
                        << " rxPower=" << opticalPathMetrics.receivedPower_dBm
                        << "dBm sensitivity=" << opticalPathMetrics.receiverSensitivity_dBm
                        << "dBm margin=" << opticalPathMetrics.signalMargin_dB
                        << "dB SNR=" << opticalPathMetrics.estimatedSNR_dB
                        << "dB BER=" << opticalPathMetrics.estimatedBER
                        << endl;
            }

            // Budget-driven reroute check
            if (opticalPathMetrics.budgetRerouteTriggered) {
                budgetRerouteCount++;
                EV_WARN << "Budget-driven reroute triggered for pkt=" << circuitToken
                        << " src=" << srcId << " dst=" << dst
                        << " margin=" << opticalPathMetrics.signalMargin_dB
                        << "dB BER=" << opticalPathMetrics.estimatedBER
                        << endl;
            }
        }
    }

    for (flitIdx = 0; flitIdx < pktLen; flitIdx++) {
        char flitName[128];
        sprintf(flitName, "%s-s:%d-t:%d-p:%d-f:%d", namePrefix, srcId, dst, pktIdx, flitIdx);
        NoCFlitMsg *flit = new NoCFlitMsg(flitName);
        flit->setKind(NOC_FLIT_MSG);
        flit->setByteLength(flitSize_B);
        flit->setBitLength(8 * flitSize_B);
        flit->setVC(vc);
        flit->setSL(packetTag);
        flit->setSrcId(srcId);
        flit->setDstId(dst);
        flit->setPktId(curPktId);
        flit->setFlitIdx(flitIdx);
        flit->setSchedulingPriority(0);
        flit->setFirstNet(true);
        flit->setFlits(pktLen);

        if (flitIdx == 0) {
            flit->setType(NOC_START_FLIT);
        } else if (flitIdx == pktLen - 1) {
            flit->setType(NOC_END_FLIT);
        } else {
            flit->setType(NOC_MID_FLIT);
        }
        if (haveOpticalPathMetrics) {
            flit->setControlInfo(opticalPathMetrics.dup());
        }
        applyFlitVisualStyle(flit, packetClass, opticalQueue);
        queue->insert(flit);
    }

    if (packetClass == ONOC_PKT_SETUP_ACK) {
        controlQueuedPkts++;
        controlPacketsEnqueued++;
    } else if (opticalQueue) {
        numQueuedPkts++;
        opticalQueuedPkts++;
        opticalPacketsEnqueued++;
    } else {
        numQueuedPkts++;
        controlQueuedPkts++;
        controlPacketsEnqueued++;
    }

    recordQueueStats();
    return opticalQueue;
}

void PktFifoSrc::recordQueueStats() {
    if (simTime() <= statStartTime) {
        return;
    }

    double totalPercent = 0;
    double controlPercent = 0;
    double opticalPercent = 0;
    if (maxQueuedPkts > 0) {
        totalPercent = 1.0 * numQueuedPkts / maxQueuedPkts;
        controlPercent = 1.0 * controlQueuedPkts / maxQueuedPkts;
        opticalPercent = 1.0 * opticalQueuedPkts / maxQueuedPkts;
    }

    queueSize.collect(totalPercent);
    controlQueueSize.collect(controlPercent);
    opticalQueueSize.collect(opticalPercent);
    controlQueueSizeVec.record(controlPercent);
    opticalQueueSizeVec.record(opticalPercent);
}

bool PktFifoSrc::tryReserveSetupPath(int dst, int &token, int &spatialChannel, int &wavelengthMask) {
    token = 0;
    spatialChannel = 0;
    wavelengthMask = 0;

    if (!enableSetupHandshake || !topologyManager) {
        return false;
    }

    bool insufficientResources = false;
    std::string failureReason;
    bool reserved = topologyManager->reserveOpticalPathForSetup(srcId,
            dst,
            token,
            spatialChannel,
            wavelengthMask,
            insufficientResources,
            failureReason);
    if (!reserved) {
        if (insufficientResources) {
            EV_WARN << "Setup path reservation failed (resource shortage) for "
                    << srcId << "->" << dst << ": " << failureReason << endl;
        } else {
            EV_WARN << "Setup path reservation failed for "
                    << srcId << "->" << dst << ": " << failureReason << endl;
        }
        return false;
    }

    if (token <= 0 || wavelengthMask == 0) {
        EV_WARN << "Setup reservation returned invalid token/mask for "
                << srcId << "->" << dst << endl;
        return false;
    }

    return true;
}

void PktFifoSrc::handleGenMsg(cMessage *msg) {
    if (curPktIdx == curMsgLen) {
        curMsgLen = par("msgLen");
        if (singlePacketPerMessage) {
            curMsgLen = 1;
        }
        if (curMsgLen <= 0) {
            throw cRuntimeError("-E- can not handle <= 0 packets message");
        }
        curPktIdx = 0;
        dstId = par("dstId");
        curPktLen = par("pktLen");
    }

    curPktVC = par("pktVC");
    int dataPktLen = curPktLen;
    if (enableSetupHandshake) {
        ensureDstStateSize(dstId);
        dataPktLen = dataPktLenWhenHandshake;

        if (setupPendingByDst[dstId] && simTime() >= setupPendingExpiryByDst[dstId]) {
            setupPendingTimeoutCount++;
            int pendingToken = pendingSetupTokenByDst[dstId];
            if (pendingToken > 0 && topologyManager) {
                topologyManager->releaseOpticalPathByToken(pendingToken);
            }
            setupPendingByDst[dstId] = 0;
            setupPendingExpiryByDst[dstId] = SIMTIME_ZERO;
            pendingSetupTokenByDst[dstId] = 0;
            pendingSetupSpatialByDst[dstId] = 0;
            pendingSetupWavelengthMaskByDst[dstId] = 0;
            nextSetupAttemptByDst[dstId] = simTime();
        }

        if (!circuitReadyByDst[dstId]) {
            if (!setupPendingByDst[dstId] && simTime() >= nextSetupAttemptByDst[dstId]) {
                if (numQueuedPkts < maxQueuedPkts) {
                    int setupToken = 0;
                    int setupSpatial = 0;
                    int setupWavelengthMask = 0;
                    if (tryReserveSetupPath(dstId, setupToken, setupSpatial, setupWavelengthMask)) {
                        enqueuePacket(dstId,
                                setupControlPktLen,
                                curPktVC,
                                ONOC_PKT_SETUP_REQ,
                                setupSpatial,
                                setupWavelengthMask,
                                setupToken,
                                "setup");
                        setupPendingByDst[dstId] = 1;
                        setupPendingExpiryByDst[dstId] = simTime() + setupPendingTimeout;
                        pendingSetupTokenByDst[dstId] = setupToken;
                        pendingSetupSpatialByDst[dstId] = setupSpatial;
                        pendingSetupWavelengthMaskByDst[dstId] = setupWavelengthMask;
                        nextSetupAttemptByDst[dstId] = simTime() + setupRetryDelay;
                        if (!isSynchronous) {
                            sendControlFlitFromQ();
                        }
                    } else {
                        setupReserveFailCount++;
                        nextSetupAttemptByDst[dstId] = simTime() + setupRetryDelay;
                    }
                } else if (simTime() > statStartTime) {
                    FullQueueIndicator.collect(1);
                }
            }
            recordQueueStats();
            scheduleAt(simTime() + setupRetryDelay, genMsg);
            return;
        }
    }

    numGenPackets++;
    if (numQueuedPkts < maxQueuedPkts) {
        totalNumQPackets++;
        dstIdHist.collect(dstId);
        dstIdVec.record(dstId);

        int packetSpatialChannel = 0;
        int packetWavelengthMask = 0;
        int packetCircuitToken = 0;
        if (enableSetupHandshake) {
            ensureDstStateSize(dstId);
            packetSpatialChannel = activeSpatialByDst[dstId];
            packetWavelengthMask = activeWavelengthMaskByDst[dstId];
            packetCircuitToken = activeCircuitTokenByDst[dstId];
        }

        // ── Burst mode: enqueue burstSize data packets on the open circuit ──
        int burstSize = (enableSetupHandshake && circuitReadyByDst[dstId])
                ? opticalBurstSize : 1;
        if (burstSize < 1) burstSize = 1;

        for (int b = 0; b < burstSize; b++) {
            if (numQueuedPkts >= maxQueuedPkts) break;
            if (b > 0) {
                numGenPackets++;
                totalNumQPackets++;
                dstIdHist.collect(dstId);
                dstIdVec.record(dstId);
            }
            enqueuePacket(dstId,
                    dataPktLen,
                    curPktVC,
                    ONOC_PKT_DATA,
                    packetSpatialChannel,
                    packetWavelengthMask,
                    packetCircuitToken,
                    "flit");
        }

        if (enableSetupHandshake) {
            circuitReadyByDst[dstId] = 0;
            setupPendingByDst[dstId] = 0;
            setupPendingExpiryByDst[dstId] = SIMTIME_ZERO;
            pendingSetupTokenByDst[dstId] = 0;
            pendingSetupSpatialByDst[dstId] = 0;
            pendingSetupWavelengthMaskByDst[dstId] = 0;
            activeCircuitTokenByDst[dstId] = 0;
            activeSpatialByDst[dstId] = 0;
            activeWavelengthMaskByDst[dstId] = 0;
        }

        curPktIdx++;
        if (!isSynchronous) {
            if (enableSetupHandshake && enableOpticalBypass) {
                sendOpticalFlitFromQ();
            } else {
                sendControlFlitFromQ();
            }
        }
    } else {
        if (simTime() > statStartTime) {
            FullQueueIndicator.collect(1);
        }
    }

    recordQueueStats();

    if (isTrace) {
        scheduleAt(simTime() + packetArrivalDelayArray[traceIndex % (packetArrivalDelayArraySize - 1)], genMsg);
        traceIndex++;
    } else {
        double flitArrivalDelay = par("flitArrivalDelay");
        scheduleAt(simTime() + dataPktLen * flitArrivalDelay, genMsg);
    }
}

void PktFifoSrc::handleControlEvent(int eventType,
        int requesterId,
        int targetId,
        int token,
        int spatialChannel,
        int wavelengthMask) {
    if (!enableSetupHandshake) {
        return;
    }

    if (eventType == ONOC_EVT_SETUP_REQ) {
        if (targetId != srcId) {
            return;
        }
        setupReqRxCount++;

        if (requesterId < 0 || requesterId >= numNodes) {
            if (topologyManager && token > 0) {
                topologyManager->releaseOpticalPathByToken(token);
            }
            return;
        }

        enqueuePacket(requesterId,
                setupControlPktLen,
                par("pktVC").intValue(),
                ONOC_PKT_SETUP_ACK,
                spatialChannel,
                wavelengthMask,
                token,
                "ack");
        if (!isSynchronous) {
            sendControlFlitFromQ();
        }
        return;
    }

    if (eventType == ONOC_EVT_SETUP_ACK) {
        if (requesterId != srcId) {
            return;
        }
        setupAckRxCount++;

        ensureDstStateSize(targetId);
        int pendingToken = pendingSetupTokenByDst[targetId];
        if (!setupPendingByDst[targetId]) {
            setupAckStaleCount++;
            if (topologyManager && token > 0) {
                topologyManager->releaseOpticalPathByToken(token);
            }
            return;
        }
        if (pendingToken > 0 && token != pendingToken) {
            setupAckStaleCount++;
            if (topologyManager) {
                topologyManager->releaseOpticalPathByToken(token);
            }
            return;
        }

        setupAckAcceptedCount++;
        circuitReadyByDst[targetId] = 1;
        setupPendingByDst[targetId] = 0;
        setupPendingExpiryByDst[targetId] = SIMTIME_ZERO;
        pendingSetupTokenByDst[targetId] = 0;
        pendingSetupSpatialByDst[targetId] = 0;
        pendingSetupWavelengthMaskByDst[targetId] = 0;
        activeCircuitTokenByDst[targetId] = token;
        activeSpatialByDst[targetId] = spatialChannel;
        activeWavelengthMaskByDst[targetId] = wavelengthMask;
    }
}

void PktFifoSrc::receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details) {
    (void)source;
    (void)details;
    Enter_Method_Silent("PktFifoSrc::receiveSignal()");

    if (!enableSetupHandshake) {
        return;
    }

    if (signalID != setupReqEventSignal && signalID != setupAckEventSignal) {
        return;
    }

    int eventType = 0;
    int requesterId = -1;
    int targetId = -1;
    int token = 0;
    int spatialChannel = 0;
    int wavelengthMask = 0;
    onocDecodeControlEvent(value, eventType, requesterId, targetId, token, spatialChannel, wavelengthMask);
    handleControlEvent(eventType, requesterId, targetId, token, spatialChannel, wavelengthMask);
}

void PktFifoSrc::handleCreditMsg(NoCCreditMsg *msg) {
    int vc = msg->getVC();
    int flits = msg->getFlits();
    delete msg;
    if (vc == 0) {
        credits += flits;
    }
    if (!isSynchronous)
        sendControlFlitFromQ();
}

void PktFifoSrc::handleControlPopMsg(cMessage *msg) {
    sendControlFlitFromQ();
    if (isSynchronous)
        scheduleAt(simTime() + tClk_s, msg);
}

void PktFifoSrc::handleOpticalPopMsg(cMessage *msg) {
    sendOpticalFlitFromQ();
    (void)msg;
}

void PktFifoSrc::handleMessage(cMessage *msg) {
    int msgType = msg->getKind();
    if (msgType == NOC_VISUAL_CLEANUP_MSG) {
        handleVisualCleanup(msg);
        return;
    }
    if (msgType == NOC_POP_MSG) {
        handleControlPopMsg((NoCPopMsg *)msg);
    } else if (msgType == NOC_CLK_MSG) {
        handleOpticalPopMsg((NoCPopMsg *)msg);
    } else if (msgType == NOC_CREDIT_MSG) {
        handleCreditMsg((NoCCreditMsg *)msg);
    } else {
        handleGenMsg(msg);
    }
}

void PktFifoSrc::finish() {
    if (enableSetupHandshake) {
        getSimulation()->getSystemModule()->unsubscribe(setupReqEventSignal, this);
        getSimulation()->getSystemModule()->unsubscribe(setupAckEventSignal, this);
    }

    dstIdHist.record();
    FullQueueIndicator.record();
    numSentPkt.collect(numSentPackets);
    numSentPkt.record();
    numGenPkt.collect(numGenPackets);
    numGenPkt.record();
    numQPkt.collect(totalNumQPackets);
    numQPkt.record();
    queueSize.record();
    controlQueueSize.record();
    opticalQueueSize.record();

    recordScalar("setup-req-rx", static_cast<double>(setupReqRxCount));
    recordScalar("setup-ack-rx", static_cast<double>(setupAckRxCount));
    recordScalar("setup-ack-accepted", static_cast<double>(setupAckAcceptedCount));
    recordScalar("setup-ack-stale", static_cast<double>(setupAckStaleCount));
    recordScalar("setup-reserve-fail", static_cast<double>(setupReserveFailCount));
    recordScalar("setup-pending-timeout", static_cast<double>(setupPendingTimeoutCount));
    recordScalar("control-packets-enqueued", static_cast<double>(controlPacketsEnqueued));
    recordScalar("optical-packets-enqueued", static_cast<double>(opticalPacketsEnqueued));
    recordScalar("control-packets-sent", static_cast<double>(controlPacketsSent));
    recordScalar("optical-packets-sent", static_cast<double>(opticalPacketsSent));
    recordScalar("control-queued-packets", static_cast<double>(controlQueuedPkts));
    recordScalar("optical-queued-packets", static_cast<double>(opticalQueuedPkts));
    recordScalar("optical-budget-violation-count", static_cast<double>(opticalBudgetViolationCount));

    opticalPathHopCount.record();
    opticalPathWavelengthCount.record();
    opticalPathInsertionLossDb.record();
    opticalPathCrosstalkLossDb.record();
    opticalPathTotalLossDb.record();
    opticalPathReceivedPowerDbm.record();
    opticalPathMarginDb.record();
    opticalPathSNRDb.record();
    opticalPathBER.record();
    opticalPathModulatorLossDb.record();
    opticalPathMuxDemuxLossDb.record();
    opticalPathWaveguideLossDb.record();
    opticalPathBendingLossDb.record();
    opticalPathRingThroughLossDb.record();
    opticalPathRingDropLossDb.record();
    opticalPathSOAGainDb.record();
    opticalPathDetectorLossDb.record();
    recordScalar("optical-budget-reroute-count", static_cast<double>(budgetRerouteCount));

    if (numGenPackets != 0) {
        lossProb.collect(1 - (totalNumQPackets / numGenPackets));
    } else {
        lossProb.collect(-1);
    }
    lossProb.record();
}

PktFifoSrc::~PktFifoSrc() {
    int configuredDstId = par("dstId");

    if (controlPopMsg) {
        cancelAndDelete(controlPopMsg);
    }

    if (opticalPopMsg) {
        cancelAndDelete(opticalPopMsg);
    }

    if (configuredDstId >= 0 && genMsg) {
        cancelAndDelete(genMsg);
    }

    while (!controlQ.isEmpty()) {
        NoCFlitMsg *flit = (NoCFlitMsg *)controlQ.pop();
        delete flit;
    }

    while (!opticalQ.isEmpty()) {
        NoCFlitMsg *flit = (NoCFlitMsg *)opticalQ.pop();
        delete flit;
    }

    for (std::map<cMessage *, cFigure *>::iterator it = visualLinkCleanup.begin(); it != visualLinkCleanup.end(); ++it) {
        if (it->first) {
            cancelAndDelete(it->first);
        }
        if (it->second) {
            delete it->second;
        }
    }
    visualLinkCleanup.clear();
}
