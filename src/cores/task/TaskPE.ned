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

//
// Task-driven Processing Element.
//
// Implements the NI_Ifc interface so that it can be used as a drop-in
// replacement for the random-traffic source+sink pair in any topology.
//
simple TaskPE like hnocs.cores.NI_Ifc
{
    parameters:
        int id;
        int numVCs = default(2);
        int flitSize @unit(byte) = default(4B);
        double statStartTime @unit(s) = default(1us);

        string application = default("matrix_multiply");

        double powerIdle    @unit(W) = default(0.1W);
        double powerCompute @unit(W) = default(2.0W);
        double powerSendPerFlit @unit(J) = default(0.1e-9 J);
        double powerRecvPerFlit @unit(J) = default(0.05e-9 J);

        bool   enablePowerTrace    = default(true);
        string powerTraceFile      = default("results/power_trace.csv");
        string hotspotTraceFile    = default("results/hotspot_power.trace");
        double powerSampleInterval @unit(s) = default(1us);


        @display("i=block/process");

    gates:
        inout in;
        inout out;
}