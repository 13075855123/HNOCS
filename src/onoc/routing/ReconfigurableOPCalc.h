#ifndef __HNOCS_ONOC_RECONFIGURABLE_OPCALC_H_
#define __HNOCS_ONOC_RECONFIGURABLE_OPCALC_H_

#include <omnetpp.h>

#include <map>

using namespace omnetpp;

#include "NoCs_m.h"
#include "onoc/control/LogicalTopologyManager.h"
#include "routers/hier/FlitMsgCtrl.h"

// Output-port calculator that routes flits according to runtime logical topology.
// Physical network remains Torus; this module maps logical next-hop to physical ports.
class ReconfigurableOPCalc : public cSimpleModule {
  private:
    // Physical torus shape and local router coordinates.
    int numCols;
    int numRows;
    int routerId;
    int rx;
    int ry;

    // Switch port index connected to local core.
    int corePort;

    // Runtime type names and manager module lookup key.
    const char *portType;
    const char *coreType;
    const char *topologyManagerName;

    // Optional optical planning context used for mixed electro-optical evolution.
    bool enableOpticalWavelengthPlanning;
    bool enforceOpticalWavelengthCap;
    bool dropPacketOnWavelengthShortage;
    int availableOpticalWavelengths;
    simsignal_t opticalRequiredWavelengthsSignal;
    simsignal_t opticalWavelengthInsufficientSignal;

    // Pointer to topology manager and local map neighborRouterId -> sw port index.
    LogicalTopologyManager *topologyManager;
    std::map<int, int> neighborRouterIdToPort;

    // GlobalBuffer routing support.
    int bufferIdBase;
    int bufferPort;   // sw_out index connecting to GlobalBuffer (-1 if none)

  private:
    // Coordinate/id conversion helpers.
    int nodeIdByRowCol(int x, int y) const;
    void rowColByNodeId(int nodeId, int &x, int &y) const;

    // Type checks for reflected OMNeT submodules.
    bool isPortModule(cModule *mod) const;
    bool isCoreModule(cModule *mod) const;

    // Topology introspection on current router wiring.
    cModule *getPortRemotePort(cModule *port) const;
    cModule *getPortRemoteCore(cModule *port) const;
    int getIdxOfSwPortConnectedToPort(cModule *port) const;

    // Build local neighbor-to-port map once at initialization.
    void analyzeRouterTopology();

    // Physical routing helpers.
    int pickPortForRouter(int targetRouterId) const;
    int torusDistance(int fromRouterId, int toRouterId) const;
    int pickBestAvailableNeighborTowards(int targetRouterId) const;
    int getNextRouterOnTorusPath(int targetRouterId) const;

    // Main packet handling routine.
    void handlePacketMsg(NoCFlitMsg *msg);

  protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
};

#endif
