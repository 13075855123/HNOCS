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

#ifndef __HNOCS_TASK_DESCRIPTOR_H_
#define __HNOCS_TASK_DESCRIPTOR_H_

#include <omnetpp.h>
#include <vector>
#include <map>

using namespace omnetpp;

// Task execution states
enum TaskState {
    TASK_WAITING,      // waiting for dependencies
    TASK_READY,        // ready to be scheduled
    TASK_COMPUTING,    // currently computing
    TASK_COMPLETED     // finished
};

// Describes a single task in the task graph
class TaskDescriptor {
public:
    int taskId;                              // globally unique task ID
    int assignedPE;                          // PE this task is assigned to
    simtime_t computeTime;                   // compute duration (seconds)
    int outputDataSize;                      // output data size (bytes)

    std::vector<int> predecessors;           // predecessor task IDs
    std::vector<int> successors;             // successor task IDs
    std::map<int, int> successorPE;          // {successorTaskId -> peId}

    TaskState state;                         // current state
    int pendingDependencies;                 // unsatisfied dependency count
    simtime_t startTime;                     // execution start time
    simtime_t finishTime;                    // execution finish time

    TaskDescriptor(int id, int pe, simtime_t compTime, int dataSize)
        : taskId(id), assignedPE(pe), computeTime(compTime),
          outputDataSize(dataSize), state(TASK_WAITING),
          pendingDependencies(0), startTime(0), finishTime(0) {}
};

#endif // __HNOCS_TASK_DESCRIPTOR_H_
