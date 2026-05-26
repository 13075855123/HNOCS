package hnocs.onoc.optical;

simple OpticalCircuitController
{
    parameters:
        int rows;
        int columns;
        bool logCircuitEvents = default(true);
        @signal[onoc-setup-ack-event](long);
        @signal[onoc-data-release-event](long);
        @signal[onoc-optical-path-open-event](long);
        @signal[onoc-optical-path-close-event](long);
        @display("i=block/network");

        // Deprecated (retained for IDE compat)
        bool remapToDynamic = default(false);
        double wTemperature = default(1.0);
        double wHopCount = default(0.5);
}

