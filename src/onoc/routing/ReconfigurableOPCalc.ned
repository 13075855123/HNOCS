package hnocs.onoc.routing;

simple ReconfigurableOPCalc like hnocs.routers.hier.opCalc.OPCalc_Ifc
{
    parameters:
        string portType;                               // Router port module type for reflection lookup
        string coreType;                               // Core module type for local-core port detection
        string topologyManagerName = default("topologyManager"); // Manager submodule name in network
        bool enableOpticalWavelengthPlanning = default(true); // Query required wavelengths per src-dst pair
        bool enforceOpticalWavelengthCap = default(false); // Throw error if required wavelengths exceed available
        bool dropPacketOnWavelengthShortage = default(false); // Drop packet at source when allocation fails due to insufficient resources
        int availableOpticalWavelengths = default(2); // Available wavelengths per optical connection
        @display("i=block/fork");
            bool remapToDynamic = default(false); // deprecated, IDE compat            double wTemperature = default(1.0);   // deprecated            double wHopCount = default(0.5);      // deprecated    gates:
        inout calc; // Receives flits from InPort and returns chosen output port via control info
}
