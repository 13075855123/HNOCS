#ifndef __HNOCS_ONOC_OPTICAL_CIRCUIT_CONTROLLER_H_
#define __HNOCS_ONOC_OPTICAL_CIRCUIT_CONTROLLER_H_

#include <omnetpp.h>

#include <map>
#include <set>

#include "onoc/common/ControlPlaneEvents.h"

using namespace omnetpp;

class OpticalCircuitController : public cSimpleModule, public cListener {
  private:
    bool logCircuitEvents;
    simsignal_t setupAckEventSignal;
    simsignal_t dataReleaseEventSignal;
    simsignal_t opticalPathOpenSignal;
    simsignal_t opticalPathCloseSignal;
    cModule *topologyManagerModule;

    // Active source-destination optical circuits represented as (src,dst).
    std::set<std::pair<int, int> > activeCircuits;
    std::map<int, std::pair<int, int> > activeTokens;

  private:
    bool openCircuit(int srcId, int dstId);
    bool closeCircuit(int srcId, int dstId);

  protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
    virtual void finish();
    virtual void receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details);
};

#endif
