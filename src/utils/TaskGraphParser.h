//
// Copyright (C) 2024 HNOCS Project
//
// TaskGraphParser — shared CSV task graph loader for GlobalBuffer and TaskPE
//

#ifndef __HNOCS_TASK_GRAPH_PARSER_H_
#define __HNOCS_TASK_GRAPH_PARSER_H_

#include <omnetpp.h>
#include <vector>
#include <string>
#include "cores/task/TaskDescriptor.h"

class TaskGraphParser {
public:
    // Parse a CSV file, return all TaskDescriptors.
    // Caller owns the returned pointers (must delete each element).
    // Throws cRuntimeError on file open error or format error.
    static std::vector<TaskDescriptor*> parse(const char* filename);

private:
    static std::vector<std::string> split(const std::string& s, char delim);
    static void computePredecessors(std::vector<TaskDescriptor*>& tasks);
};

#endif
