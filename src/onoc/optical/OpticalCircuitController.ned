package hnocs.onoc.optical;

simple OpticalCircuitController
{
    parameters:
        int rows;
        int columns;
        bool logCircuitEvents = default(true);
        @display("i=block/network");
}
