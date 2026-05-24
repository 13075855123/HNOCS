#include "OpticalCircuitController.h"

#include "onoc/control/LogicalTopologyManager.h"

Define_Module(OpticalCircuitController);

bool OpticalCircuitController::openCircuit(int srcId, int dstId) {
    std::pair<int, int> key(srcId, dstId);
    std::set<std::pair<int, int> >::iterator it = activeCircuits.find(key);
    if (it != activeCircuits.end()) {
        return false;
    }
    activeCircuits.insert(key);
    return true;
}

bool OpticalCircuitController::closeCircuit(int srcId, int dstId) {
    std::pair<int, int> key(srcId, dstId);
    std::set<std::pair<int, int> >::iterator it = activeCircuits.find(key);
    if (it == activeCircuits.end()) {
        return false;
    }
    activeCircuits.erase(it);
    return true;
}

void OpticalCircuitController::initialize() {
    logCircuitEvents = par("logCircuitEvents");
    setupAckEventSignal = registerSignal("onoc-setup-ack-event");
    dataReleaseEventSignal = registerSignal("onoc-data-release-event");
    opticalPathOpenSignal = registerSignal("onoc-optical-path-open-event");
    opticalPathCloseSignal = registerSignal("onoc-optical-path-close-event");

    topologyManagerModule = getSystemModule()->getSubmodule("topologyManager");

    getSimulation()->getSystemModule()->subscribe("onoc-setup-ack-event", this);
    getSimulation()->getSystemModule()->subscribe("onoc-data-release-event", this);
}

void OpticalCircuitController::handleMessage(cMessage *msg) {
    delete msg;
    throw cRuntimeError("OpticalCircuitController only supports signal-driven control");
}

void OpticalCircuitController::finish() {
    getSimulation()->getSystemModule()->unsubscribe(setupAckEventSignal, this);
    getSimulation()->getSystemModule()->unsubscribe(dataReleaseEventSignal, this);
    recordScalar("onoc-optical-active-circuits", static_cast<double>(activeCircuits.size()));
}

void OpticalCircuitController::receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details) {
    (void)source;
    (void)details;

    Enter_Method_Silent("OpticalCircuitController::receiveSignal()");

    if (signalID != setupAckEventSignal && signalID != dataReleaseEventSignal) {
        return;
    }

    int eventType = 0;
    int requesterId = -1;
    int targetId = -1;
    int token = 0;
    int spatialChannel = 0;
    int wavelengthMask = 0;
    onocDecodeControlEvent(value,
            eventType,
            requesterId,
            targetId,
            token,
            spatialChannel,
            wavelengthMask);

    if (requesterId < 0 || targetId < 0 || token <= 0) {
        return;
    }

    if (eventType == ONOC_EVT_SETUP_ACK) {
        std::pair<int, int> pairKey = std::make_pair(requesterId, targetId);
        bool newlyOpened = openCircuit(requesterId, targetId);
        activeTokens[token] = pairKey;
        emit(opticalPathOpenSignal,
                onocEncodeControlEvent(ONOC_EVT_SETUP_ACK,
                        requesterId,
                        targetId,
                        token,
                        spatialChannel,
                        wavelengthMask));
        if (logCircuitEvents) {
            EV_INFO << "Optical circuit opened for " << requesterId
                    << "->" << targetId
                    << " token=" << token
                    << " spatial=" << spatialChannel
                    << " wlMask=" << wavelengthMask;
            if (!newlyOpened) {
                EV_INFO << " (shared pair already active)";
            }
            EV_INFO << endl;
        }
        return;
    }

    if (eventType == ONOC_EVT_DATA_EOP_RELEASE) {
        LogicalTopologyManager *topologyManager = dynamic_cast<LogicalTopologyManager *>(topologyManagerModule);
        if (topologyManager) {
            topologyManager->releaseOpticalPathByToken(token);
        }

        std::pair<int, int> pairKey = std::make_pair(requesterId, targetId);
        std::map<int, std::pair<int, int> >::iterator tokenIt = activeTokens.find(token);
        if (tokenIt != activeTokens.end()) {
            pairKey = tokenIt->second;
            activeTokens.erase(tokenIt);
        }

        bool pairStillActive = false;
        for (std::map<int, std::pair<int, int> >::const_iterator it = activeTokens.begin(); it != activeTokens.end(); ++it) {
            if (it->second == pairKey) {
                pairStillActive = true;
                break;
            }
        }

        if (!pairStillActive && closeCircuit(pairKey.first, pairKey.second)) {
            emit(opticalPathCloseSignal,
                    onocEncodeControlEvent(ONOC_EVT_DATA_EOP_RELEASE,
                            pairKey.first,
                            pairKey.second,
                            token,
                            spatialChannel,
                            wavelengthMask));
            if (logCircuitEvents) {
                EV_INFO << "Optical circuit closed for " << pairKey.first
                        << "->" << pairKey.second
                        << " token=" << token << endl;
            }
        }
    }
}
