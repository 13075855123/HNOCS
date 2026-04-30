#include "InPortSync.h"
#include "thermal/ThermalTrace.h"   // NEW

Define_Module(InPortSync);

// NEW
void InPortSync::finalizeEnergyWindow(simtime_t now) {
    if (now <= statStartTime) {
        windowBufferWriteCount = 0;
        windowBufferReadCount = 0;
        windowCrossbarTraversal = 0;
        windowEnergyJ = 0.0;
        return;
    }

    windowEnergyJ =
        windowBufferWriteCount * eBufferWrite +
        windowBufferReadCount  * eBufferRead +
        windowCrossbarTraversal * eCrossbar +
        pLeak * energyWindow.dbl();

    totalEnergyJ += windowEnergyJ;

    windowEnergyVec.record(windowEnergyJ);
    cumulativeEnergyVec.record(totalEnergyJ);

    double windowAvgPower = 0.0;   // NEW
    if (energyWindow.dbl() > 0) {
        windowAvgPower = windowEnergyJ / energyWindow.dbl();
        windowAvgPowerVec.record(windowAvgPower);
    } else {
        windowAvgPowerVec.record(0.0);
    }

    // NEW: only one inPort per router submits aggregated router power
    // owner = router[x].port[0].inPort
    if (thermalAggregationOwner) {
        cModule* portMod = getParentModule();                 // port[i]
        cModule* routerMod = portMod ? portMod->getParentModule() : nullptr; // router[r]

        if (routerMod) {
            double routerWindowEnergy = 0.0;

            for (cModule::SubmoduleIterator it(routerMod); !it.end(); ++it) {
                cModule* sub = *it;
                if (strcmp(sub->getName(), "port") == 0) {
                    cModule* inPortMod = sub->getSubmodule("inPort");
                    if (inPortMod) {
                        InPortSync* ip = dynamic_cast<InPortSync*>(inPortMod);
                        if (ip) {
                            routerWindowEnergy += ip->windowEnergyJ;
                        }
                    }
                }
            }

            double routerAvgPower = 0.0;
            if (energyWindow.dbl() > 0) {
                routerAvgPower = routerWindowEnergy / energyWindow.dbl();
            }

            int routerId = routerMod->getIndex();
            getThermalTraceWriter()->submitRouterPower(routerId, now, routerAvgPower);

            EV << "-I- " << getFullPath()
               << " ROUTER-THERMAL-SUBMIT"
               << " routerId=" << routerId
               << " routerWindowEnergy=" << routerWindowEnergy
               << " routerAvgPower=" << routerAvgPower
               << " at " << now
               << endl;
        }
    }

    EV << "-I- " << getFullPath()
       << " ENERGY-WINDOW"
       << " at " << now
       << " windowEnergyJ=" << windowEnergyJ
       << " totalEnergyJ=" << totalEnergyJ
       << " windowBufferWriteCount=" << windowBufferWriteCount
       << " windowBufferReadCount=" << windowBufferReadCount
       << " windowCrossbarTraversal=" << windowCrossbarTraversal
       << endl;

    windowBufferWriteCount = 0;
    windowBufferReadCount = 0;
    windowCrossbarTraversal = 0;
    windowEnergyJ = 0.0;
}

void InPortSync::initialize() {
    numVCs = par("numVCs");
    flitsPerVC = par("flitsPerVC");
    collectPerHopWait = par("collectPerHopWait");
    int rows = par("rows");
    int columns = par("columns");
    statStartTime = par("statStartTime");

    // NEW
    energyWindow = par("energyWindow");
    eBufferWrite = par("eBufferWrite");
    eBufferRead  = par("eBufferRead");
    eCrossbar    = par("eCrossbar");
    pLeak        = par("pLeak");

    QByiVC.resize(numVCs);
    curOutPort.resize(numVCs);
    curOutVC.resize(numVCs);
    curPktId.resize(numVCs, 0);

    for (int vc = 0; vc < numVCs; vc++)
        sendCredit(vc, flitsPerVC);

    QLenVec.setName("Inport_total_Queue_Length");

    bufferWriteCount = 0;
    bufferReadCount = 0;
    crossbarTraversal = 0;

    // NEW
    windowBufferWriteCount = 0;
    windowBufferReadCount = 0;
    windowCrossbarTraversal = 0;
    windowEnergyJ = 0.0;
    totalEnergyJ = 0.0;

    windowEnergyVec.setName("router-window-energy");
    cumulativeEnergyVec.setName("router-cumulative-energy");
    windowAvgPowerVec.setName("router-window-avg-power");

    energyWindowMsg = new cMessage("energyWindow");
    scheduleAt(simTime() + energyWindow, energyWindowMsg);

    if (collectPerHopWait) {
        qTimeBySrcDst_head_flit.resize(rows * columns);
        qTimeBySrcDst_body_flits.resize(rows * columns);
        for (int src = 0; src < rows * columns; src++) {
            qTimeBySrcDst_head_flit[src].resize(rows * columns);
            qTimeBySrcDst_body_flits[src].resize(rows * columns);
            for (int dst = 0; dst < rows * columns; dst++) {
                char str[64];
                char str1[64];
                sprintf(str, "%d_to_%d VC acquisition time", src, dst);
                sprintf(str1, "%d_to_%d transmission time", src, dst);
                qTimeBySrcDst_head_flit[src][dst].setName(str);
                qTimeBySrcDst_body_flits[src][dst].setName(str1);
            }
        }
    }

    // NEW: only port[0].inPort submits aggregated router power
    thermalAggregationOwner = false;
    cModule* portMod = getParentModule();
    if (portMod && strcmp(portMod->getName(), "port") == 0) {
        thermalAggregationOwner = (portMod->getIndex() == 0);
    }
}

inPortFlitInfo* InPortSync::getFlitInfo(NoCFlitMsg *msg) {
    cObject *obj = msg->getControlInfo();
    if (obj == NULL) {
        throw cRuntimeError("-E- %s BUG - No Control Info for FLIT: %s",
                getFullPath().c_str(), msg->getFullName());
    }

    inPortFlitInfo *info = dynamic_cast<inPortFlitInfo*> (obj);
    return info;
}

void InPortSync::sendCredit(int vc, int numFlits) {
    if (gate("in$o")->getPathEndGate()->getType() != cGate::INPUT) {
        return;
    }
    EV<< "-I- " << getFullPath() << " sending " << numFlits
       << " credits on VC=" << vc << endl;

    char credName[64];
    sprintf(credName, "cred-%d-%d", vc, numFlits);
    NoCCreditMsg *crd = new NoCCreditMsg(credName);
    crd->setKind(NOC_CREDIT_MSG);
    crd->setVC(vc);
    crd->setFlits(numFlits);
    crd->setSchedulingPriority(0);
    send(crd, "in$o");
}

void InPortSync::sendReq(NoCFlitMsg *msg) {
    inPortFlitInfo *info = getFlitInfo(msg);
    int outPort = info->outPort;
    int inVC = info->inVC;
    int outVC = msg->getVC();

    if (msg->getType() != NOC_START_FLIT) {
        throw cRuntimeError("SendReq for flit which isn`t SoP");
    }

    EV<< "-I- " << getFullPath() << " sending Req through outPort:" << outPort
       << " on VC: " << outVC << endl;

    char reqName[64];
    sprintf(reqName, "req-s:%d-d:%d-p:%d-f:%d", (msg->getPktId() >> 16), msg->getDstId(),
            (msg->getPktId() % (1<< 16)), msg->getFlitIdx());
    NoCReqMsg *req = new NoCReqMsg(reqName);
    req->setKind(NOC_REQ_MSG);
    req->setOutPortNum(outPort);
    req->setOutVC(outVC);
    req->setInVC(inVC);
    req->setPktId(msg->getPktId());
    req->setNumFlits(msg->getFlits());
    req->setNumGranted(0);
    req->setNumAcked(0);
    req->setSchedulingPriority(0);
    send(req, "ctrl$o", outPort);
}

void InPortSync::sendFlit(NoCFlitMsg *msg) {
    int inVC = getFlitInfo(msg)->inVC;
    int outPort = getFlitInfo(msg)->outPort;

    if (gate("out", outPort)->getTransmissionChannel()->isBusy()) {
        EV << "-E-" << getFullPath() << " out port of InPort is busy! will be available in "
           << (gate("out", outPort)->getTransmissionChannel()->getTransmissionFinishTime()-simTime()) << endl;
        throw cRuntimeError("-E- Out port of InPort is busy!");
    }

    EV << "-I- " << getFullPath()
       << " SEND-FLIT"
       << " pktId=" << msg->getPktId()
       << " flitIdx=" << msg->getFlitIdx()
       << "/" << (msg->getFlits() - 1)
       << " inVC=" << inVC
       << " outPort=" << outPort
       << " outVC=" << msg->getVC()
       << " type=" << msg->getType()
       << " src=" << msg->getSrcId()
       << " dst=" << msg->getDstId()
       << " at " << simTime()
       << endl;

    inPortFlitInfo *info = (inPortFlitInfo*) msg->removeControlInfo();
    delete info;

    if (simTime()> statStartTime) {
        crossbarTraversal++;

        // NEW
        windowCrossbarTraversal++;

        if (collectPerHopWait) {
            if (msg->getType() == NOC_START_FLIT) {
                qTimeBySrcDst_head_flit[msg->getSrcId()][msg->getDstId()].collect(
                    1e9*(simTime().dbl() - msg->getArrivalTime().dbl()));
            } else {
                qTimeBySrcDst_body_flits[msg->getSrcId()][msg->getDstId()].collect(
                    1e9*(simTime().dbl() - msg->getArrivalTime().dbl()));
            }
        }
    }

    send(msg, "out", outPort);
    sendCredit(inVC,1);
}

void InPortSync::handleCalcVCResp(NoCFlitMsg *msg) {
    inPortFlitInfo *info = getFlitInfo(msg);
    int inVC = info->inVC;
    int outVC = msg->getVC();

    curOutVC[inVC] = outVC;

    EV << "-I- " << getFullPath()
       << " CALC-VC-RESP"
       << " pktId=" << msg->getPktId()
       << " flitIdx=" << msg->getFlitIdx()
       << "/" << (msg->getFlits() - 1)
       << " inVC=" << inVC
       << " outVC=" << outVC
       << " outPort=" << info->outPort
       << " type=" << msg->getType()
       << " src=" << msg->getSrcId()
       << " dst=" << msg->getDstId()
       << " at " << simTime()
       << endl;

    if (QByiVC[inVC].isEmpty()) {
        QByiVC[inVC].insert(msg);
    } else {
        QByiVC[inVC].insertBefore(QByiVC[inVC].front(), msg);
    }
    if (simTime() > statStartTime) {
        bufferWriteCount++;

        // NEW
        windowBufferWriteCount++;
    }

    measureQlength();

    EV << "-I- " << getFullPath() << " Packet:" << (msg->getPktId() >> 16)
       << "." << (msg->getPktId() % (1<< 16))
       << " will be sent on VC:" << outVC << endl;

    sendReq(msg);
}

void InPortSync::handleCalcOPResp(NoCFlitMsg *msg) {
    int inVC = getFlitInfo(msg)->inVC;

    curOutPort[inVC] = getFlitInfo(msg)->outPort;

    EV << "-I- " << getFullPath()
       << " CALC-OP-RESP"
       << " pktId=" << msg->getPktId()
       << " flitIdx=" << msg->getFlitIdx()
       << "/" << (msg->getFlits() - 1)
       << " inVC=" << inVC
       << " outPort=" << curOutPort[inVC]
       << " type=" << msg->getType()
       << " src=" << msg->getSrcId()
       << " dst=" << msg->getDstId()
       << " at " << simTime()
       << endl;

    EV << "-I- " << getFullPath() << " Packet:" << (msg->getPktId() >> 16)
       << "." << (msg->getPktId() % (1<< 16))
       << " will be sent to port:" << curOutPort[inVC] << endl;

    if (QByiVC[inVC].getLength() >= flitsPerVC) {
        throw cRuntimeError("-E- VC %d is already full receiving packet:%d",
                inVC, msg->getPktId());
    }

    if (QByiVC[inVC].isEmpty()) {
        send(msg,"calcVc$o");
    } else {
        QByiVC[inVC].insert(msg);
        measureQlength();
    }
}

void InPortSync::handleInFlitMsg(NoCFlitMsg *msg) {
    inPortFlitInfo *info = new inPortFlitInfo;
    msg->setControlInfo(info);
    int inVC = msg->getVC();
    info->inVC = inVC;

    if (msg->getFirstNet()) {
        msg->setFirstNetTime(simTime());
        msg->setFirstNet(false);
    }

    if (msg->getType() == NOC_START_FLIT) {
        if (curPktId[inVC]) {
            throw cRuntimeError("-E- got new packet 0x%x during packet 0x%x",
                    curPktId[inVC], msg->getPktId());
        }
        curPktId[inVC] = msg->getPktId();

        EV << "-I- " << getFullPath() << " Received Packet:"
           << (msg->getPktId() >> 16) << "." << (msg->getPktId() % (1<< 16))
           << endl;

        send(msg, "calcOp$o");
    } else {
        if (msg->getPktId() != curPktId[inVC]) {
            throw cRuntimeError("-E- got FLIT %d with packet 0x%x during packet 0x%x",
                    msg->getFlitIdx(), msg->getPktId(), curPktId[inVC]);
        }

        if (msg->getType() == NOC_END_FLIT)
            curPktId[inVC] = 0;

        int outPort = curOutPort[inVC];
        info->outPort = outPort;

        EV << "-I- " << getFullPath() << " FLIT:" << (msg->getPktId() >> 16)
           << "." << (msg->getPktId() % (1<< 16))
           << "." << msg->getFlitIdx() << " Queued to be sent on OP:"
           << outPort << endl;

        if (QByiVC[inVC].getLength() >= flitsPerVC) {
            throw cRuntimeError("-E- VC %d is already full receiving packet:%d",
                    inVC, msg->getPktId());
        }

        QByiVC[inVC].insert(msg);
        if (simTime() > statStartTime) {
            bufferWriteCount++;

            // NEW
            windowBufferWriteCount++;
        }

        measureQlength();
    }
}

void InPortSync::handleGntMsg(NoCGntMsg *msg) {
    int outVC = msg->getOutVC();
    int inVC = msg->getInVC();
    int op = msg->getArrivalGate()->getIndex();

    EV << "-I- " << getFullPath() << " Gnt of inVC: " << inVC << " outVC:" << outVC
       << " through gate:" << msg->getArrivalGate()->getFullPath() <<" SimTime:" <<simTime()<< endl;

    NoCFlitMsg* foundFlit = NULL;
    if (!QByiVC[inVC].isEmpty()) {
        foundFlit = (NoCFlitMsg*)QByiVC[inVC].pop();
        if (simTime() > statStartTime) {
            bufferReadCount++;

            // NEW
            windowBufferReadCount++;
        }
        foundFlit->setVC(curOutVC[inVC]);

        measureQlength();

        if (foundFlit->getType() == NOC_END_FLIT && !QByiVC[inVC].isEmpty()) {
            NoCFlitMsg* nextPkt = (NoCFlitMsg*)QByiVC[inVC].pop();
            if (simTime() > statStartTime) {
                bufferReadCount++;

                // NEW
                windowBufferReadCount++;
            }
            send(nextPkt,"calcVc$o");
        }

        sendFlit(foundFlit);

    } else {
        EV << "-I- Could not find any flit with inVC:" << inVC << endl;
        char nakName[64];
        sprintf(nakName, "nak-op:%d-ivc:%d-ovc:%d", op, inVC, outVC);
        NoCAckMsg *ack = new NoCAckMsg(nakName);
        ack->setKind(NOC_ACK_MSG);
        ack->setOutPortNum(op);
        ack->setInVC(inVC);
        ack->setOutVC(outVC);
        ack->setOK(false);
        send(ack, "ctrl$o", op);
    }
    delete msg;
}

void InPortSync::handleMessage(cMessage *msg) {
    // NEW
    if (msg == energyWindowMsg) {
        finalizeEnergyWindow(simTime());
        scheduleAt(simTime() + energyWindow, energyWindowMsg);
        return;
    }

    int msgType = msg->getKind();
    cGate *inGate = msg->getArrivalGate();
    if (msgType == NOC_FLIT_MSG) {
        if (inGate == gate("calcVc$i")) {
            handleCalcVCResp((NoCFlitMsg*) msg);
        } else if (inGate == gate("calcOp$i")) {
            handleCalcOPResp((NoCFlitMsg*) msg);
        } else {
            handleInFlitMsg((NoCFlitMsg*) msg);
        }
    } else if (msgType == NOC_GNT_MSG) {
        handleGntMsg((NoCGntMsg*) msg);
    } else {
        throw cRuntimeError("Does not know how to handle message of type %d",
                msg->getKind());
        delete msg;
    }
}

InPortSync::~InPortSync() {
    // NEW
    if (energyWindowMsg) {
        cancelAndDelete(energyWindowMsg);
        energyWindowMsg = NULL;
    }

    numVCs = par("numVCs");
    NoCFlitMsg* msg = NULL;
    for (int vc = 0; vc < numVCs; vc++) {
        while (!QByiVC[vc].isEmpty()) {
            msg = (NoCFlitMsg*) QByiVC[vc].pop();
            cancelAndDelete(msg);
        }
    }
}

void InPortSync::measureQlength() {
    if (simTime() > statStartTime) {
        int numVCs = par("numVCs");
        int Qsize = 0;
        for (int vc = 0; vc < numVCs; vc++) {
            Qsize = Qsize + QByiVC[vc].getLength();
        }
        QLenVec.record(Qsize);
    }
}

void InPortSync::finish() {
    // NEW
    finalizeEnergyWindow(simTime());

    if (simTime() > statStartTime) {
        int Dst;
        int Src;
        int rows = par("rows");
        int columns = par("columns");
        if (collectPerHopWait) {
            for (Dst = 0; Dst < (rows * columns); Dst++) {
                for (Src = 0; Src < (rows * columns); Src++) {
                    qTimeBySrcDst_head_flit[Src][Dst].record();
                    qTimeBySrcDst_body_flits[Src][Dst].record();
                }
            }
        }
        recordScalar("bufferWriteCount", bufferWriteCount);
        recordScalar("bufferReadCount", bufferReadCount);
        recordScalar("crossbarTraversal", crossbarTraversal);

        // NEW
        recordScalar("totalEnergyJ", totalEnergyJ);
    }
}
