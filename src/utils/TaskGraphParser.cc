//
// Copyright (C) 2024 HNOCS Project
//
// TaskGraphParser implementation — two-pass CSV reader
//

#include "TaskGraphParser.h"
#include <fstream>
#include <sstream>
#include <map>
#include <cstdlib>
#include <cerrno>
#include <cctype>
#include <cmath>
#include <limits>

namespace {

int parseIntField(const std::string& value, const char* filename, int lineNum,
                  const char* fieldName) {
    const char* begin = value.c_str();
    char* end = nullptr;
    errno = 0;
    long parsed = std::strtol(begin, &end, 10);
    while (end && *end != '\0' && std::isspace(static_cast<unsigned char>(*end))) {
        end++;
    }
    if (begin == end || errno == ERANGE || (end && *end != '\0') ||
            parsed < std::numeric_limits<int>::min() ||
            parsed > std::numeric_limits<int>::max()) {
        throw cRuntimeError("TaskGraphParser: %s:%d — invalid integer for %s: '%s'",
                filename, lineNum, fieldName, value.c_str());
    }
    return static_cast<int>(parsed);
}

double parseDoubleField(const std::string& value, const char* filename, int lineNum,
                        const char* fieldName) {
    const char* begin = value.c_str();
    char* end = nullptr;
    errno = 0;
    double parsed = std::strtod(begin, &end);
    while (end && *end != '\0' && std::isspace(static_cast<unsigned char>(*end))) {
        end++;
    }
    if (begin == end || errno == ERANGE || (end && *end != '\0') ||
            !std::isfinite(parsed)) {
        throw cRuntimeError("TaskGraphParser: %s:%d — invalid number for %s: '%s'",
                filename, lineNum, fieldName, value.c_str());
    }
    return parsed;
}

}

std::vector<std::string> TaskGraphParser::split(const std::string& s, char delim) {
    std::vector<std::string> tokens;
    std::stringstream ss(s);
    std::string token;
    while (std::getline(ss, token, delim)) {
        // trim leading/trailing whitespace
        size_t start = token.find_first_not_of(" \t\r");
        size_t end   = token.find_last_not_of(" \t\r");
        if (start == std::string::npos) {
            tokens.push_back("");
        } else {
            tokens.push_back(token.substr(start, end - start + 1));
        }
    }
    return tokens;
}

void TaskGraphParser::computePredecessors(std::vector<TaskDescriptor*>& tasks) {
    // Build index for O(1) lookup
    std::map<int, TaskDescriptor*> index;
    for (TaskDescriptor* t : tasks) {
        index[t->taskId] = t;
    }

    // For each task T, for each successor S, add T as predecessor of S
    for (TaskDescriptor* t : tasks) {
        for (int succId : t->successors) {
            auto it = index.find(succId);
            if (it != index.end()) {
                it->second->predecessors.push_back(t->taskId);
            } else {
                // Successor not in this task set — fine for per-PE partial loads
                EV << "-I- TaskGraphParser: successor task " << succId
                   << " of task " << t->taskId << " not found in loaded task set" << endl;
            }
        }
    }

    // Set pendingDependencies and initial state
    for (TaskDescriptor* t : tasks) {
        t->pendingDependencies = (int)t->predecessors.size();
        t->state = t->predecessors.empty() ? TASK_READY : TASK_WAITING;
    }
}

std::vector<TaskDescriptor*> TaskGraphParser::parse(const char* filename) {
    std::vector<TaskDescriptor*> tasks;
    std::map<int, TaskDescriptor*> idIndex;

    std::ifstream file(filename);
    if (!file.is_open()) {
        throw cRuntimeError("TaskGraphParser: cannot open file '%s'", filename);
    }

    int lineNum = 0;
    std::string line;
    while (std::getline(file, line)) {
        lineNum++;

        // Trim whitespace
        size_t start = line.find_first_not_of(" \t\r");
        if (start == std::string::npos) continue;  // empty line
        line = line.substr(start);

        // Skip comments
        if (line[0] == '#') continue;

        // Split by comma
        std::vector<std::string> tokens = split(line, ',');
        if (tokens.size() < 4) {
            throw cRuntimeError(
                "TaskGraphParser: %s:%d — need at least 4 columns (taskId,peId,compTime_ns,outSize_B), got %d",
                filename, lineNum, (int)tokens.size());
        }

        // Parse fixed columns
        int taskId       = parseIntField(tokens[0], filename, lineNum, "taskId");
        int peId         = parseIntField(tokens[1], filename, lineNum, "peId");
        double compNs    = parseDoubleField(tokens[2], filename, lineNum, "compTime_ns");
        int outSizeB     = parseIntField(tokens[3], filename, lineNum, "outSize_B");
        if (taskId < 0) {
            throw cRuntimeError("TaskGraphParser: %s:%d — taskId must be non-negative, got %d",
                    filename, lineNum, taskId);
        }
        if (peId < -2) {
            throw cRuntimeError("TaskGraphParser: %s:%d — peId must be -2, -1, or >=0, got %d",
                    filename, lineNum, peId);
        }
        if (compNs < 0.0) {
            throw cRuntimeError("TaskGraphParser: %s:%d — compTime_ns must be non-negative, got %g",
                    filename, lineNum, compNs);
        }
        if (outSizeB < 0) {
            throw cRuntimeError("TaskGraphParser: %s:%d — outSize_B must be non-negative, got %d",
                    filename, lineNum, outSizeB);
        }
        simtime_t compTime = compNs * 1e-9;  // ns → seconds

        // Check for duplicate taskId
        if (idIndex.find(taskId) != idIndex.end()) {
            throw cRuntimeError(
                "TaskGraphParser: %s:%d — duplicate taskId %d",
                filename, lineNum, taskId);
        }

        TaskDescriptor* task = new TaskDescriptor(taskId, peId, compTime, outSizeB);

        // Parse successor pairs: succTaskId:succPE
        for (size_t i = 4; i < tokens.size(); i++) {
            if (tokens[i].empty()) continue;
            size_t colon = tokens[i].find(':');
            if (colon == std::string::npos) {
                throw cRuntimeError(
                    "TaskGraphParser: %s:%d — bad successor format '%s' (need taskId:peId)",
                    filename, lineNum, tokens[i].c_str());
            }
            std::string succIdText = tokens[i].substr(0, colon);
            std::string succPEText = tokens[i].substr(colon + 1);
            int succId = parseIntField(succIdText, filename, lineNum, "successor taskId");
            int succPE = parseIntField(succPEText, filename, lineNum, "successor peId");
            if (succId < -1) {
                throw cRuntimeError("TaskGraphParser: %s:%d — successor taskId must be -1 or >=0, got %d",
                        filename, lineNum, succId);
            }
            if (succPE < -2) {
                throw cRuntimeError("TaskGraphParser: %s:%d — successor peId must be -2, -1, or >=0, got %d",
                        filename, lineNum, succPE);
            }
            task->successors.push_back(succId);
            task->successorPE[succId] = succPE;
        }

        tasks.push_back(task);
        idIndex[taskId] = task;
    }

    file.close();

    // Pass 2: compute predecessors from successors
    computePredecessors(tasks);

    EV << "-I- TaskGraphParser: loaded " << tasks.size()
       << " tasks from " << filename << endl;

    return tasks;
}
