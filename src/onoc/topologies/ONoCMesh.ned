//
// Copyright (C) 2010-2011 Eitan Zahavi, The Technion EE Department
// Copyright (C) 2010-2011 Yaniv Ben-Itzhak, The Technion EE Department
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//

package hnocs.onoc.topologies;

import hnocs.cores.task.TaskPE;
import hnocs.globalbuffer.GlobalBuffer;
import hnocs.onoc.control.LogicalTopologyManager;
import hnocs.onoc.optical.OpticalCircuitController;
import hnocs.routers.Router_Ifc;

// Physical link model used by router-router and router-core connections.
channel MeshOpticalLink extends ned.DatarateChannel
{
    datarate = default(16Gbps);
    delay = default(0us);
}

// Fixed physical Mesh network with runtime-switchable logical topology manager
// and device-level optical budget modelling.
network ONoCMesh
{
    parameters:
        string routerType;
        string coreType;
        int columns = default(4);
        int rows = default(4);

        // ── Logical topology ──
        string initialTopology = default("mesh");
        string topologySwitches = default("");
        string physicalTopology = default("mesh");
        int starCenterId = default(0);
        int starLeafLimit = default(-1);
        string starLeafOrderMode = default("physical");

        // ── Optical layer ──
        int defaultOpticalWavelengths = default(2);
        int maxOpticalWavelengths = default(16);
        int numOpticalSpatialChannels = default(1);
        double opticalLaunchPower_dBm = default(0.0);
        int opticalNumSplitBranches = default(16);
        double opticalSplitterExcessLoss_dB = default(1.0);
        double opticalCouplingLoss_dB = default(3.0);
        double opticalReceiverSensitivity_dBm = default(-18.0);
        double opticalSourceModulatorLoss_dB = default(0.0);
        double opticalHopInsertionLoss_dB = default(0.0);
        double opticalHopCrosstalkLoss_dB = default(0.0);
        double opticalReceiverDemodulatorLoss_dB = default(0.0);
        string opticalDeviceParamsFile = default("");
        double opticalWaveguideMaxPower_dBm = default(14.0);
        double opticalThermalNoiseFloor_dBm = default(-50.0);
        int opticalModulationBitsPerSymbol = default(2);
        bool opticalEnableSOA = default(true);
        bool enableBudgetBasedRerouting = default(false);
        double rerouteMarginThreshold_dB = default(3.0);
        double opticalWaveguideNItoRouter_cm = default(0.03);
        double opticalWaveguideRouterToRouter_cm = default(0.15);
        double opticalWaveguideSourceToMod_cm = default(0.01);
        double opticalWaveguideDemodToPD_cm = default(0.005);
        bool opticalEnableDemodCrosstalk = default(true);
        string opticalPairWavelengthOverrides = default("");
        bool logOpticalAllocDecisions = default(false);
        bool enableOpticalCircuitController = default(false);
        bool logOpticalCircuitEvents = default(true);

        // ── RC thermal model ──
        double RconvPE = default(10);
        double RconvRouter = default(10);
        double RlateralPE = default(10);
        double RlateralRouter = default(10);
        double Rpe2router = default(3);
        double Cpe = default(1e-6);
        double Crouter = default(1e-7);
        double Tambient = default(318.15);

        // ── DVFS thermal throttling ──
        double Tthrottle = default(326.15);
        double throttleBeta = default(0.1);

        // ── Task-driven ──
        string csvFile = default("tasks_mpeg4_static.csv");
        int bufferBaseId = default(1000);

        // Deprecated (retained for IDE compat)
        bool remapToDynamic = default(false);
        double wTemperature = default(1.0);
        double wHopCount = default(0.5);

    submodules:
        // TaskPE per router — MUST come first so pe[0].initialize() calls
        // ThermalModel::open() BEFORE topologyManager adds ring tuning power.
        pe[columns * rows]: TaskPE {
            parameters:
                id = index;
                @display("p=150,150,matrix,$columns,150,150");
        }

        // Central manager that owns the logical adjacency graph A(t).
        topologyManager: LogicalTopologyManager {
            parameters:
                rows = parent.rows;
                columns = parent.columns;
                initialTopology = parent.initialTopology;
                physicalTopology = parent.physicalTopology;
                topologySwitches = parent.topologySwitches;
                starCenterId = parent.starCenterId;
                starLeafLimit = parent.starLeafLimit;
                starLeafOrderMode = parent.starLeafOrderMode;
                defaultOpticalWavelengths = parent.defaultOpticalWavelengths;
                maxOpticalWavelengths = parent.maxOpticalWavelengths;
                numOpticalSpatialChannels = parent.numOpticalSpatialChannels;
                opticalLaunchPower_dBm = parent.opticalLaunchPower_dBm;
                opticalNumSplitBranches = parent.opticalNumSplitBranches;
                opticalSplitterExcessLoss_dB = parent.opticalSplitterExcessLoss_dB;
                opticalCouplingLoss_dB = parent.opticalCouplingLoss_dB;
                opticalReceiverSensitivity_dBm = parent.opticalReceiverSensitivity_dBm;
                opticalSourceModulatorLoss_dB = parent.opticalSourceModulatorLoss_dB;
                opticalHopInsertionLoss_dB = parent.opticalHopInsertionLoss_dB;
                opticalHopCrosstalkLoss_dB = parent.opticalHopCrosstalkLoss_dB;
                opticalReceiverDemodulatorLoss_dB = parent.opticalReceiverDemodulatorLoss_dB;
                opticalDeviceParamsFile = parent.opticalDeviceParamsFile;
                opticalWaveguideMaxPower_dBm = parent.opticalWaveguideMaxPower_dBm;
                opticalThermalNoiseFloor_dBm = parent.opticalThermalNoiseFloor_dBm;
                opticalModulationBitsPerSymbol = parent.opticalModulationBitsPerSymbol;
                opticalEnableSOA = parent.opticalEnableSOA;
                enableBudgetBasedRerouting = parent.enableBudgetBasedRerouting;
                rerouteMarginThreshold_dB = parent.rerouteMarginThreshold_dB;
                opticalWaveguideNItoRouter_cm = parent.opticalWaveguideNItoRouter_cm;
                opticalWaveguideRouterToRouter_cm = parent.opticalWaveguideRouterToRouter_cm;
                opticalWaveguideSourceToMod_cm = parent.opticalWaveguideSourceToMod_cm;
                opticalWaveguideDemodToPD_cm = parent.opticalWaveguideDemodToPD_cm;
                opticalEnableDemodCrosstalk = parent.opticalEnableDemodCrosstalk;
                opticalPairWavelengthOverrides = parent.opticalPairWavelengthOverrides;
                logOpticalAllocDecisions = parent.logOpticalAllocDecisions;
                @display("p=40,40;i=block/cogwheel");
        }

        // Control-plane stub for ACK-driven optical circuit setup/release bookkeeping.
        opticalController: OpticalCircuitController if enableOpticalCircuitController {
            parameters:
                rows = parent.rows;
                columns = parent.columns;
                logCircuitEvents = parent.logOpticalCircuitEvents;
                @display("p=190,40;i=block/network");
        }

        // Physical routers arranged on a rows x columns grid.
        router[columns * rows]: <routerType> like Router_Ifc {
            parameters:
                numPorts = 5;
                id = index;
                @display("p=100,100,matrix,$columns,150,150");
            gates:
                in[5];
                out[5];
        }

        // GlobalBuffer for task distribution
        globalBuffer: GlobalBuffer {
            parameters:
                numConnections = parent.rows;
                application = "task_driven";
                baseId = parent.bufferBaseId;
                @display("p=40,200;i=block/buffer");
        }

    connections allowunconnected:
        for r=0..rows-1, for c=0..columns-1 {
            // South-North (all but last row — no wrap in Mesh)
            router[r*columns+c].in[2]  <--> MeshOpticalLink <--> router[(r+1)*columns+c].out[0] if r!=rows-1;
            router[r*columns+c].out[2] <--> MeshOpticalLink <--> router[(r+1)*columns+c].in[0]  if r!=rows-1;
            // East-West (all but last column — no wrap in Mesh)
            router[r*columns+c].in[3]  <--> MeshOpticalLink <--> router[r*columns+c+1].out[1] if c!=columns-1;
            router[r*columns+c].out[3] <--> MeshOpticalLink <--> router[r*columns+c+1].in[1]  if c!=columns-1;
            // Router-PE local attachment
            router[r*columns+c].in[4]  <--> MeshOpticalLink <--> pe[r*columns+c].out;
            router[r*columns+c].out[4] <--> MeshOpticalLink <--> pe[r*columns+c].in;

            // GlobalBuffer connections to west port of column-0 routers
            globalBuffer.out[r] <--> MeshOpticalLink <--> router[r*columns].in[1]  if c==0;
            globalBuffer.in[r]  <--> MeshOpticalLink <--> router[r*columns].out[1] if c==0;
        }
}
