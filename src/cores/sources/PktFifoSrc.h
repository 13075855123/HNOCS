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

#ifndef __HNOCS_PKT_FIFO_SOURCE_H_
#define __HNOCS_PKT_FIFO_SOURCE_H_

#include <omnetpp.h>
#include <vector>
#include <map>
#include <set>
using namespace omnetpp;

#include "NoCs_m.h"
#include "onoc/common/OpticalPathMetrics.h"
#include "onoc/common/ControlPlaneEvents.h"

class LogicalTopologyManager;

#define MAXTRACESIZE 500000
//
// A simple source of Packets made out of FLITs with separate control and optical queues.
//
class PktFifoSrc: public cSimpleModule, public cListener {
private:
	// parameters:
	int srcId;
	int dstId;
	int flitSize_B;
	simtime_t statStartTime; // in sec
	bool isSynchronous;       // if true will send packets on clock with freq of out link
	bool			isTrace; 					// If true uses a trace file for flitArrivalDelay
	char 			fileName;					// trace filename

	// for reading trace data
	double packetArrivalDelayArray[MAXTRACESIZE];
	int packetArrivalDelayArraySize;
	int traceIndex; // index for trace array

	// state:
	int pktIdx;
	int flitIdx;
	int curPktLen;
	int curPktId;
	int curPktVC;
	double numQueuedPkts;
	int controlQueuedPkts;
	int opticalQueuedPkts;
	int maxQueuedPkts;
	int curMsgDst;			// the destination of the current msg
	int curMsgLen;			// length in packets of current msg
	int curPktIdx;          // the packet index in the msg

	int numSentPackets;// number of sent packets, assume that there is only single destination
	double numGenPackets; // number of generated packets, for loss probability
	double totalNumQPackets; // number of queued packets, for loss probability
	long controlPacketsEnqueued;
	long opticalPacketsEnqueued;
	long controlPacketsSent;
	long opticalPacketsSent;
	long opticalBudgetViolationCount;
	long budgetRerouteCount;          // number of times budget triggered a reroute
	cQueue controlQ;
	cQueue opticalQ;
	NoCPopMsg *controlPopMsg; // used to pop control packets modeling the wire BW
	NoCPopMsg *opticalPopMsg; // used to pace direct optical transmission
	cMessage  *genMsg; // used to gen next flit
	int credits;       // number of credits on VC=0
	double tClk_s;     // clk extracted from output channel
	bool enableSetupHandshake;
	bool singlePacketPerMessage;
	int setupControlPktLen;
	int dataPktLenWhenHandshake;
	simtime_t setupRetryDelay;
	simtime_t setupPendingTimeout;
	bool			enableOpticalBypass;
	int			numRows;
	int			numColumns;
	double			opticalWavelengthBitrate;
	simtime_t		opticalBasePropagationDelay;
	simtime_t		opticalPerTorusHopDelay;
	int			opticalRequiredWavelengths;
	int			opticalBurstSize; // data packets per circuit setup burst
	int numNodes;
	std::vector<unsigned char> circuitReadyByDst;
	std::vector<unsigned char> setupPendingByDst;
	std::vector<simtime_t> nextSetupAttemptByDst;
	std::vector<simtime_t> setupPendingExpiryByDst;
	std::vector<int> pendingSetupTokenByDst;
	std::vector<int> pendingSetupSpatialByDst;
	std::vector<int> pendingSetupWavelengthMaskByDst;
	std::vector<int> activeCircuitTokenByDst;
	std::vector<int> activeSpatialByDst;
	std::vector<int> activeWavelengthMaskByDst;
	simsignal_t setupReqEventSignal;
	simsignal_t setupAckEventSignal;
	LogicalTopologyManager *topologyManager;
	bool enableTrafficVisualization;
	simtime_t visualLinkHoldTime;
	std::map<cMessage *, cFigure *> visualLinkCleanup;
	std::set<cMessage *> pendingOpticalReleaseMsgs;
	long setupReqRxCount;
	long setupAckRxCount;
	long setupAckAcceptedCount;
	long setupAckStaleCount;
	long setupReserveFailCount;
	long setupPendingTimeoutCount;

	// Statistics
	cHistogram dstIdHist;
	cOutVector dstIdVec;
	cStdDev FullQueueIndicator; // If >0 then the queue was full during the simulation
	cStdDev queueSize; // queue fill in % tracked every generation event
	cStdDev controlQueueSize; // electrical control queue fill in % tracked per state change
	cStdDev opticalQueueSize; // optical data queue fill in % tracked per state change
	cOutVector controlQueueSizeVec; // electrical control queue fill samples
	cOutVector opticalQueueSizeVec; // optical data queue fill samples
	cStdDev opticalPathHopCount; // optical packet path length in hops
	cStdDev opticalPathWavelengthCount; // number of wavelengths assigned to an optical packet
	cStdDev opticalPathInsertionLossDb; // accumulated insertion loss in dB
	cStdDev opticalPathCrosstalkLossDb; // accumulated crosstalk loss in dB
	cStdDev opticalPathTotalLossDb; // total optical path loss in dB
	cStdDev opticalPathReceivedPowerDbm; // estimated received optical power in dBm
	cStdDev opticalPathMarginDb; // received power minus sensitivity in dB
	cStdDev opticalPathSNRDb; // estimated SNR in dB (device-level)
	cStdDev opticalPathBER; // estimated BER (device-level)
	cStdDev opticalPathModulatorLossDb; // modulator loss in dB
	cStdDev opticalPathMuxDemuxLossDb; // MUX+DEMUX loss in dB
	cStdDev opticalPathWaveguideLossDb; // waveguide propagation loss in dB
	cStdDev opticalPathBendingLossDb; // waveguide bending loss in dB
	cStdDev opticalPathRingThroughLossDb; // ring through loss in dB
	cStdDev opticalPathRingDropLossDb; // ring drop loss in dB
	cStdDev opticalPathSOAGainDb; // total SOA gain in dB
	cStdDev opticalPathDetectorLossDb; // photodetector loss in dB
	cStdDev numSentPkt; // number of sent packets, assume that there is only single destination
	cStdDev numGenPkt; // number of generated packets, for loss probability
	cStdDev numQPkt; // number of queued packets, for loss probability
	cStdDev lossProb; // probability to throw packet i.e. source queue is full and therefore the packet is discarded

	// methods
	void sendControlFlitFromQ();
	void sendOpticalFlitFromQ();
	bool enqueuePacket(int dst, int pktLen, int vc, int packetClass, int spatialChannel,
			int wavelengthMask, int circuitToken, const char *namePrefix);
	void ensureDstStateSize(int dst);
	cSimpleModule *getDestinationSinkModule(int dst) const;
	int meshHopDistance(int srcId, int dstId) const;
	int countSetBits(int value) const;
	void recordQueueStats();
	simtime_t computeOpticalPropagationDelay(int srcId, int dstId) const;
	simtime_t computeOpticalTxDuration(const NoCFlitMsg *flit) const;
	bool sendFlitDirectToSink(NoCFlitMsg *flit);
	void applyFlitVisualStyle(NoCFlitMsg *flit, int packetClass, bool opticalQueue) const;
	bool tryReserveSetupPath(int dst, int &token, int &spatialChannel, int &wavelengthMask);
	void handleGenMsg(cMessage *msg);
	void handleCreditMsg(NoCCreditMsg *msg);
	void handleControlPopMsg(cMessage *msg);
	void handleOpticalPopMsg(cMessage *msg);
	void handleVisualCleanup(cMessage *msg);
	void handleControlEvent(int eventType, int requesterId, int targetId, int token,
			int spatialChannel, int wavelengthMask);
	void drawTransientTrafficLine(int dstId, bool opticalData);
	void purgeControlFlitsForSetup(int token);
	void scheduleOpticalRelease(int token, simtime_t delay);
	void handleOpticalRelease(cMessage *msg);

protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
    virtual void finish();
    virtual void receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details);

public:
    virtual ~PktFifoSrc();
};

#endif
