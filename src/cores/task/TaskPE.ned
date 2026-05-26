//
// Copyright (C) 2024 HNOCS Project
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

package hnocs.cores.task;

simple TaskPE like hnocs.cores.NI_Ifc
{
    parameters:
        int id;
        int numVCs = default(2);
        int flitSize @unit(byte) = default(4B);
        double statStartTime @unit(s) = default(1us);

        string application = default("matrix_multiply");
        string csvFile = default("");
        int    bufferBaseId = default(1000);

        double powerIdle    @unit(W) = default(0.1W);
        double powerCompute @unit(W) = default(2.0W);
        double powerSendPerFlit @unit(J) = default(0.1e-9 J);
        double powerRecvPerFlit @unit(J) = default(0.05e-9 J);

        bool   enablePowerTrace    = default(true);
        string powerTraceFile      = default("results/power_trace.csv");
        string hotspotTraceFile    = default("");
        double powerSampleInterval @unit(s) = default(1us);

        // NEW
        double energyWindow @unit(s) = default(100ns);
        bool   enableEnergyWindow = default(true);

        double computeDensity = default(0);

        // Optical bypass parameters
        bool enableSetupHandshake = default(false);
        bool enableOpticalBypass = default(false);
        double setupRetryDelay @unit(s) = default(50ns);
        double setupPendingTimeout @unit(s) = default(200ns);
        int opticalRequiredWavelengths = default(2);
        double opticalWavelengthBitrate @unit(bps) = default(256Gbps);
        double opticalBasePropagationDelay @unit(s) = default(0.5ns);
        double opticalPerHopDelay @unit(s) = default(0.1ns);
        int opticalBurstSize = default(1);
        double opticalModulatorEnergyPerFlit @unit(J) = default(2e-12 J);
        double opticalReceiverEnergyPerFlit  @unit(J) = default(1e-12 J);

        @signal[onoc-setup-req-event](type=long);
        @signal[onoc-setup-ack-event](type=long);
        @display("i=block/process");

    gates:
        inout in;
        inout out;
        input opticalIn @directIn;
}