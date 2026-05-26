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

package hnocs.cores.sources;

//
// Message Source with Packet Fifo's
//
simple PktFifoSrc like Source_Ifc 
{
    parameters:
        int             srcId;                       // must be globally unique
        volatile int    pktVC;                       // the VC to be used for packets
        volatile int    dstId;                       // the packet destination 
        volatile int    pktLen;                      // packet length in FLITs
        volatile int 	msgLen;                      // how many packets will be sent to same dst 
        volatile double flitArrivalDelay @unit(s);   // Inter Flit delay [sec] 
        int             flitSize @unit(byte);        // FLIT size [bytes]
        int             maxQueuedPkts;               // Max number of packets that can be queued
        double          statStartTime @unit(s);      // start time for recording statistics [sec]
        bool            isSynchronous;               // If true will send on clock (defived link BW)
        bool			isTrace; 					 // If true uses a trace file for flitArrivalDelay
        string 			fileName;					 // trace filename
        bool            enableSetupHandshake = default(false); // when true, send setup request and wait for ACK before data
        bool            singlePacketPerMessage = default(false); // when true, force msgLen=1
        int             setupControlPktLen = default(2); // setup/ack control packet size in flits
        int             dataPktLenWhenHandshake = default(2); // data packet size while handshake mode is enabled
        double          setupRetryDelay @unit(s) = default(20ns); // retry period for setup request
        double          setupPendingTimeout @unit(s) = default(2us); // timeout before abandoning a pending setup and retrying
        bool            enableOpticalBypass = default(false); // when true, data packets bypass routers via direct optical path
        bool            enableTrafficVisualization = default(true); // visualize setup/ack(data bypass) traffic in QtEnv
        double          visualLinkHoldTime @unit(s) = default(50ns); // transient visualization line lifetime
        int             opticalRequiredWavelengths = default(2); // required wavelengths per optical data transfer
        double          opticalWavelengthBitrate @unit(bps) = default(256Gbps); // bitrate per wavelength
        double          opticalBasePropagationDelay @unit(s) = default(100ps); // fixed optical propagation latency
        double          opticalPerTorusHopDelay @unit(s) = default(20ps); // extra propagation delay per torus hop of physical span
        int             opticalBurstSize = default(1); // number of data packets per circuit setup (1=legacy, >1=burst)
           
        @signal[onoc-setup-req-event](long);
        @signal[onoc-setup-ack-event](long);
    @display("i=block/source");
        // Deprecated (retained for IDE compat)
        bool remapToDynamic = default(false);
        double wTemperature = default(1.0);
        double wHopCount = default(0.5);

    gates: 
        inout out;
}
