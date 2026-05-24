#include "ReconfigurableOPCalc.h"

#include "onoc/common/ControlPlaneEvents.h"

#include <algorithm>
#include <climits>
#include <cstdlib>

Define_Module(ReconfigurableOPCalc);

// Convert (x,y) to linear router id.
int ReconfigurableOPCalc::nodeIdByRowCol(int x, int y) const {
    return y * numCols + x;
}

// Convert linear router id to (x,y).
void ReconfigurableOPCalc::rowColByNodeId(int nodeId, int &x, int &y) const {
    y = nodeId / numCols;
    x = nodeId % numCols;
}

// Check if module matches configured port type.
bool ReconfigurableOPCalc::isPortModule(cModule *mod) const {
    return mod->getModuleType() == cModuleType::get(portType);
}

// Check if module matches configured core type or is a generic endpoint (PE/NI).
bool ReconfigurableOPCalc::isCoreModule(cModule *mod) const {
    if (!mod) return false;
    // Exact type match
    try {
        if (mod->getModuleType() == cModuleType::get(coreType)) return true;
    } catch (...) {}
    // Generic endpoint: has id + in + out gates (covers TaskPE, NI, etc.)
    return mod->hasPar("id") && mod->hasGate("in") && mod->hasGate("out");
}

// Returns remote module if the given port connects to another router port.
cModule *ReconfigurableOPCalc::getPortRemotePort(cModule *port) const {
    cGate *gate = port->gate("out$o");
    if (!gate) {
        return NULL;
    }

    cGate *remGate = gate->getPathEndGate()->getPreviousGate();
    if (!remGate) {
        return NULL;
    }

    cModule *neighbor = remGate->getOwnerModule();
    if (!isPortModule(neighbor) || neighbor == port) {
        return NULL;
    }

    return neighbor;
}

// Returns remote module if the given port connects to local core.
cModule *ReconfigurableOPCalc::getPortRemoteCore(cModule *port) const {
    cGate *gate = port->gate("out$o");
    if (!gate) {
        return NULL;
    }

    cGate *remGate = gate->getPathEndGate()->getPreviousGate();
    if (!remGate) {
        return NULL;
    }

    cModule *neighbor = remGate->getOwnerModule();
    if (!isCoreModule(neighbor) || neighbor == port) {
        return NULL;
    }

    return neighbor;
}

// Find switch port index whose sw_in[i] is wired to the given router port module.
int ReconfigurableOPCalc::getIdxOfSwPortConnectedToPort(cModule *port) const {
    for (int i = 0; i < getParentModule()->gateSize("sw_in"); ++i) {
        cGate *oGate = getParentModule()->gate("sw_in", i);
        if (!oGate) {
            return -1;
        }

        cGate *remGate = oGate->getPathEndGate()->getPreviousGate();
        if (!remGate) {
            return -1;
        }

        cModule *neighbor = remGate->getOwnerModule();
        if (neighbor == port) {
            return i;
        }
    }
    return -1;
}

void ReconfigurableOPCalc::analyzeRouterTopology() {
    // Build one-time map: remote router id -> local switch output port index.
    corePort = -1;
    bufferPort = -1;
    neighborRouterIdToPort.clear();

    cModule *router = getParentModule()->getParentModule();

    for (cModule::SubmoduleIterator iter(router); !iter.end(); iter++) {
        cModule *port = *iter;
        if (!isPortModule(port)) {
            continue;
        }

        int portIdx = getIdxOfSwPortConnectedToPort(port);
        if (portIdx < 0) {
            continue;
        }

        cModule *remCore = getPortRemoteCore(port);
        if (remCore) {
            int remCoreId = remCore->par("id").intValue();
            if (remCoreId == routerId) {
                corePort = portIdx;
            }
            continue;
        }

        cModule *remPort = getPortRemotePort(port);
        if (remPort) {
            int remRouterId = remPort->getParentModule()->par("id").intValue();
            if (neighborRouterIdToPort.find(remRouterId) == neighborRouterIdToPort.end()) {
                neighborRouterIdToPort[remRouterId] = portIdx;
            }
        }
    }

    // Detect GlobalBuffer port: connected module that is neither router nor core
    if (bufferIdBase >= 0) {
        cModule *router2 = getParentModule()->getParentModule();
        // Find the west port (physical port index 1) — this is where GB connects at column 0
        // GB connects to west port of column-0 routers
        for (cModule::SubmoduleIterator iter(router2); !iter.end(); iter++) {
            cModule *candidatePort = *iter;
            if (!isPortModule(candidatePort)) continue;
            int portIndex = candidatePort->getIndex();
            // Physical port 1 = West (where GB connects)
            if (portIndex == 1 && candidatePort->gate("out$o")->isConnectedOutside()) {
                cModule *remPort = getPortRemotePort(candidatePort);
                if (!remPort) {
                    bufferPort = getIdxOfSwPortConnectedToPort(candidatePort);
                    EV << "-I- " << getFullPath() << " detected GB port at idx=" << bufferPort << endl;
                    break;
                }
            }
        }
    }

    if (corePort < 0) {
        EV << "-W- " << getFullPath() << " could not find local core port" << endl;
    }

    if (neighborRouterIdToPort.empty()) {
        EV << "-W- " << getFullPath() << " found no remote routers on this input port" << endl;
    }
}

int ReconfigurableOPCalc::pickPortForRouter(int targetRouterId) const {
    // Return direct output port toward the requested neighboring router.
    std::map<int, int>::const_iterator it = neighborRouterIdToPort.find(targetRouterId);
    if (it == neighborRouterIdToPort.end()) {
        return -1;
    }
    return it->second;
}

int ReconfigurableOPCalc::torusDistance(int fromRouterId, int toRouterId) const {
    // Manhattan distance under torus wrap-around; used by fallback heuristic.
    int fx = 0;
    int fy = 0;
    int tx = 0;
    int ty = 0;

    rowColByNodeId(fromRouterId, fx, fy);
    rowColByNodeId(toRouterId, tx, ty);

    int dx = std::abs(tx - fx);
    int dy = std::abs(ty - fy);

    if (numCols > 0) {
        dx = std::min(dx, numCols - dx);
    }
    if (numRows > 0) {
        dy = std::min(dy, numRows - dy);
    }

    return dx + dy;
}

int ReconfigurableOPCalc::pickBestAvailableNeighborTowards(int targetRouterId) const {
    // Fallback policy: among physically connected neighbors, pick the one
    // with minimum torus distance to target router.
    int bestNeighbor = -1;
    int bestDist = INT_MAX;

    for (std::map<int, int>::const_iterator it = neighborRouterIdToPort.begin();
            it != neighborRouterIdToPort.end(); ++it) {
        int neighborRouterId = it->first;
        int dist = torusDistance(neighborRouterId, targetRouterId);
        if (dist < bestDist) {
            bestDist = dist;
            bestNeighbor = neighborRouterId;
        }
    }

    return bestNeighbor;
}

int ReconfigurableOPCalc::getNextRouterOnTorusPath(int targetRouterId) const {
    // Deterministic torus step toward target:
    // X dimension first, then Y; ties prefer + direction.
    if (targetRouterId == routerId) {
        return routerId;
    }

    int tx = 0;
    int ty = 0;
    rowColByNodeId(targetRouterId, tx, ty);

    if ((tx != rx) && (numCols > 1)) {
        int right = (tx - rx + numCols) % numCols;
        int left = (rx - tx + numCols) % numCols;

        int nx = rx;
        if (right <= left) {
            nx = (rx + 1) % numCols;
        } else {
            nx = (rx - 1 + numCols) % numCols;
        }
        return nodeIdByRowCol(nx, ry);
    }

    if ((ty != ry) && (numRows > 1)) {
        int down = (ty - ry + numRows) % numRows;
        int up = (ry - ty + numRows) % numRows;

        int ny = ry;
        if (down <= up) {
            ny = (ry + 1) % numRows;
        } else {
            ny = (ry - 1 + numRows) % numRows;
        }
        return nodeIdByRowCol(rx, ny);
    }

    return targetRouterId;
}

void ReconfigurableOPCalc::initialize() {
    // Load type names and coordinates, then bind to topology manager.
    coreType = par("coreType");
    portType = par("portType");
    topologyManagerName = par("topologyManagerName");
    enableOpticalWavelengthPlanning = par("enableOpticalWavelengthPlanning");
    enforceOpticalWavelengthCap = par("enforceOpticalWavelengthCap");
    dropPacketOnWavelengthShortage = par("dropPacketOnWavelengthShortage");
    availableOpticalWavelengths = par("availableOpticalWavelengths");

    if (availableOpticalWavelengths <= 0) {
        throw cRuntimeError("availableOpticalWavelengths must be > 0 (got %d)", availableOpticalWavelengths);
    }

    opticalRequiredWavelengthsSignal = registerSignal("onoc-optical-required-wavelengths");
    opticalWavelengthInsufficientSignal = registerSignal("onoc-optical-wavelength-insufficient");

    cModule *router = getParentModule()->getParentModule();
    cModule *network = router->getParentModule();
    routerId = router->par("id").intValue();
    numCols = network->par("columns").intValue();
    numRows = network->par("rows").intValue();

    if (network->hasPar("bufferBaseId")) {
        bufferIdBase = network->par("bufferBaseId");
    } else {
        bufferIdBase = -1;
    }

    if (numCols <= 0 || numRows <= 0) {
        throw cRuntimeError("rows and columns must be positive for ReconfigurableOPCalc");
    }

    rowColByNodeId(routerId, rx, ry);

    cModule *managerModule = getSystemModule()->getSubmodule(topologyManagerName);
    topologyManager = dynamic_cast<LogicalTopologyManager *>(managerModule);
    if (!topologyManager) {
        throw cRuntimeError("Could not find LogicalTopologyManager '%s' from %s",
                topologyManagerName, getFullPath().c_str());
    }

    // Analyze static router wiring once; topology changes are logical only.
    analyzeRouterTopology();
}

void ReconfigurableOPCalc::handlePacketMsg(NoCFlitMsg *msg) {
    // Resolve outgoing physical switch port for this flit.
    int swOutPortIdx = -1;
    int packetClass = 0;
    int packetSpatialChannel = 0;
    int packetWavelengthMask = 0;
    onocDecodePacketTag(msg->getSL(), packetClass, packetSpatialChannel, packetWavelengthMask);
    bool isDataPacket = (packetClass == ONOC_PKT_DATA);

    if (enableOpticalWavelengthPlanning && isDataPacket && msg->getSrcId() == routerId) {
        if (msg->getType() == NOC_START_FLIT) {
            int requiredWavelengths = topologyManager->getRequiredOpticalWavelengths(msg->getSrcId(), msg->getDstId());
            emit(opticalRequiredWavelengthsSignal, requiredWavelengths);

            int selectedSpatial = -1;
            std::vector<int> selectedWavelengths;
            bool insufficientResources = false;
            std::string failureReason;
            bool allocated = topologyManager->tryAllocateOpticalPathForPacket(
                    msg->getSrcId(),
                    msg->getDstId(),
                    msg->getPktId(),
                    selectedSpatial,
                    selectedWavelengths,
                    insufficientResources,
                    failureReason);

            if (!allocated) {
                emit(opticalWavelengthInsufficientSignal, 1L);
                EV_WARN << "Optical allocation failed for packet " << msg->getPktId()
                        << " pair " << msg->getSrcId() << "->" << msg->getDstId()
                        << ": " << failureReason << endl;

                if (insufficientResources && dropPacketOnWavelengthShortage) {
                    cObject *obj = msg->getControlInfo();
                    if (obj == NULL) {
                        throw cRuntimeError("-E- %s BUG - No Control Info for FLIT: %s",
                                getFullPath().c_str(), msg->getFullName());
                    }

                    inPortFlitInfo *info = dynamic_cast<inPortFlitInfo *>(obj);
                    if (!info) {
                        throw cRuntimeError("Control info type mismatch for FLIT: %s", msg->getFullName());
                    }

                    // Use negative outPort as a drop marker for InPortAsync.
                    info->outPort = -1;
                    send(msg, "calc$o");
                    return;
                }

                if (enforceOpticalWavelengthCap) {
                    throw cRuntimeError("Optical allocation failed for packet %d (%d->%d): %s",
                            msg->getPktId(), msg->getSrcId(), msg->getDstId(), failureReason.c_str());
                }
            } else if (requiredWavelengths > availableOpticalWavelengths) {
                // Keep legacy threshold warning behavior so existing experiments are comparable.
                emit(opticalWavelengthInsufficientSignal, 1L);
                EV_WARN << "Required optical wavelengths " << requiredWavelengths
                        << " exceed availableOpticalWavelengths=" << availableOpticalWavelengths
                        << " for pair " << msg->getSrcId() << "->" << msg->getDstId() << endl;
                if (enforceOpticalWavelengthCap) {
                    throw cRuntimeError("Optical wavelength requirement %d exceeds availableOpticalWavelengths=%d for pair %d->%d",
                            requiredWavelengths, availableOpticalWavelengths, msg->getSrcId(), msg->getDstId());
                }
            }
        } else if (msg->getType() == NOC_END_FLIT && packetWavelengthMask == 0) {
            // Legacy data-stage allocation path (no setup token metadata).
            topologyManager->releaseOpticalPathForPacket(msg->getPktId());
        }
    }

    // GlobalBuffer routing: GB IDs are in [bufferIdBase, bufferIdBase+numRows-1]
    bool isGBDest = (bufferIdBase >= 0 && msg->getDstId() >= bufferIdBase
            && msg->getDstId() < bufferIdBase + numRows);

    if (msg->getDstId() == routerId) {
        // Local delivery: route to core port.
        swOutPortIdx = corePort;
    } else if (isGBDest) {
        // Route toward GlobalBuffer at west of column 0
        int bufferRow = msg->getDstId() - bufferIdBase;
        if (rx == 0 && ry == bufferRow) {
            // At GB column, correct row: route directly to GB
            swOutPortIdx = bufferPort;
        } else if (rx > 0) {
            // Not at column 0: go west toward column 0
            swOutPortIdx = pickPortForRouter(routerId - 1);
        } else if (ry > bufferRow) {
            // At column 0, need to go north toward target row
            swOutPortIdx = pickPortForRouter(routerId - numCols);
        } else {
            // At column 0, need to go south toward target row
            swOutPortIdx = pickPortForRouter(routerId + numCols);
        }
    } else {
        // Step 1: ask logical topology manager for next logical hop.
        int logicalNextHop = topologyManager->getLogicalNextHop(routerId, msg->getDstId());
        if (logicalNextHop < 0) {
            throw cRuntimeError("No logical path from router %d to destination %d under topology '%s'",
                    routerId, msg->getDstId(), topologyManager->getCurrentTopology().c_str());
        }

        // Step 2: if logical hop is physically adjacent, use it directly.
        swOutPortIdx = pickPortForRouter(logicalNextHop);

        // Step 3: otherwise move one torus step toward the logical hop.
        if (swOutPortIdx < 0) {
            int torusNextHop = getNextRouterOnTorusPath(logicalNextHop);
            swOutPortIdx = pickPortForRouter(torusNextHop);
        }

        // Step 4: final fallback by nearest physically available neighbor.
        if (swOutPortIdx < 0) {
            int fallbackNeighbor = pickBestAvailableNeighborTowards(logicalNextHop);
            swOutPortIdx = pickPortForRouter(fallbackNeighbor);
        }
    }

    if (swOutPortIdx < 0) {
        throw cRuntimeError("Routing dead end at router %d for destination %d", routerId, msg->getDstId());
    }

    cObject *obj = msg->getControlInfo();
    if (obj == NULL) {
        throw cRuntimeError("-E- %s BUG - No Control Info for FLIT: %s",
                getFullPath().c_str(), msg->getFullName());
    }

    inPortFlitInfo *info = dynamic_cast<inPortFlitInfo *>(obj);
    if (!info) {
        throw cRuntimeError("Control info type mismatch for FLIT: %s", msg->getFullName());
    }

    // Write chosen switch output port into control info for downstream modules.
    info->outPort = swOutPortIdx;
    send(msg, "calc$o");
}

void ReconfigurableOPCalc::handleMessage(cMessage *msg) {
    // Only flit messages are expected on this module interface.
    if (msg->getKind() == NOC_FLIT_MSG) {
        handlePacketMsg((NoCFlitMsg *) msg);
    } else {
        throw cRuntimeError("Does not know how to handle message of type %d", msg->getKind());
    }
}
