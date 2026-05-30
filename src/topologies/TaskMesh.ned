//
// Copyright (C) 2024 HNOCS Project
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//

package hnocs.topologies;

import hnocs.routers.Router_Ifc;
import hnocs.cores.task.TaskPE;
import hnocs.globalbuffer.GlobalBuffer;

channel TaskLink extends ned.DatarateChannel
{
    datarate = 16Gbps;
    delay    = 0us;
}

network TaskMesh
{
    parameters:
        string routerType;
        string coreType = default("hnocs.cores.task.TaskPE");
        int columns = default(4);
        int rows    = default(4);

        string bufferApplication = default("cnn_inference");
        int    bufferBaseId      = default(1000);

        // RC thermal model parameters
        double RconvPE        = default(10);      // K/W
        double RconvRouter    = default(10);      // K/W
        double RlateralPE     = default(10);      // K/W
        double RlateralRouter = default(10);      // K/W
        double Rpe2router     = default(3);       // K/W
        double Cpe            = default(1e-6);    // J/K
        double Crouter        = default(1e-7);    // J/K
        double Tambient       = default(318.15);  // K

        // DVFS thermal throttling
        double Tthrottle      = default(326.15);  // K (53°C)
        double throttleBeta   = default(0.1);     // 1/K, slowdown per degree above threshold

        @display("bgb=750,700");

        // Deprecated (retained for IDE compat)
        bool remapToDynamic = default(false);
        double wTemperature = default(1.0);
        double wHopCount = default(0.5);

    submodules:
        router[columns*rows]: <routerType> like Router_Ifc {
            parameters:
                numPorts = 5;
                id       = index;
                @display("p=100,100,matrix,$columns,140,140");
            gates:
                in[5];
                out[5];
        }

        pe[columns*rows]: TaskPE {
            parameters:
                id = index;
                @display("p=140,140,matrix,$columns,140,140");
        }

        globalBuffer: GlobalBuffer {
            parameters:
                numConnections = parent.rows;
                application    = parent.bufferApplication;
                baseId         = parent.bufferBaseId;
                @display("p=40,200;i=block/buffer");
        }

    connections allowunconnected:
        for r=0..rows-1, for c=0..columns-1 {
            router[r*columns+c].in[2]  <--> TaskLink <--> router[(r+1)*columns+c].out[0] if r!=rows-1;
            router[r*columns+c].out[2] <--> TaskLink <--> router[(r+1)*columns+c].in[0]  if r!=rows-1;

            router[r*columns+c].in[3]  <--> TaskLink <--> router[r*columns+c+1].out[1] if c!=columns-1;
            router[r*columns+c].out[3] <--> TaskLink <--> router[r*columns+c+1].in[1]  if c!=columns-1;

            router[r*columns+c].in[4]  <--> TaskLink <--> pe[r*columns+c].out;
            router[r*columns+c].out[4] <--> TaskLink <--> pe[r*columns+c].in;

            globalBuffer.out[r] <--> TaskLink <--> router[r*columns].in[1]  if c==0;
            globalBuffer.in[r]  <--> TaskLink <--> router[r*columns].out[1] if c==0;
        }
}
