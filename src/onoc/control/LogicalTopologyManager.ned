package hnocs.onoc.control;

simple LogicalTopologyManager
{
    parameters:
    int rows;                              // Physical torus rows
    int columns;                           // Physical torus columns
    string initialTopology = default("torus"); // Initial logical topology
    string physicalTopology = default("mesh");   // Physical topology: "mesh" or "torus" for path computation
    string ringMode = default("snake");        // Ring order: snake or id
    string topologySwitches = default("");     // Runtime switch script: "t1:mesh;t2:ring"
    int starCenterId = default(0);              // Star/Tree root node id
    int starLeafLimit = default(-1);            // Star max leaves; <=0 means all leaves
    string starLeafOrderMode = default("physical"); // Star leaf selection: physical or id
    int defaultOpticalWavelengths = default(2); // Default wavelengths per source-destination pair
    int maxOpticalWavelengths = default(16);    // Hard cap for configured wavelengths per pair
    int numOpticalSpatialChannels = default(1); // Number of spatial channels per physical link
    double opticalLaunchPower_dBm = default(0.0); // Optical launch power used for budget accounting
    double opticalReceiverSensitivity_dBm = default(-18.0); // Receive sensitivity threshold in dBm
    double opticalSourceModulatorLoss_dB = default(0.0); // Source-side modulator loss in dB
    double opticalHopInsertionLoss_dB = default(0.0); // Per-hop insertion loss in dB
    double opticalHopCrosstalkLoss_dB = default(0.0); // Per-hop equivalent crosstalk loss in dB
    double opticalReceiverDemodulatorLoss_dB = default(0.0); // Destination-side demodulator loss in dB
    string opticalDeviceParamsFile = default(""); // CSV file with per-device per-wavelength parameters
    int opticalNumSplitBranches = default(16);    // 1×N splitter branch count (== PE count)
    double opticalSplitterExcessLoss_dB = default(1.0); // Splitter excess loss in dB
    double opticalCouplingLoss_dB = default(3.0);       // Grating coupler loss in dB
    double opticalWaveguideMaxPower_dBm = default(14.0); // Waveguide damage threshold
    double opticalThermalNoiseFloor_dBm = default(-50.0); // Thermal noise floor per wavelength
    int opticalModulationBitsPerSymbol = default(2); // 1=OOK, 2=PAM4
    bool opticalEnableSOA = default(true); // Whether SOAs are present on the path
    bool enableBudgetBasedRerouting = default(false); // Trigger reroute when budget fails
    double rerouteMarginThreshold_dB = default(3.0); // Min margin before triggering reroute
    double opticalWaveguideNItoRouter_cm = default(0.03); // NI<->Router waveguide length
    double opticalWaveguideRouterToRouter_cm = default(0.15); // Inter-router waveguide length
    double opticalWaveguideSourceToMod_cm = default(0.01); // Source->Modulator waveguide
    double opticalWaveguideDemodToPD_cm = default(0.005); // Demodulator->PD waveguide
    bool opticalEnableDemodCrosstalk = default(true); // Enable demod-side crosstalk modelling
    string opticalPairWavelengthOverrides = default(""); // "src->dst:wl;src->dst:wl"
    bool logOpticalAllocDecisions = default(false); // Log parsed pair wavelength requirements
    bool logTopologyTransitions = default(true); // Enable transition logs
    string opticalWavelengthStrategy = default("lowest"); // "lowest" or "thermal"
    // Temperature-aware optical effects
    bool opticalEnableThermalEffects = default(false);
    double opticalTambient_K = default(318.15);
    double opticalThermoOpticCoeff_nm_per_K = default(0.1);
    double opticalTuningEfficiency_mW_per_nm = default(0.5);
    double opticalSoaPumpPower_mW = default(80.0);   // SOA electrical pump power per device (256 Gbps PAM4: ~80 mW for 13 dB gain, 128 GBaud)
    double opticalLaserWPE = default(0.20);          // Laser wall-plug efficiency (0=disabled). P_elec = P_opt / WPE. Off-chip: not in thermal model
    double opticalRingIL_TempCoeff_dB_per_K = default(0.02);
    double opticalSoaGain_TempCoeff_dB_per_K = default(0.05);
    double opticalWaveguideLoss_TempCoeff_dB_per_cm_per_K = default(0.001);
        // Baseline microring thermal tuning — static always-on power per ring
        double opticalRingTuningPower_mW_per_ring = default(2.0);
        int opticalNumRingsPerRouter = default(160);
        @display("i=block/cogwheel");

        // Deprecated (retained for IDE compat)
        bool remapToDynamic = default(false);
        double wTemperature = default(1.0);
        double wHopCount = default(0.5);
}

