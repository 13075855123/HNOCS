package hnocs.onoc.optical;

simple OpticalCircuitController
{
    parameters:
        int rows;
        int columns;
        bool logCircuitEvents = default(true);
        @display("i=block/network");
            bool remapToDynamic = default(false); // deprecated, IDE compat            double wTemperature = default(1.0);   // deprecated            double wHopCount = default(0.5);      // deprecated}
