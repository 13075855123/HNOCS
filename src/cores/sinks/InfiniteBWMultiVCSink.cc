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

// Behavior
// This sink is simple - it assumes NO delay on receiving packets
// so on the received FLIT a credit is generated.
//
// PktId check is valid only for single source .
//
#include "InfiniteBWMultiVCSink.h"

Define_Module(InfiniteBWMultiVCSink)
;

void InfiniteBWMultiVCSink::initialize() {
	numVCs = par("numVCs");
	coreId = getParentModule()->par("id").intValue();
	setupReqEventSignal = registerSignal("onoc-setup-req-event");
	setupAckEventSignal = registerSignal("onoc-setup-ack-event");
	dataReleaseEventSignal = registerSignal("onoc-data-release-event");

	end2EndLatency.setName("end-to-end-latency-ns"); // end-to-end latency per flit
	networkLatency.setName("network-latency-ns"); // network-latency per flit
	packetLatency.setName("packet-network-latency-ns"); // network-latency per packet

	// statistics for head-flits only
	SoPEnd2EndLatency.setName("SoP-end-to-end-latency-ns");
	SoPLatency.setName("SoP-network-latency-ns");
	SoPQTime.setName("SoP-queueing-time-ns");

	// statistics for tail-flits only
	EoPEnd2EndLatency.setName("EoP-end-to-end-latency-ns");
	EoPLatency.setName("EoP-network-latency-ns");
	EoPQTime.setName("EoP-queueing-time-ns");

	numReceivedPkt.setName("number-received-packets");

	// Vectors
	end2EndLatencyVec.setName("end-to-end-latency-ns");

	numRecPkt = 0;

	vcFLITs.resize(numVCs, 0);
	statStartTime = par("statStartTime");

	// send the credits to the other size
	for (int vc = 0; vc < numVCs; vc++)
		sendCredit(vc, 100);

	SoPEnd2EndLatencyHist.setName("SoP-E2E-Latency-Hist");
	SoPEnd2EndLatencyHist.setMode(cHistogram::MODE_INTEGERS);
}

void InfiniteBWMultiVCSink::sendCredit(int vc, int num) {
	char credName[64];
	sprintf(credName, "cred-%d-%d", vc, 1);
	NoCCreditMsg *crd = new NoCCreditMsg(credName);
	crd->setKind(NOC_CREDIT_MSG);
	crd->setVC(vc);
	crd->setFlits(num);
	send(crd, "in$o");
}

void InfiniteBWMultiVCSink::handleMessage(cMessage *msg) {
	NoCFlitMsg *flit = dynamic_cast<NoCFlitMsg*> (msg);
	if (!flit) {
		throw cRuntimeError("InfiniteBWMultiVCSink expects NoCFlitMsg, got kind=%d", msg->getKind());
	}

	int vc = flit->getVC();
	bool arrivedViaOptical = hasGate("opticalIn")
			&& msg->getArrivalGateId() == gate("opticalIn")->getId();
	int pktClass = 0;
	int spatialChannel = 0;
	int wavelengthMask = 0;
	onocDecodePacketTag(flit->getSL(), pktClass, spatialChannel, wavelengthMask);
	bool isDataPacket = (pktClass == ONOC_PKT_DATA);
	int token = flit->getPktId();

	if (flit->getType() == NOC_START_FLIT && pktClass == ONOC_PKT_SETUP_REQ) {
		emit(setupReqEventSignal,
				onocEncodeControlEvent(ONOC_EVT_SETUP_REQ,
						flit->getSrcId(),
						coreId,
						token,
						spatialChannel,
						wavelengthMask));
	}
	if (flit->getType() == NOC_START_FLIT && pktClass == ONOC_PKT_SETUP_ACK) {
		emit(setupAckEventSignal,
				onocEncodeControlEvent(ONOC_EVT_SETUP_ACK,
						coreId,
						flit->getSrcId(),
						token,
						spatialChannel,
						wavelengthMask));
	}
	if (flit->getType() == NOC_END_FLIT && isDataPacket && token > 0) {
		emit(dataReleaseEventSignal,
				onocEncodeControlEvent(ONOC_EVT_DATA_EOP_RELEASE,
						flit->getSrcId(),
						coreId,
						token,
						spatialChannel,
						wavelengthMask));
	}

	if (isDataPacket && flit->getType() == NOC_START_FLIT) {
		auto inserted = expectedFlitIdxByPktId.emplace(flit->getPktId(), 0);
		if (!inserted.second) {
			throw cRuntimeError(
					"-E- BUG - duplicate SoP for pktId %d at sink %s",
					flit->getPktId(), getFullPath().c_str());
		}
	}

	if (isDataPacket) {
		int pktId = flit->getPktId();
		auto expectedIt = expectedFlitIdxByPktId.find(pktId);
		if (expectedIt == expectedFlitIdxByPktId.end()) {
			throw cRuntimeError(
					"-E- BUG - received non-start flit for unknown pktId %d at sink %s",
					pktId, getFullPath().c_str());
		}
		if (expectedIt->second != flit->getFlitIdx()) {
			throw cRuntimeError(
					"-E- BUG - Received flit Index %d but expecting flit index %d for pktId %d",
					flit->getFlitIdx(), expectedIt->second, pktId);
		}
		expectedIt->second++;
		if (flit->getType() == NOC_END_FLIT) {
			expectedFlitIdxByPktId.erase(pktId);
		}
	}

	if (!arrivedViaOptical) {
		sendCredit(vc, 1);
	}

	// some statistics, now tracked per packet id so optical bypass can interleave packets safely
	if (isDataPacket && simTime() > statStartTime) {
		vcFLITs[vc]++;

		if (flit->getFirstNet()) {
			throw cRuntimeError(
					"-E- BUG - received flit on vc %d, but firstNet flag set is true !",
					vc);
		}

		double eed = (simTime().dbl() - msg->getCreationTime().dbl());
		double d = (simTime().dbl() - flit->getFirstNetTime().dbl());
		double eed_ns = eed * 1e9;
		double d_ns = d * 1e9;

		end2EndLatency.collect(eed_ns);
		networkLatency.collect(d_ns);
		end2EndLatencyVec.record(eed_ns);

		int pktId = flit->getPktId();
		if (flit->getType() == NOC_START_FLIT) {
			if (simTime() > statStartTime) {
				SoPEnd2EndLatency.collect(eed_ns);
				SoPEnd2EndLatencyHist.collect(eed_ns);
				SoPLatency.collect(d_ns);
				SoPQTime.collect(1e9 * (flit->getInjectTime().dbl() - msg->getCreationTime().dbl()));

				firstNetTimeByPktId[pktId] = flit->getFirstNetTime();
				numRecPkt++;
			}
		}

		if (flit->getType() == NOC_END_FLIT) {
			EoPEnd2EndLatency.collect(eed_ns);
			EoPLatency.collect(d_ns);
			EoPQTime.collect(1e9 * (flit->getInjectTime().dbl() - msg->getCreationTime().dbl()));
			auto firstNetIt = firstNetTimeByPktId.find(pktId);
			if (firstNetIt != firstNetTimeByPktId.end()) {
				packetLatency.collect(1e9 * (simTime().dbl() - firstNetIt->second.dbl()));
			}
			firstNetTimeByPktId.erase(pktId);
			expectedFlitIdxByPktId.erase(pktId);
		}
	}

	delete msg;
}

void InfiniteBWMultiVCSink::finish() {
	char name[32];
	double totalFlits = 0;
	int flitSize_B = par("flitSize"); // in bytes
	for (int vc = 0; vc < numVCs; vc++) {
		sprintf(name, "flit-per-vc-%d", vc);
		recordScalar(name, vcFLITs[vc]);
		totalFlits += vcFLITs[vc];
	}
	if (simTime() > statStartTime) {
		SoPEnd2EndLatency.record();
		SoPEnd2EndLatencyHist.record();
		SoPLatency.record();
		SoPQTime.record();
		EoPEnd2EndLatency.record();
		EoPLatency.record();
		EoPQTime.record();

		packetLatency.record();
		networkLatency.record();
		end2EndLatency.record();

		numReceivedPkt.collect(numRecPkt);
		numReceivedPkt.record();
		double BW_MBps = 1e-6 * totalFlits * flitSize_B / (simTime().dbl()- statStartTime);
		recordScalar("Sink-Total-BW-MBps", BW_MBps);
	}
}
