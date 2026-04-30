#ifndef __HNOCS_SYNC_INPORT_H_
#define __HNOCS_SYNC_INPORT_H_

#include <omnetpp.h>
using namespace omnetpp;

#include "NoCs_m.h"
#include "routers/hier/FlitMsgCtrl.h"
#include "thermal/ThermalTrace.h"

class InPortSync: public cSimpleModule {
private:
    bool collectPerHopWait;
    int numVCs;
    int flitsPerVC;
    simtime_t statStartTime;

    std::vector<cQueue> QByiVC;
    std::vector<int> curOutVC;
    std::vector<int> curOutPort;
    std::vector<int> curPktId;

    void sendCredit(int vc, int numFlits);
    void sendReq(NoCFlitMsg *msg);
    void sendFlit(NoCFlitMsg *msg);
    void handleCalcVCResp(NoCFlitMsg *msg);
    void handleCalcOPResp(NoCFlitMsg *msg);
    void handleInFlitMsg(NoCFlitMsg *msg);
    void handleGntMsg(NoCGntMsg *msg);
    void handlePopMsg(NoCPopMsg *msg);
    void measureQlength();

    std::vector<std::vector<cStdDev> > qTimeBySrcDst_head_flit;
    std::vector<std::vector<cStdDev> > qTimeBySrcDst_body_flits;
    cOutVector QLenVec;
    long bufferWriteCount;
    long bufferReadCount;
    long crossbarTraversal;

    // NEW: InPort energy model
    simtime_t energyWindow;
    cMessage* energyWindowMsg;
    double eBufferWrite;
    double eBufferRead;
    double eCrossbar;
    double pLeak;

    long windowBufferWriteCount;
    long windowBufferReadCount;
    long windowCrossbarTraversal;

    double windowEnergyJ;
    double totalEnergyJ;

    cOutVector windowEnergyVec;
    cOutVector cumulativeEnergyVec;
    cOutVector windowAvgPowerVec;

    // NEW
    void finalizeEnergyWindow(simtime_t now);

    // NEW: only one inPort per router submits aggregated router power
    bool thermalAggregationOwner;

    class inPortFlitInfo* getFlitInfo(NoCFlitMsg *msg);

protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
    virtual void finish();
public:
    virtual ~InPortSync();
};
#endif
