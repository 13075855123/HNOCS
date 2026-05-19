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
        int initialCredits = default(4);
        string csvFile = default("");
        double wTemperature = default(1.0);
        double wHopCount    = default(0.5);
        bool remapToDynamic = default(false);
        @display("i=block/buffer");
    gates:
        inout in[numConnections];
        inout out[numConnections];
}
