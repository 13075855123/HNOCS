//
// Copyright (C) 2024 HNOCS Project
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//

package hnocs.globalbuffer;

simple GlobalBuffer
{
    parameters:
        int numConnections;
        int numVCs = default(2);
        int flitSize @unit(byte) = default(16B);
        string application = default("cnn_inference");
        int baseId = default(1000);
        int initialCredits = default(8);
        string csvFile = default("");
        bool enableSetupHandshake = default(false);
        bool enableOpticalBypass = default(false);
        double setupRetryDelay @unit(s) = default(50ns);
        double setupPendingTimeout @unit(s) = default(2us);
        int opticalRequiredWavelengths = default(2);
        double opticalWavelengthBitrate @unit(bps) = default(256Gbps);
        double opticalBasePropagationDelay @unit(s) = default(0.5ns);
        double opticalPerHopDelay @unit(s) = default(0.1ns);
        @display("i=block/buffer");
    gates:
        inout in[numConnections];
        inout out[numConnections];
        input opticalIn @directIn;
}
