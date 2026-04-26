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

#ifndef __HNOCS_SYNC_INPORT_H_
#define __HNOCS_SYNC_INPORT_H_

#include <omnetpp.h>
using namespace omnetpp;

#include "NoCs_m.h"
#include "routers/hier/FlitMsgCtrl.h"

//
// Input Port of a router
//
// Ports:
//   inout in - where FLITs are received and credits are reported
//   inout out_sw - where req/ack and FLITs are provided to schedulers
//
// Events:
//   NoCFlitMsg, NoCPacketMsg - received on the "in" port
//   NoCCreditMsg - sent back on the in port when the FLIT is sent to the scheduler
//   Gnt - received from the out port when the scheduler select this port
//         (this is a response to req and before the ack)
//   Pop - self event to flag the end of sending a FLIT. It is used for counting how many
//         parallel in flight FLITs leave the inPort. Such that numParallelSends
//         can be calculated. The Pop must happen BEFORE any other event to clear before next Gnts
//
// NOTE: on each in VC there is only 1 packet being received at a given time
// NOTE: on each out port there is only 1 packet being sent at a given time
//
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

//    // ===== NEW =====
//    simtime_t energyWindow;
//    cMessage* energyWindowMsg;
//    double eBufferWrite;
//    double eBufferRead;
//    double eCrossbar;
//    double pLeak;
//
//    long windowBufferWriteCount;
//    long windowBufferReadCount;
//    long windowCrossbarTraversal;
//
//    double windowEnergyJ;
//    double totalEnergyJ;
//
//    cOutVector windowEnergyVec;
//    cOutVector cumulativeEnergyVec;
//    cOutVector windowAvgPowerVec;

//    void finalizeEnergyWindow(simtime_t now);

    class inPortFlitInfo* getFlitInfo(NoCFlitMsg *msg);

protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
    virtual void finish();
public:
    virtual ~InPortSync();
};
#endif
