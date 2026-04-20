//
// Copyright (C) 2024 HNOCS Project
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

package hnocs.topologies;

import hnocs.routers.Router_Ifc;
import hnocs.cores.task.TaskPE;

//
// Shared link channel for the task mesh (same parameters as Mesh.ned).
//
channel TaskLink extends ned.DatarateChannel
{
    datarate = 16Gbps;
    delay    = 0us;
}

//
// A 2-D mesh network whose processing elements are task-driven TaskPEs.
//
// Port numbering on routers (same as Mesh.ned):
//   0 = north, 1 = west, 2 = south, 3 = east, 4 = PE
//
network TaskMesh
{
    parameters:
        string routerType;
        int columns = default(4);
        int rows    = default(4);

        @display("bgb=800,600");

    submodules:
        router[columns*rows]: <routerType> like Router_Ifc {
            parameters:
                numPorts = 5;
                id       = index;
                @display("p=100,100,matrix,$columns,150,150");
            gates:
                in[5];
                out[5];
        }

        pe[columns*rows]: TaskPE {
            parameters:
                id = index;
                @display("p=150,150,matrix,$columns,150,150");
        }

    connections allowunconnected:
        for r=0..rows-1, for c=0..columns-1 {
            // south–north links (ports 2 and 0)
            router[r*columns+c].in[2]  <--> TaskLink <--> router[(r+1)*columns+c].out[0] if r!=rows-1;
            router[r*columns+c].out[2] <--> TaskLink <--> router[(r+1)*columns+c].in[0]  if r!=rows-1;

            // east–west links (ports 3 and 1)
            router[r*columns+c].in[3]  <--> TaskLink <--> router[r*columns+c+1].out[1] if c!=columns-1;
            router[r*columns+c].out[3] <--> TaskLink <--> router[r*columns+c+1].in[1]  if c!=columns-1;

            // PE ↔ router (port 4)
            router[r*columns+c].in[4]  <--> TaskLink <--> pe[r*columns+c].out;
            router[r*columns+c].out[4] <--> TaskLink <--> pe[r*columns+c].in;
        }
}
