//
// Copyright (C) 2010-2011 Eitan Zahavi, The Technion EE Department
// Copyright (C) 2010-2011 Yaniv Ben-Itzhak, The Technion EE Department
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

package hnocs.routers.hier.inPort;

simple InPortSync like InPort_Ifc
{
    parameters:
        int numVCs;
        int flitsPerVC;
        int rows;
        int columns;
        bool collectPerHopWait;
        double statStartTime @unit(s);

        // NEW: InPort energy model
        double energyWindow @unit(s) = default(100ns);
        bool   enableEnergyWindow = default(true);
        double eBufferWrite @unit(J) = default(1e-12J);
        double eBufferRead  @unit(J) = default(1e-12J);
        double eCrossbar    @unit(J) = default(0.5e-12J);
        double pLeak        @unit(W) = default(1e-3W);

        @display("i=block/subqueue");
            bool remapToDynamic = default(false); // deprecated, IDE compat            double wTemperature = default(1.0);   // deprecated            double wHopCount = default(0.5);      // deprecated    gates:
        inout in;
        output out[];
        inout ctrl[];
        inout calcVc;
        inout calcOp;
}