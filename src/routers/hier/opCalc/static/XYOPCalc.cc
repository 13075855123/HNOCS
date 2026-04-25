//
// Copyright (C) 2010-2011 Eitan Zahavi, The Technion EE Department
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
// along with this program.  If not, see http://www.gnu.org/licenses/>.
//

#include "XYOPCalc.h"
#include <NoCs_m.h>
#include <cstring>

Define_Module(XYOPCalc);

int XYOPCalc::rowColByID(int id, int &x, int &y)
{
    y = id / numCols;
    x = id % numCols;
    return(0);
}

// return true if the provided cModule pointer is a Port
bool
XYOPCalc::isPortModule(cModule *mod)
{
    return (mod && mod->getModuleType() == cModuleType::get(portType));
}

// helper: return true if mod is the hierarchical Router module
static bool isRouterModule(cModule *mod)
{
    if (!mod) return false;
    const char *nedType = mod->getNedTypeName();
    return (nedType && std::strcmp(nedType, "hnocs.routers.hier.Router") == 0);
}

// return the pointer to the port on the other side of the given port or NULL
cModule *
XYOPCalc::getPortRemotePort(cModule *port)
{
    cGate *gate = port->gate("out$o");
    if (!gate) return NULL;

    cGate *pathEnd = gate->getPathEndGate();
    if (!pathEnd) return NULL;

    cGate *remGate = pathEnd->getPreviousGate();
    if (!remGate) return NULL;

    cModule *neighbour = remGate->getOwnerModule();
    if (!isPortModule(neighbour)) return NULL;
    if (neighbour == port) return NULL;
    return neighbour;
}

// return true if the provided cModule pointer is a Core
bool
XYOPCalc::isCoreModule(cModule *mod)
{
    if (!mod)
        return false;

    // Ports are not cores
    if (isPortModule(mod))
        return false;

    // Routers are not cores
    if (isRouterModule(mod))
        return false;

    // 1) Exact configured coreType match
    try {
        cModuleType *configuredCoreType = cModuleType::get(coreType);
        if (configuredCoreType && mod->getModuleType() == configuredCoreType)
            return true;
    } catch (...) {
        // ignore lookup failure and continue with generic terminal-core checks
    }

    // 2) Generic endpoint-core match:
    //    accept modules that look like local NI/core/PE endpoints:
    bool hasId  = mod->hasPar("id");
    bool hasIn  = mod->hasGate("in");
    bool hasOut = mod->hasGate("out");

    if (hasId && hasIn && hasOut)
        return true;

    return false;
}

// return the pointer to the Core on the other side of the given port or NULL
cModule *
XYOPCalc::getPortRemoteCore(cModule *port)
{
    const char *gateNames[] = {"out$o", "in$i"};
    for (int i = 0; i < 2; i++) {
        cGate *gate = port->gate(gateNames[i]);
        if (!gate) continue;

        cGate *pathEnd = gate->getPathEndGate();
        if (!pathEnd) continue;

        cGate *remGate = pathEnd->getPreviousGate();
        if (!remGate) continue;

        cModule *neighbour = remGate->getOwnerModule();
        if (!neighbour || neighbour == port) continue;

        if (isCoreModule(neighbour))
            return neighbour;
    }
    return NULL;
}

// Given the port pointer find the index idx such that sw_out[idx]
// connect to that port
int
XYOPCalc::getIdxOfSwPortConnectedToPort(cModule *port)
{
    for (int i = 0; i < getParentModule()->gateSize("sw_in"); i++) {
        cGate *oGate = getParentModule()->gate("sw_in", i);
        if (!oGate) return -1;

        cGate *pathEnd = oGate->getPathEndGate();
        if (!pathEnd) return -1;

        cGate *remGate = pathEnd->getPreviousGate();
        if (!remGate) return -1;

        cModule *neighbour = remGate->getOwnerModule();
        if (neighbour == port)
            return i;
    }
    return -1;
}

// Map local sw index to router physical port index.
// Router.ned removes the local physical port from sw_in/sw_out.
static int swIndexToPhysicalPort(int localPhysicalPort, int swIdx)
{
    return (swIdx < localPhysicalPort) ? swIdx : (swIdx + 1);
}

// Check whether a router physical port is externally connected.
static bool isRouterPhysicalPortConnected(cModule *router, int physicalPort)
{
    cGate *outGate = router->gateHalf("out", cGate::OUTPUT, physicalPort);
    cGate *inGate  = router->gateHalf("in",  cGate::INPUT,  physicalPort);

    bool outConnected = (outGate && outGate->isConnectedOutside());
    bool inConnected  = (inGate  && inGate->isConnectedOutside());

    return (outConnected || inConnected);
}

// Analyze the topology of this router and obtain the port numbers
// connected to the 4 directions and the local core/PE endpoint.
int
XYOPCalc::analyzeMeshTopology()
{
    northPort = -1;
    westPort  = -1;
    southPort = -1;
    eastPort  = -1;
    corePort  = -1;

    cModule *port   = getParentModule();
    cModule *router = port->getParentModule();

    int localPhysicalPort = port->getIndex();

    for (int swIdx = 0; swIdx < port->gateSize("sw_out"); swIdx++) {
        int physicalPort = swIndexToPhysicalPort(localPhysicalPort, swIdx);

        if (!isRouterPhysicalPortConnected(router, physicalPort))
            continue;

        switch (physicalPort) {
            case 0:
                if (northPort != -1)
                    throw cRuntimeError("Already found north port %d and another mapping %d on %s",
                                        northPort, swIdx, getFullPath().c_str());
                northPort = swIdx;
                EV << "-I- " << getFullPath()
                   << " mapped physical north port[0] to sw_out[" << swIdx << "]" << endl;
                break;

            case 1:
                if (westPort != -1)
                    throw cRuntimeError("Already found west port %d and another mapping %d on %s",
                                        westPort, swIdx, getFullPath().c_str());
                westPort = swIdx;
                EV << "-I- " << getFullPath()
                   << " mapped physical west port[1] to sw_out[" << swIdx << "]" << endl;
                break;

            case 2:
                if (southPort != -1)
                    throw cRuntimeError("Already found south port %d and another mapping %d on %s",
                                        southPort, swIdx, getFullPath().c_str());
                southPort = swIdx;
                EV << "-I- " << getFullPath()
                   << " mapped physical south port[2] to sw_out[" << swIdx << "]" << endl;
                break;

            case 3:
                if (eastPort != -1)
                    throw cRuntimeError("Already found east port %d and another mapping %d on %s",
                                        eastPort, swIdx, getFullPath().c_str());
                eastPort = swIdx;
                EV << "-I- " << getFullPath()
                   << " mapped physical east port[3] to sw_out[" << swIdx << "]" << endl;
                break;

            case 4:
                if (corePort != -1)
                    throw cRuntimeError("Already found core port %d and another mapping %d on %s",
                                        corePort, swIdx, getFullPath().c_str());
                corePort = swIdx;
                EV << "-I- " << getFullPath()
                   << " mapped physical core/PE port[4] to sw_out[" << swIdx << "]" << endl;
                break;

            default:
                // Ignore any extra physical ports if a larger router is ever used.
                break;
        }
    }

    return(0);
}

void XYOPCalc::initialize()
{
    coreType = par("coreType");
    portType = par("portType");

    cModule *router = getParentModule()->getParentModule();
    int id = router->par("id");
    numCols = router->getParentModule()->par("columns");

    rowColByID(id, rx, ry);

    analyzeMeshTopology();

    EV << "-I- " << getFullPath() << " Found N/W/S/E/C ports:" << northPort
       << "/" << westPort << "/" << southPort << "/"
       << eastPort << "/" << corePort << endl;

    WATCH(northPort);
    WATCH(westPort);
    WATCH(eastPort);
    WATCH(southPort);
    WATCH(corePort);
}

void XYOPCalc::handlePacketMsg(NoCFlitMsg* msg)
{
    int dx, dy;
    rowColByID(msg->getDstId(), dx, dy);
    int swOutPortIdx;

    if ((dx == rx) && (dy == ry)) {
        swOutPortIdx = corePort;
    } else if (dx > rx) {
        swOutPortIdx = eastPort;
    } else if (dx < rx) {
        swOutPortIdx = westPort;
    } else if (dy > ry) {
        swOutPortIdx = northPort;
    } else {
        swOutPortIdx = southPort;
    }

    if (swOutPortIdx < 0) {
        throw cRuntimeError("Routing dead end at %s (%d,%d) "
                "for destination %d (%d,%d)",
                getParentModule()->getFullPath().c_str(), rx, ry,
                msg->getDstId(), dx, dy);
    }

    cObject *obj = msg->getControlInfo();
    if (obj == NULL) {
        throw cRuntimeError("-E- %s BUG - No Control Info for FLIT: %s",
                getFullPath().c_str(), msg->getFullName());
    }

    inPortFlitInfo *info = dynamic_cast<inPortFlitInfo*>(obj);
    info->outPort = swOutPortIdx;
    send(msg, "calc$o");
}

void XYOPCalc::handleMessage(cMessage *msg)
{
    int msgType = msg->getKind();
    if (msgType == NOC_FLIT_MSG) {
        handlePacketMsg((NoCFlitMsg*)msg);
    } else {
        throw cRuntimeError("Does not know how to handle message of type %d", msg->getKind());
        delete msg;
    }
}
