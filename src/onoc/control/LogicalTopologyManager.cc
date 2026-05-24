#include "LogicalTopologyManager.h"

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <limits>
#include <queue>
#include <sstream>

#include "onoc/common/OpticalDeviceModel.h"
#include "onoc/common/OpticalParamLoader.h"
#include "thermal/ThermalTrace.h"

Define_Module(LogicalTopologyManager);

// Initialize defaults before OMNeT parameters are read in initialize().
LogicalTopologyManager::LogicalTopologyManager() {
    rows = 0;
    columns = 0;
    numNodes = 0;
    starCenterId = 0;
    starLeafLimit = -1;
    starLeafOrderMode = "physical";
    defaultOpticalWavelengths = 2;
    maxOpticalWavelengths = 16;
    numOpticalSpatialChannels = 1;
    opticalLaunchPower_dBm = 0.0;
    opticalReceiverSensitivity_dBm = -18.0;
    opticalSourceModulatorLoss_dB = 0.0;
    opticalHopInsertionLoss_dB = 0.0;
    opticalHopCrosstalkLoss_dB = 0.0;
    opticalReceiverDemodulatorLoss_dB = 0.0;
    opticalDeviceParamsFile = "";
    opticalWaveguideMaxPower_dBm = 14.0;
    opticalThermalNoiseFloor_dBm = -50.0;
    opticalModulationBitsPerSymbol = 2;
    opticalEnableSOA = true;
    enableBudgetBasedRerouting = false;
    rerouteMarginThreshold_dB = 3.0;
    wgDistances.sourceToModulator_cm = 0.01;
    wgDistances.modulatorToRouter_cm = 0.03;
    wgDistances.routerToRouter_cm = 0.15;
    wgDistances.routerToDemodulator_cm = 0.03;
    wgDistances.demodulatorToPD_cm = 0.005;
    nextCircuitToken = 1;
    logOpticalAllocDecisions = false;
    logTopologyTransitions = true;
    ringMode = "snake";
    physicalTopology = "mesh";
    totalOpticalTuningPower_mW = 0.0;
    opticalBudgetComputations = 0;
}

// Cancel and delete all scheduled topology switch messages.
LogicalTopologyManager::~LogicalTopologyManager() {
    for (size_t i = 0; i < scheduledSwitchMsgs.size(); ++i) {
        cMessage *msg = scheduledSwitchMsgs[i];
        if (!msg) {
            continue;
        }
        if (msg->isScheduled()) {
            cancelEvent(msg);
        }
        delete msg;
    }
    scheduledSwitchMsgs.clear();
    opticalPacketAllocations.clear();
    opticalEdgeOccupancy.clear();
}

// Map (x,y) to linear node id.
int LogicalTopologyManager::nodeIdByRowCol(int x, int y) const {
    return y * columns + x;
}

// Map linear node id to (x,y).
void LogicalTopologyManager::rowColByNodeId(int nodeId, int &x, int &y) const {
    y = nodeId / columns;
    x = nodeId % columns;
}

// Normalize arbitrary node id (including negative) into [0, numNodes).
int LogicalTopologyManager::normalizeNodeId(int nodeId) const {
    if (numNodes <= 0) {
        return 0;
    }
    int normalized = nodeId % numNodes;
    if (normalized < 0) {
        normalized += numNodes;
    }
    return normalized;
}

// Check whether node id is within current graph range.
bool LogicalTopologyManager::isValidNodeId(int nodeId) const {
    return nodeId >= 0 && nodeId < numNodes;
}

// Reset logical adjacency matrix to empty graph.
void LogicalTopologyManager::clearAdjacency() {
    for (int i = 0; i < numNodes; ++i) {
        for (int j = 0; j < numNodes; ++j) {
            logicalAdjacency[i][j] = 0;
        }
    }
}

// Add one undirected logical edge if both endpoints are valid and distinct.
void LogicalTopologyManager::addUndirectedEdge(int a, int b) {
    if (!isValidNodeId(a) || !isValidNodeId(b) || a == b) {
        return;
    }
    logicalAdjacency[a][b] = 1;
    logicalAdjacency[b][a] = 1;
}

void LogicalTopologyManager::addTorusEdges() {
    // Torus logical graph: each node connects to its east and south neighbors
    // with wrap-around, and addUndirectedEdge makes links bidirectional.
    // Connecting only east/south avoids duplicate edge insertion.
    for (int y = 0; y < rows; ++y) {
        for (int x = 0; x < columns; ++x) {
            int node = nodeIdByRowCol(x, y);
            if (columns > 1) {
                addUndirectedEdge(node, nodeIdByRowCol((x + 1) % columns, y));
            }
            if (rows > 1) {
                addUndirectedEdge(node, nodeIdByRowCol(x, (y + 1) % rows));
            }
        }
    }
}

void LogicalTopologyManager::addMeshEdges() {
    // Mesh logical graph: same grid indexing as Torus, but no wrap-around.
    // Boundary nodes have fewer neighbors because links stop at edges.
    for (int y = 0; y < rows; ++y) {
        for (int x = 0; x < columns; ++x) {
            int node = nodeIdByRowCol(x, y);
            if (x + 1 < columns) {
                addUndirectedEdge(node, nodeIdByRowCol(x + 1, y));
            }
            if (y + 1 < rows) {
                addUndirectedEdge(node, nodeIdByRowCol(x, y + 1));
            }
        }
    }
}

void LogicalTopologyManager::buildSnakeRingOrder(std::vector<int> &order) const {
    order.clear();
    order.reserve(numNodes);

    // If rows is even, row-wise snake closes through Torus vertical wrap.
    if ((rows % 2) == 0) {
        for (int y = 0; y < rows; ++y) {
            if ((y % 2) == 0) {
                for (int x = 0; x < columns; ++x) {
                    order.push_back(nodeIdByRowCol(x, y));
                }
            } else {
                for (int x = columns - 1; x >= 0; --x) {
                    order.push_back(nodeIdByRowCol(x, y));
                }
            }
        }
        return;
    }

    // If columns is even, column-wise snake closes through Torus horizontal wrap.
    if ((columns % 2) == 0) {
        for (int x = 0; x < columns; ++x) {
            if ((x % 2) == 0) {
                for (int y = 0; y < rows; ++y) {
                    order.push_back(nodeIdByRowCol(x, y));
                }
            } else {
                for (int y = rows - 1; y >= 0; --y) {
                    order.push_back(nodeIdByRowCol(x, y));
                }
            }
        }
        return;
    }

    // Odd x odd Torus has no simple snake cycle that stays on adjacent links.
    // Fallback to ID order to keep the simulation runnable.
    for (int i = 0; i < numNodes; ++i) {
        order.push_back(i);
    }
}

void LogicalTopologyManager::addRingEdges() {
    // Ring logical graph:
    // - ringMode=id    : ID order 0..N-1
    // - ringMode=snake : serpentine order aligned to Torus neighbors when possible
    if (numNodes <= 1) {
        return;
    }

    std::vector<int> ringOrder;
    std::string mode = toLower(trim(ringMode));
    if (mode == "snake") {
        buildSnakeRingOrder(ringOrder);
    } else if (mode == "id") {
        ringOrder.reserve(numNodes);
        for (int i = 0; i < numNodes; ++i) {
            ringOrder.push_back(i);
        }
    } else {
        throw cRuntimeError("Unknown ringMode '%s' (expected 'snake' or 'id')", mode.c_str());
    }

    for (int i = 0; i < numNodes; ++i) {
        int a = ringOrder[i];
        int b = ringOrder[(i + 1) % numNodes];
        addUndirectedEdge(a, b);
    }
}

int LogicalTopologyManager::torusDistanceByNodeIds(int fromId, int toId) const {
    // Manhattan distance on torus with wrap-around on both axes.
    int fx = 0;
    int fy = 0;
    int tx = 0;
    int ty = 0;

    rowColByNodeId(fromId, fx, fy);
    rowColByNodeId(toId, tx, ty);

    int dx = (tx > fx) ? (tx - fx) : (fx - tx);
    int dy = (ty > fy) ? (ty - fy) : (fy - ty);

    if (columns > 0) {
        int wrapDx = columns - dx;
        if (wrapDx < dx) {
            dx = wrapDx;
        }
    }

    if (rows > 0) {
        int wrapDy = rows - dy;
        if (wrapDy < dy) {
            dy = wrapDy;
        }
    }

    return dx + dy;
}

void LogicalTopologyManager::buildStarLeafOrderByPhysicalProximity(std::vector<int> &order, int center) const {
    // Sort candidate leaves by torus distance to center, then by node id.
    order.clear();
    order.reserve(numNodes > 0 ? numNodes - 1 : 0);

    for (int node = 0; node < numNodes; ++node) {
        if (node == center) {
            continue;
        }
        order.push_back(node);
    }

    std::sort(order.begin(), order.end(),
            [this, center](int a, int b) {
                int da = torusDistanceByNodeIds(center, a);
                int db = torusDistanceByNodeIds(center, b);
                if (da != db) {
                    return da < db;
                }
                return a < b;
            });
}

void LogicalTopologyManager::addStarEdges() {
    // Star logical graph: starCenterId is normalized to [0, numNodes).
    // Leaf selection policy:
    // - starLeafOrderMode=physical: nearest leaves first by Torus distance
    // - starLeafOrderMode=id      : ascending node id (legacy)
    // starLeafLimit <= 0 means connect all leaves.
    int center = normalizeNodeId(starCenterId);
    int maxLeaves = starLeafLimit;
    std::vector<int> leafOrder;

    std::string mode = toLower(trim(starLeafOrderMode));
    if (mode == "physical") {
        buildStarLeafOrderByPhysicalProximity(leafOrder, center);
    } else if (mode == "id") {
        for (int node = 0; node < numNodes; ++node) {
            if (node == center) {
                continue;
            }
            leafOrder.push_back(node);
        }
    } else {
        throw cRuntimeError("Unknown starLeafOrderMode '%s' (expected 'physical' or 'id')", mode.c_str());
    }

    int connectedLeaves = 0;
    std::vector<int> selectedLeaves;
    for (size_t i = 0; i < leafOrder.size(); ++i) {
        if (maxLeaves > 0 && connectedLeaves >= maxLeaves) {
            break;
        }

        int node = leafOrder[i];
        addUndirectedEdge(center, node);
        selectedLeaves.push_back(node);
        connectedLeaves++;
    }

    if (logTopologyTransitions) {
        std::ostringstream oss;
        for (size_t i = 0; i < selectedLeaves.size(); ++i) {
            if (i > 0) {
                oss << ',';
            }
            oss << selectedLeaves[i];
        }
        EV_INFO << "Star center=" << center
                << ", leafOrderMode=" << mode
                << ", leafLimit=" << maxLeaves
                << ", selectedLeaves=[" << oss.str() << "]" << endl;
    }
}

void LogicalTopologyManager::getTorusNeighbors(int nodeId, std::vector<int> &neighbors) const {
    // Candidate neighbors on the physical Torus grid, used by tree building.
    // Duplicates can happen on tiny dimensions (for example 2xN), so they are filtered.
    neighbors.clear();
    if (!isValidNodeId(nodeId)) {
        return;
    }

    int x = 0;
    int y = 0;
    rowColByNodeId(nodeId, x, y);

    if (columns > 1) {
        int east = nodeIdByRowCol((x + 1) % columns, y);
        int west = nodeIdByRowCol((x - 1 + columns) % columns, y);
        neighbors.push_back(east);
        if (west != east) {
            neighbors.push_back(west);
        }
    }

    if (rows > 1) {
        int south = nodeIdByRowCol(x, (y + 1) % rows);
        int north = nodeIdByRowCol(x, (y - 1 + rows) % rows);
        bool southExists = false;
        bool northExists = false;

        for (size_t i = 0; i < neighbors.size(); ++i) {
            if (neighbors[i] == south) {
                southExists = true;
            }
            if (neighbors[i] == north) {
                northExists = true;
            }
        }

        if (!southExists) {
            neighbors.push_back(south);
        }
        if (!northExists && north != south) {
            neighbors.push_back(north);
        }
    }
}

void LogicalTopologyManager::addTreeEdges() {
    // Tree logical graph: build a BFS spanning tree over Torus neighbors.
    // Root is normalizeNodeId(starCenterId). When a node is first discovered,
    // the current node becomes its parent and we add exactly one tree edge.
    if (numNodes <= 1) {
        return;
    }

    int root = normalizeNodeId(starCenterId);
    std::vector<unsigned char> visited(numNodes, 0);
    std::queue<int> pending;
    std::vector<int> neighbors;

    visited[root] = 1;
    pending.push(root);

    while (!pending.empty()) {
        int current = pending.front();
        pending.pop();

        getTorusNeighbors(current, neighbors);
        for (size_t i = 0; i < neighbors.size(); ++i) {
            int next = neighbors[i];
            if (visited[next]) {
                continue;
            }
            visited[next] = 1;
            // Parent-child relation in BFS tree: current (parent) -> next (child).
            addUndirectedEdge(current, next);
            pending.push(next);
        }
    }
}

std::string LogicalTopologyManager::trim(const std::string &text) const {
    // Trim leading and trailing ASCII whitespace.
    size_t start = 0;
    while (start < text.size() && std::isspace(static_cast<unsigned char>(text[start])) != 0) {
        ++start;
    }

    size_t end = text.size();
    while (end > start && std::isspace(static_cast<unsigned char>(text[end - 1])) != 0) {
        --end;
    }

    return text.substr(start, end - start);
}

std::string LogicalTopologyManager::toLower(const std::string &text) const {
    // Lowercase conversion for case-insensitive topology/strategy parameters.
    std::string lowered = text;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(),
            static_cast<int (*)(int)>(std::tolower));
    return lowered;
}

int LogicalTopologyManager::parsePositiveInt(const std::string &token, const char *fieldName) const {
    std::string normalized = trim(token);
    if (normalized.empty()) {
        throw cRuntimeError("%s must not be empty", fieldName);
    }

    char *endPtr = NULL;
    long value = std::strtol(normalized.c_str(), &endPtr, 10);
    if (endPtr == normalized.c_str() || *endPtr != '\0') {
        throw cRuntimeError("%s must be an integer, got '%s'", fieldName, normalized.c_str());
    }
    if (value <= 0) {
        throw cRuntimeError("%s must be > 0, got '%ld'", fieldName, value);
    }
    return static_cast<int>(value);
}

long long LogicalTopologyManager::makeUndirectedEdgeKey(int a, int b) const {
    if (a > b) {
        int tmp = a;
        a = b;
        b = tmp;
    }

    return (static_cast<long long>(a) << 32) | static_cast<unsigned int>(b);
}

int LogicalTopologyManager::getNextRouterOnTorusXYPath(int fromId, int dstId) const {
    if (fromId == dstId) {
        return dstId;
    }

    int fx = 0;
    int fy = 0;
    int tx = 0;
    int ty = 0;
    rowColByNodeId(fromId, fx, fy);
    rowColByNodeId(dstId, tx, ty);

    if ((fx != tx) && (columns > 1)) {
        int right = (tx - fx + columns) % columns;
        int left = (fx - tx + columns) % columns;
        int nx = fx;
        if (right <= left) {
            nx = (fx + 1) % columns;
        } else {
            nx = (fx - 1 + columns) % columns;
        }
        return nodeIdByRowCol(nx, fy);
    }

    if ((fy != ty) && (rows > 1)) {
        int down = (ty - fy + rows) % rows;
        int up = (fy - ty + rows) % rows;
        int ny = fy;
        if (down <= up) {
            ny = (fy + 1) % rows;
        } else {
            ny = (fy - 1 + rows) % rows;
        }
        return nodeIdByRowCol(fx, ny);
    }

    return dstId;
}

void LogicalTopologyManager::buildTorusXYPathEdges(int srcId, int dstId, std::vector<long long> &pathEdges) const {
    pathEdges.clear();
    if (!isValidNodeId(srcId) || !isValidNodeId(dstId) || srcId == dstId) {
        return;
    }

    int current = srcId;
    int guard = 0;
    const int maxHops = std::max(1, numNodes * 2);

    while (current != dstId) {
        int next = getNextRouterOnTorusXYPath(current, dstId);
        if (!isValidNodeId(next) || next == current) {
            break;
        }
        pathEdges.push_back(makeUndirectedEdgeKey(current, next));
        current = next;
        guard++;

        if (guard > maxHops) {
            throw cRuntimeError("Optical XY path loop detected while building path %d->%d", srcId, dstId);
        }
    }
}

int LogicalTopologyManager::getNextRouterOnMeshXYPath(int fromId, int dstId) const {
    if (fromId == dstId) {
        return dstId;
    }

    int fx = 0, fy = 0, tx = 0, ty = 0;
    rowColByNodeId(fromId, fx, fy);
    rowColByNodeId(dstId, tx, ty);

    // Mesh XY: first move in X (column) direction, no wrap-around
    if (fx != tx) {
        int nx = (tx > fx) ? (fx + 1) : (fx - 1);
        return nodeIdByRowCol(nx, fy);
    }

    // Move in Y (row) direction, no wrap-around
    if (fy != ty) {
        int ny = (ty > fy) ? (fy + 1) : (fy - 1);
        return nodeIdByRowCol(fx, ny);
    }

    return dstId;
}

void LogicalTopologyManager::buildMeshXYPathEdges(int srcId, int dstId,
        std::vector<long long> &pathEdges) const {
    pathEdges.clear();
    if (!isValidNodeId(srcId) || !isValidNodeId(dstId) || srcId == dstId) {
        return;
    }

    int current = srcId;
    int guard = 0;
    const int maxHops = std::max(1, numNodes * 2);

    while (current != dstId) {
        int next = getNextRouterOnMeshXYPath(current, dstId);
        if (!isValidNodeId(next) || next == current) {
            break;
        }
        pathEdges.push_back(makeUndirectedEdgeKey(current, next));
        current = next;
        guard++;

        if (guard > maxHops) {
            throw cRuntimeError("Optical Mesh XY path loop detected while building path %d->%d",
                    srcId, dstId);
        }
    }
}

void LogicalTopologyManager::buildXYPathEdges(int srcId, int dstId,
        std::vector<long long> &pathEdges) const {
    if (physicalTopology == "torus") {
        buildTorusXYPathEdges(srcId, dstId, pathEdges);
    } else {
        buildMeshXYPathEdges(srcId, dstId, pathEdges);
    }
}

std::vector<std::vector<int> > &LogicalTopologyManager::getOrCreateEdgeOccupancy(long long edgeKey) {
    std::map<long long, std::vector<std::vector<int> > >::iterator it = opticalEdgeOccupancy.find(edgeKey);
    if (it != opticalEdgeOccupancy.end()) {
        return it->second;
    }

    std::vector<std::vector<int> > occupancy;
    occupancy.resize(numOpticalSpatialChannels);
    for (int s = 0; s < numOpticalSpatialChannels; ++s) {
        occupancy[s].resize(maxOpticalWavelengths, 0);
    }

    opticalEdgeOccupancy[edgeKey] = occupancy;
    return opticalEdgeOccupancy[edgeKey];
}

bool LogicalTopologyManager::isWavelengthFreeOnPath(const std::vector<long long> &pathEdges,
        int spatialChannel,
        int wavelengthIndex) const {
    for (size_t i = 0; i < pathEdges.size(); ++i) {
        std::map<long long, std::vector<std::vector<int> > >::const_iterator it = opticalEdgeOccupancy.find(pathEdges[i]);
        if (it == opticalEdgeOccupancy.end()) {
            continue;
        }

        const std::vector<std::vector<int> > &edgeOcc = it->second;
        if (spatialChannel < 0 || spatialChannel >= static_cast<int>(edgeOcc.size())) {
            return false;
        }
        if (wavelengthIndex < 0 || wavelengthIndex >= static_cast<int>(edgeOcc[spatialChannel].size())) {
            return false;
        }
        if (edgeOcc[spatialChannel][wavelengthIndex] != 0) {
            return false;
        }
    }

    return true;
}

void LogicalTopologyManager::parseOpticalPairWavelengthOverrides(const std::string &spec) {
    std::string normalizedSpec = trim(spec);
    if (normalizedSpec.empty()) {
        return;
    }

    cStringTokenizer entryTokenizer(normalizedSpec.c_str(), ";");
    const char *entryToken = NULL;
    while ((entryToken = entryTokenizer.nextToken()) != NULL) {
        std::string entry = trim(entryToken);
        if (entry.empty()) {
            continue;
        }

        size_t colonPos = entry.find(':');
        if (colonPos == std::string::npos) {
            throw cRuntimeError("Invalid optical pair override '%s', expected 'src->dst:wl'", entry.c_str());
        }

        std::string pairToken = trim(entry.substr(0, colonPos));
        std::string wlToken = trim(entry.substr(colonPos + 1));

        size_t arrowPos = pairToken.find("->");
        if (arrowPos == std::string::npos) {
            throw cRuntimeError("Invalid optical pair '%s', expected 'src->dst'", pairToken.c_str());
        }

        std::string srcToken = trim(pairToken.substr(0, arrowPos));
        std::string dstToken = trim(pairToken.substr(arrowPos + 2));

        char *srcEndPtr = NULL;
        long srcLong = std::strtol(srcToken.c_str(), &srcEndPtr, 10);
        if (srcEndPtr == srcToken.c_str() || *srcEndPtr != '\0' || srcLong < 0) {
            throw cRuntimeError("optical override src id must be >= 0, got '%s'", srcToken.c_str());
        }

        char *dstEndPtr = NULL;
        long dstLong = std::strtol(dstToken.c_str(), &dstEndPtr, 10);
        if (dstEndPtr == dstToken.c_str() || *dstEndPtr != '\0' || dstLong < 0) {
            throw cRuntimeError("optical override dst id must be >= 0, got '%s'", dstToken.c_str());
        }

        int srcId = static_cast<int>(srcLong);
        int dstId = static_cast<int>(dstLong);
        int wlCount = parsePositiveInt(wlToken, "optical override wavelength count");

        if (srcId < 0 || srcId >= numNodes || dstId < 0 || dstId >= numNodes) {
            throw cRuntimeError("Optical override pair '%s' is out of range for %d nodes", pairToken.c_str(), numNodes);
        }

        if (wlCount > maxOpticalWavelengths) {
            throw cRuntimeError("Optical override '%s:%d' exceeds maxOpticalWavelengths=%d",
                    pairToken.c_str(), wlCount, maxOpticalWavelengths);
        }

        pairRequiredWavelengths[srcId][dstId] = wlCount;

        if (logOpticalAllocDecisions) {
            EV_INFO << "Optical override pair " << srcId << "->" << dstId
                    << " requires " << wlCount << " wavelengths" << endl;
        }
    }
}

void LogicalTopologyManager::applyTopology(const std::string &topologyName) {
    std::string normalized = toLower(trim(topologyName));
    if (normalized.empty()) {
        throw cRuntimeError("Topology name must not be empty");
    }

    clearAdjacency();

    if (normalized == "torus") {
        addTorusEdges();
    } else if (normalized == "mesh") {
        addMeshEdges();
    } else if (normalized == "ring") {
        addRingEdges();
    } else if (normalized == "star") {
        addStarEdges();
    } else if (normalized == "tree") {
        addTreeEdges();
    } else {
        throw cRuntimeError("Unknown logical topology '%s'", normalized.c_str());
    }

    currentTopology = normalized;

    if (logTopologyTransitions) {
        EV << "-I- " << getFullPath() << " switched logical topology to '"
           << currentTopology << "' (activeEdges=" << countActiveEdges() << ")" << endl;
    }
}

void LogicalTopologyManager::scheduleTopologySwitches(const std::string &switchSpec) {
    // Parse "time:topology;time:topology" and schedule self-messages.
    std::string normalizedSpec = trim(switchSpec);
    if (normalizedSpec.empty()) {
        return;
    }

    cStringTokenizer switchTokenizer(normalizedSpec.c_str(), ";");
    const char *entry = NULL;
    while ((entry = switchTokenizer.nextToken()) != NULL) {
        std::string switchEntry = trim(entry);
        if (switchEntry.empty()) {
            continue;
        }

        size_t delimPos = switchEntry.find(':');
        if (delimPos == std::string::npos) {
            throw cRuntimeError("Invalid topology switch entry '%s', expected '<time>:<topology>'",
                    switchEntry.c_str());
        }

        std::string timeToken = trim(switchEntry.substr(0, delimPos));
        std::string topologyToken = toLower(trim(switchEntry.substr(delimPos + 1)));

        if (timeToken.empty() || topologyToken.empty()) {
            throw cRuntimeError("Invalid topology switch entry '%s', expected '<time>:<topology>'",
                    switchEntry.c_str());
        }

        simtime_t switchAt = SimTime::parse(timeToken.c_str());
        std::string msgName = std::string("topology-switch:") + topologyToken;
        cMessage *switchMsg = new cMessage(msgName.c_str());
        scheduledSwitchMsgs.push_back(switchMsg);
        scheduleAt(switchAt, switchMsg);

        if (logTopologyTransitions) {
            EV << "-I- " << getFullPath() << " scheduled topology switch to '"
               << topologyToken << "' at " << switchAt << endl;
        }
    }
}

int LogicalTopologyManager::countActiveEdges() const {
    // Count undirected edges once by scanning upper triangular matrix.
    int edges = 0;
    for (int i = 0; i < numNodes; ++i) {
        for (int j = i + 1; j < numNodes; ++j) {
            if (logicalAdjacency[i][j]) {
                edges++;
            }
        }
    }
    return edges;
}

void LogicalTopologyManager::initialize() {
    // Read all topology-control parameters from NED/ini.
    rows = par("rows");
    columns = par("columns");
    ringMode = par("ringMode").stringValue();
    starCenterId = par("starCenterId");
    starLeafLimit = par("starLeafLimit");
    starLeafOrderMode = par("starLeafOrderMode").stringValue();
    defaultOpticalWavelengths = par("defaultOpticalWavelengths");
    maxOpticalWavelengths = par("maxOpticalWavelengths");
    numOpticalSpatialChannels = par("numOpticalSpatialChannels");
    opticalLaunchPower_dBm = par("opticalLaunchPower_dBm");
    opticalReceiverSensitivity_dBm = par("opticalReceiverSensitivity_dBm");
    opticalSourceModulatorLoss_dB = par("opticalSourceModulatorLoss_dB");
    opticalHopInsertionLoss_dB = par("opticalHopInsertionLoss_dB");
    opticalHopCrosstalkLoss_dB = par("opticalHopCrosstalkLoss_dB");
    opticalReceiverDemodulatorLoss_dB = par("opticalReceiverDemodulatorLoss_dB");
    opticalDeviceParamsFile = par("opticalDeviceParamsFile").stringValue();
    opticalWaveguideMaxPower_dBm = par("opticalWaveguideMaxPower_dBm");
    opticalThermalNoiseFloor_dBm = par("opticalThermalNoiseFloor_dBm");
    opticalModulationBitsPerSymbol = par("opticalModulationBitsPerSymbol");
    opticalEnableSOA = par("opticalEnableSOA");
    enableBudgetBasedRerouting = par("enableBudgetBasedRerouting");
    rerouteMarginThreshold_dB = par("rerouteMarginThreshold_dB");

    // Temperature-aware optical parameters
    opticalEnableThermalEffects = par("opticalEnableThermalEffects");
    opticalTambient_K = par("opticalTambient_K");
    opticalThermoOpticCoeff_nm_per_K = par("opticalThermoOpticCoeff_nm_per_K");
    opticalTuningEfficiency_mW_per_nm = par("opticalTuningEfficiency_mW_per_nm");
    opticalRingIL_TempCoeff_dB_per_K = par("opticalRingIL_TempCoeff_dB_per_K");
    opticalSoaGain_TempCoeff_dB_per_K = par("opticalSoaGain_TempCoeff_dB_per_K");
    opticalWaveguideLoss_TempCoeff_dB_per_cm_per_K = par("opticalWaveguideLoss_TempCoeff_dB_per_cm_per_K");
    wgDistances.modulatorToRouter_cm = par("opticalWaveguideNItoRouter_cm");
    wgDistances.routerToRouter_cm = par("opticalWaveguideRouterToRouter_cm");
    wgDistances.sourceToModulator_cm = par("opticalWaveguideSourceToMod_cm");
    wgDistances.demodulatorToPD_cm = par("opticalWaveguideDemodToPD_cm");
    wgDistances.routerToDemodulator_cm = wgDistances.modulatorToRouter_cm; // symmetric
    logOpticalAllocDecisions = par("logOpticalAllocDecisions");
    logTopologyTransitions = par("logTopologyTransitions");
    if (hasPar("physicalTopology")) {
        std::string pt = par("physicalTopology").stringValue();
        physicalTopology = strcmp(pt.c_str(), "torus") == 0 ? "torus" : "mesh";
    }

    if (rows <= 0 || columns <= 0) {
        throw cRuntimeError("rows and columns must be positive (got rows=%d, columns=%d)",
                rows, columns);
    }

    if (defaultOpticalWavelengths <= 0) {
        throw cRuntimeError("defaultOpticalWavelengths must be > 0 (got %d)", defaultOpticalWavelengths);
    }
    if (maxOpticalWavelengths <= 0) {
        throw cRuntimeError("maxOpticalWavelengths must be > 0 (got %d)", maxOpticalWavelengths);
    }
    if (numOpticalSpatialChannels <= 0) {
        throw cRuntimeError("numOpticalSpatialChannels must be > 0 (got %d)", numOpticalSpatialChannels);
    }
    if (defaultOpticalWavelengths > maxOpticalWavelengths) {
        throw cRuntimeError("defaultOpticalWavelengths (%d) must be <= maxOpticalWavelengths (%d)",
                defaultOpticalWavelengths, maxOpticalWavelengths);
    }
    if (opticalSourceModulatorLoss_dB < 0.0 || opticalHopInsertionLoss_dB < 0.0
            || opticalHopCrosstalkLoss_dB < 0.0 || opticalReceiverDemodulatorLoss_dB < 0.0) {
        throw cRuntimeError("optical loss parameters must be >= 0");
    }

    numNodes = rows * columns;
    logicalAdjacency.resize(numNodes);
    for (int i = 0; i < numNodes; ++i) {
        logicalAdjacency[i].resize(numNodes, 0);
    }

    pairRequiredWavelengths.resize(numNodes);
    for (int src = 0; src < numNodes; ++src) {
        pairRequiredWavelengths[src].resize(numNodes, defaultOpticalWavelengths);
    }

    std::string opticalOverrideSpec = par("opticalPairWavelengthOverrides").stringValue();
    parseOpticalPairWavelengthOverrides(opticalOverrideSpec);

    // Load device-level optical parameters from file (or use defaults).
    loadOpticalParamsOrDefault(
            opticalDeviceParamsFile.empty() ? NULL : opticalDeviceParamsFile.c_str(),
            deviceParamTable, maxOpticalWavelengths);

    // Pre-build wavelength-dependent router turn metadata matrices for every node.
    RouterTurnMetadataMatrix templateMatrix = buildWavelengthDependentRouterMatrix(maxOpticalWavelengths);
    for (int n = 0; n < numNodes; ++n) {
        routerTurnMatrices[n] = templateMatrix;
    }

    // Build the initial logical graph, then schedule future topology changes.
    std::string initialTopology = par("initialTopology").stringValue();
    applyTopology(initialTopology);

    std::string switchSpec = par("topologySwitches").stringValue();
    scheduleTopologySwitches(switchSpec);
}

void LogicalTopologyManager::handleMessage(cMessage *msg) {
    // Only self-messages are expected: each message encodes one topology switch.
    if (!msg->isSelfMessage()) {
        throw cRuntimeError("Only self-messages are supported by LogicalTopologyManager");
    }

    std::string msgName = msg->getName();
    size_t delimPos = msgName.find(':');
    if (delimPos == std::string::npos) {
        delete msg;
        throw cRuntimeError("Malformed topology switch message '%s'", msgName.c_str());
    }

    std::string topologyToken = toLower(trim(msgName.substr(delimPos + 1)));

    for (std::vector<cMessage *>::iterator it = scheduledSwitchMsgs.begin();
            it != scheduledSwitchMsgs.end(); ++it) {
        if (*it == msg) {
            scheduledSwitchMsgs.erase(it);
            break;
        }
    }

    applyTopology(topologyToken);
    delete msg;
}

void LogicalTopologyManager::finish() {
    // Persist final edge count for result analysis.
    recordScalar("onoc-logical-active-edges", countActiveEdges());

    // Per-edge, per-spatial-channel wavelength occupancy statistics
    int totalOccupiedSlots = 0;
    int totalSlots = 0;
    for (std::map<long long, std::vector<std::vector<int> > >::const_iterator
            it = opticalEdgeOccupancy.begin(); it != opticalEdgeOccupancy.end(); ++it) {
        for (size_t s = 0; s < it->second.size(); ++s) {
            int occupied = 0;
            for (size_t w = 0; w < it->second[s].size(); ++w) {
                if (it->second[s][w] > 0) ++occupied;
                ++totalSlots;
            }
            totalOccupiedSlots += occupied;
        }
    }
    recordScalar("onoc-optical-total-wavelength-slots", static_cast<double>(totalSlots));
    recordScalar("onoc-optical-occupied-wavelength-slots", static_cast<double>(totalOccupiedSlots));
    if (totalSlots > 0) {
        recordScalar("onoc-optical-wavelength-utilization-pct",
                static_cast<double>(totalOccupiedSlots) / totalSlots * 100.0);
    }

    // Active optical circuits snapshot
    recordScalar("onoc-optical-active-circuits",
            static_cast<double>(opticalPacketAllocations.size()));

    // Temperature-aware optical statistics
    if (opticalEnableThermalEffects) {
        recordScalar("onoc-optical-total-tuning-power-mW", totalOpticalTuningPower_mW);
        recordScalar("onoc-optical-budget-computations", static_cast<double>(opticalBudgetComputations));
        if (opticalBudgetComputations > 0) {
            recordScalar("onoc-optical-avg-tuning-power-mW",
                    totalOpticalTuningPower_mW / opticalBudgetComputations);
        }
    }
}

int LogicalTopologyManager::getLogicalNextHop(int srcId, int dstId) const {
    // BFS shortest-path next-hop on the current logical adjacency graph.
    if (!isValidNodeId(srcId) || !isValidNodeId(dstId)) {
        return -1;
    }
    if (srcId == dstId) {
        return dstId;
    }

    std::vector<int> parent(numNodes, -1);
    std::vector<unsigned char> visited(numNodes, 0);
    std::queue<int> pending;

    visited[srcId] = 1;
    parent[srcId] = srcId;
    pending.push(srcId);

    while (!pending.empty()) {
        int current = pending.front();
        pending.pop();

        if (current == dstId) {
            break;
        }

        for (int next = 0; next < numNodes; ++next) {
            if (!logicalAdjacency[current][next] || visited[next]) {
                continue;
            }

            visited[next] = 1;
            parent[next] = current;
            pending.push(next);
        }
    }

    if (!visited[dstId]) {
        return -1;
    }

    int hop = dstId;
    while (parent[hop] != srcId) {
        hop = parent[hop];
        if (hop < 0) {
            return -1;
        }
    }

    return hop;
}

bool LogicalTopologyManager::isLogicalEdgeUp(int srcId, int dstId) const {
    // Convenience query: check if direct logical edge exists.
    if (!isValidNodeId(srcId) || !isValidNodeId(dstId)) {
        return false;
    }
    return logicalAdjacency[srcId][dstId] != 0;
}

int LogicalTopologyManager::getRequiredOpticalWavelengths(int srcId, int dstId) const {
    if (!isValidNodeId(srcId) || !isValidNodeId(dstId)) {
        return defaultOpticalWavelengths;
    }
    return pairRequiredWavelengths[srcId][dstId];
}

bool LogicalTopologyManager::getOpticalPathMetrics(int pktId, OpticalPathMetrics &metrics) const {
    // Return cached budget if pre-computed at reservation time
    std::map<int, OpticalPathMetrics>::const_iterator cacheIt = cachedBudgets.find(pktId);
    if (cacheIt != cachedBudgets.end()) {
        metrics = cacheIt->second;
        return true;
    }

    std::map<int, OpticalPacketAllocation>::const_iterator it = opticalPacketAllocations.find(pktId);
    if (it == opticalPacketAllocations.end()) {
        return false;
    }

    const OpticalPacketAllocation &alloc = it->second;

    // Use device-level computation when available
    if (!deviceParamTable.empty()) {
        bool ok = getDeviceLevelPathMetrics(alloc.srcId, alloc.dstId,
                alloc.wavelengths, metrics);
        if (ok) cachedBudgets[pktId] = metrics;
        return ok;
    }

    // Fallback to hop-level (legacy)
    metrics = OpticalPathMetrics();
    metrics.opticalPath = true;
    metrics.srcId = alloc.srcId;
    metrics.dstId = alloc.dstId;
    metrics.pktId = alloc.pktId;
    metrics.spatialChannel = alloc.spatialChannel;
    metrics.wavelengths = alloc.wavelengths;
    metrics.hopCount = static_cast<int>(alloc.pathEdges.size());
    metrics.wavelengthCount = static_cast<int>(alloc.wavelengths.size());
    metrics.launchPower_dBm = opticalLaunchPower_dBm;
    metrics.receiverSensitivity_dBm = opticalReceiverSensitivity_dBm;
    metrics.sourceModulatorLoss_dB = opticalSourceModulatorLoss_dB;
    metrics.hopInsertionLoss_dB = opticalHopInsertionLoss_dB * metrics.hopCount;
    metrics.hopCrosstalkLoss_dB = opticalHopCrosstalkLoss_dB * metrics.hopCount;
    metrics.receiverDemodulatorLoss_dB = opticalReceiverDemodulatorLoss_dB;
    metrics.totalLoss_dB = metrics.sourceModulatorLoss_dB
            + metrics.hopInsertionLoss_dB
            + metrics.hopCrosstalkLoss_dB
            + metrics.receiverDemodulatorLoss_dB;
    metrics.receivedPower_dBm = metrics.launchPower_dBm - metrics.totalLoss_dB;
    metrics.signalMargin_dB = metrics.receivedPower_dBm - metrics.receiverSensitivity_dBm;
    metrics.meetsSensitivity = metrics.receivedPower_dBm >= metrics.receiverSensitivity_dBm;
    return true;
}

// ────────────────────────────────────────────────────────────
//  Device-level path metrics: builds a device chain from source
//  NI through torus routers to destination NI, walks every
//  optical segment, accumulates per-device losses, SOA gain +
//  ASE noise, computes SNR and PAM4 BER.
// ────────────────────────────────────────────────────────────
bool LogicalTopologyManager::getDeviceLevelPathMetrics(int srcId, int dstId,
        const std::vector<int> &wavelengths,
        OpticalPathMetrics &metrics) const {
    metrics = OpticalPathMetrics();
    metrics.opticalPath = true;
    metrics.srcId = srcId;
    metrics.dstId = dstId;
    metrics.pktId = 0; // filled by caller
    metrics.wavelengths = wavelengths;
    metrics.hopCount = 0;
    metrics.wavelengthCount = static_cast<int>(wavelengths.size());

    // Assign wavelength names
    for (size_t i = 0; i < wavelengths.size(); ++i) {
        char nameBuf[32];
        snprintf(nameBuf, sizeof(nameBuf), "lambda_%d", wavelengths[i]);
        metrics.wavelengthNames.push_back(nameBuf);
    }

    // ── Build the device path ──
    OpticalDevicePath devPath;
    const int totalWL = maxOpticalWavelengths;

    // ---- Source NI: Laser → waveguide → modulator chain per λ ----
    for (size_t wi = 0; wi < wavelengths.size(); ++wi) {
        int wl = wavelengths[wi];
        // Waveguide: source to modulator
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_WAVEGUIDE;
            seg.deviceIndex = srcId;
            seg.waveguideLength_cm = wgDistances.sourceToModulator_cm;
            seg.wavelengthIndex = wl;
            devPath.segments.push_back(seg);
        }
        // Modulator microring chain: (wl-1) through + 1 drop
        buildModulatorSegments(srcId, wl, totalWL, devPath.segments);
        // Waveguide: modulator to router core port
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_WAVEGUIDE;
            seg.deviceIndex = srcId * 10;
            seg.waveguideLength_cm = wgDistances.modulatorToRouter_cm;
            seg.wavelengthIndex = wl;
            devPath.segments.push_back(seg);
        }
    }

    // ---- Source router: Core→[direction] injection ----
    // Router injection: expand from Core(0) to the first output port
    // (handled in the loop below when prevNode=srcId)

    // ---- Router hops (use Mesh/Torus XY path according to physicalTopology) ----
    std::vector<long long> pathEdges;
    buildXYPathEdges(srcId, dstId, pathEdges);

    int prevNode = srcId;
    int prevOutPort = -1;
    for (size_t e = 0; e < pathEdges.size(); ++e) {
        long long edgeKey = pathEdges[e];
        int a = static_cast<int>(edgeKey >> 32);
        int b = static_cast<int>(edgeKey & 0xFFFFFFFFLL);
        int nextNode = (a == prevNode) ? b : a;

        // Determine incoming/outgoing port directions
        int inPort  = -1;
        int outPort = -1;
        {
            int px, py, nx, ny;
            rowColByNodeId(prevNode, px, py);
            rowColByNodeId(nextNode, nx, ny);
            int dx = nx - px;
            int dy = ny - py;
            if (dx > 1) dx -= columns; if (dx < -1) dx += columns;
            if (dy > 1) dy -= rows;    if (dy < -1) dy += rows;
            // Map delta to port: 0=Local,1=West,2=North,3=East,4=South
            if (dx == 0 && dy == -1)      { inPort = 2; outPort = 0; } // N→S
            else if (dx == 0 && dy == 1)  { inPort = 0; outPort = 2; } // S→N
            else if (dx == -1 && dy == 0) { inPort = 3; outPort = 1; } // W→E
            else if (dx == 1 && dy == 0)  { inPort = 1; outPort = 3; } // E→W
            if (inPort < 0) {
                if (dy < 0)      { inPort = 0; outPort = 2; }
                else if (dy > 0) { inPort = 2; outPort = 0; }
                else if (dx < 0) { inPort = 1; outPort = 3; }
                else             { inPort = 3; outPort = 1; }
            }
        }

        // If first hop: source router injection (Local=0 → outPort)
        if (e == 0) {
            inPort = 0; // Local/Core injection
        }

        // Router traversal using wavelength-dependent metadata
        // For each active wavelength, evaluate through count and expand
        std::map<int, RouterTurnMetadataMatrix>::const_iterator rtmIt =
            routerTurnMatrices.find(prevNode);
        if (rtmIt != routerTurnMatrices.end() && inPort >= 0 && outPort >= 0
                && inPort < 5 && outPort < 5 && inPort != outPort) {
            const RouterTurnMetadata &meta = rtmIt->second[inPort][outPort];
            // Emit through passes (count depends on wavelength)
            // Use a representative wavelength for shared-path through counts
            int repWl = wavelengths.empty() ? 1 : wavelengths[0];
            int formulaType = meta.throughCount; // stored as formula type index
            int actualThrough = 0;
            switch (formulaType) {
                case 0: actualThrough = repWl - 1; break;
                case 1: actualThrough = 2*totalWL + repWl - 1; break;
                case 2: actualThrough = 3*totalWL + repWl - 1; break;
                case 3: actualThrough = 4*totalWL; break;
                case 4: actualThrough = 4*totalWL + repWl - 1; break;
                case 5: actualThrough = 6*totalWL + repWl - 1; break;
                default: actualThrough = 0; break;
            }
            for (int t = 0; t < actualThrough; ++t) {
                OpticalDeviceSegment seg;
                seg.deviceType = DEV_RING_THROUGH;
                seg.deviceIndex = prevNode * 1000 + inPort * 100 + outPort * 10 + t;
                seg.wavelengthIndex = repWl;
                devPath.segments.push_back(seg);
            }
            // Drop (always 1)
            {
                OpticalDeviceSegment seg;
                seg.deviceType = DEV_RING_DROP;
                seg.deviceIndex = prevNode * 100 + inPort * 10 + outPort;
                seg.wavelengthIndex = repWl;
                devPath.segments.push_back(seg);
            }
            // Bends
            for (int b = 0; b < meta.bendCount; ++b) {
                OpticalDeviceSegment seg;
                seg.deviceType = DEV_WAVEGUIDE_BEND;
                seg.deviceIndex = prevNode * 1000 + inPort * 100 + outPort * 10 + b;
                seg.wavelengthIndex = repWl;
                devPath.segments.push_back(seg);
            }
        }

        // Waveguide segment between routers
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_WAVEGUIDE;
            seg.deviceIndex = static_cast<int>(e);
            seg.waveguideLength_cm = wgDistances.routerToRouter_cm;
            seg.wavelengthIndex = 1;
            devPath.segments.push_back(seg);
        }

        // SOA after router output
        if (opticalEnableSOA) {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_SOA;
            seg.deviceIndex = nextNode;
            seg.wavelengthIndex = 1;
            devPath.segments.push_back(seg);
        }

        prevNode = nextNode;
        prevOutPort = outPort;
    }

    // ---- Destination NI: Router→demodulator chain per λ → PD ----
    for (size_t wi = 0; wi < wavelengths.size(); ++wi) {
        int wl = wavelengths[wi];
        // Waveguide: router core port to demodulator
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_WAVEGUIDE;
            seg.deviceIndex = dstId * 10 + wi;
            seg.waveguideLength_cm = wgDistances.routerToDemodulator_cm;
            seg.wavelengthIndex = wl;
            devPath.segments.push_back(seg);
        }
        // Demodulator microring chain: (wl-1) through + 1 drop
        buildDemodulatorSegments(dstId, wl, totalWL, devPath.segments);
        // Waveguide: demodulator ring chain to PD
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_WAVEGUIDE;
            seg.deviceIndex = dstId * 100 + wi;
            seg.waveguideLength_cm = wgDistances.demodulatorToPD_cm;
            seg.wavelengthIndex = wl;
            devPath.segments.push_back(seg);
        }
        // Photodetector
        {
            OpticalDeviceSegment seg;
            seg.deviceType = DEV_PHOTODETECTOR;
            seg.deviceIndex = dstId * 100 + static_cast<int>(wi);
            seg.wavelengthIndex = wl;
            devPath.segments.push_back(seg);
        }
    }

    metrics.hopCount = static_cast<int>(pathEdges.size());

    // ── Compute budget ──
    OpticalBudgetConstraints constraints;
    constraints.launchPower_dBm = opticalLaunchPower_dBm;
    constraints.waveguideMaxPower_dBm = opticalWaveguideMaxPower_dBm;
    constraints.receiverSensitivity_dBm = opticalReceiverSensitivity_dBm;
    constraints.thermalNoiseFloor_dBm = opticalThermalNoiseFloor_dBm;
    constraints.modulationBitsPerSymbol = opticalModulationBitsPerSymbol;
    constraints.enableSOA = opticalEnableSOA;
    constraints.totalWavelengths = totalWL;
    constraints.wgDistances = wgDistances;
    constraints.enableDemodCrosstalk = par("opticalEnableDemodCrosstalk");
    constraints.singleDestinationPerWavelength = false; // dual-λ used

    // Temperature-aware effects
    constraints.enableThermalEffects = opticalEnableThermalEffects;
    constraints.Tambient_K = opticalTambient_K;
    constraints.thermoOpticCoeff_nm_per_K = opticalThermoOpticCoeff_nm_per_K;
    constraints.tuningEfficiency_mW_per_nm = opticalTuningEfficiency_mW_per_nm;
    constraints.ringIL_TempCoeff_dB_per_K = opticalRingIL_TempCoeff_dB_per_K;
    constraints.soaGain_TempCoeff_dB_per_K = opticalSoaGain_TempCoeff_dB_per_K;
    constraints.waveguideLoss_TempCoeff_dB_per_cm_per_K = opticalWaveguideLoss_TempCoeff_dB_per_cm_per_K;
    if (opticalEnableThermalEffects) {
        constraints.getNodeTemperature = [](int nodeId) -> double {
            ThermalModel *tm = getThermalModel();
            if (!tm) return 318.15;
            // Use PE temperature as proxy for all nodes (PE≈Router from Rpe2router coupling)
            return tm->getPEPerature(nodeId);
        };
    }

    OpticalDevicePath result;
    // Pass the router matrix for the first node (representative)
    std::map<int, RouterTurnMetadataMatrix>::const_iterator repMatrix =
        routerTurnMatrices.begin();
    const RouterTurnMetadataMatrix &refMatrix =
        (repMatrix != routerTurnMatrices.end()) ? repMatrix->second
        : buildWavelengthDependentRouterMatrix(totalWL);
    computeDeviceLevelBudget(devPath, deviceParamTable, constraints, refMatrix, result);

    // ── Populate metrics from result ──
    metrics.launchPower_dBm = constraints.launchPower_dBm;
    metrics.receiverSensitivity_dBm = constraints.receiverSensitivity_dBm;

    // Accumulate per-device-type totals
    metrics.modulatorLoss_dB = 0.0;
    metrics.muxDemuxLoss_dB = 0.0;
    metrics.waveguidePropagationLoss_dB = 0.0;
    metrics.waveguideBendingLoss_dB = 0.0;
    metrics.ringThroughLoss_dB = 0.0;
    metrics.ringDropLoss_dB = 0.0;
    metrics.soaGainTotal_dB = 0.0;
    metrics.detectorLoss_dB = 0.0;

    for (size_t si = 0; si < devPath.segments.size(); ++si) {
        const OpticalDeviceSegment &seg = devPath.segments[si];
        const DevicePerWavelengthParams &params =
            getDeviceParams(deviceParamTable, seg.deviceType, seg.wavelengthIndex);
        switch (seg.deviceType) {
            case DEV_MODULATOR:       metrics.modulatorLoss_dB       += params.insertionLoss_dB; break;
            case DEV_MUX:
            case DEV_DEMUX:           metrics.muxDemuxLoss_dB        += params.insertionLoss_dB; break;
            case DEV_WAVEGUIDE:       metrics.waveguidePropagationLoss_dB += params.insertionLoss_dB * seg.waveguideLength_cm; break;
            case DEV_WAVEGUIDE_BEND:  metrics.waveguideBendingLoss_dB    += params.insertionLoss_dB; break;
            case DEV_RING_THROUGH:    metrics.ringThroughLoss_dB     += params.insertionLoss_dB; break;
            case DEV_RING_DROP:       metrics.ringDropLoss_dB        += params.insertionLoss_dB; break;
            case DEV_SOA:             metrics.soaGainTotal_dB        += params.soaGain_dB; break;
            case DEV_PHOTODETECTOR:   metrics.detectorLoss_dB        += params.insertionLoss_dB; break;
            default: break;
        }
    }

    metrics.totalLoss_dB = result.totalLoss_dB;
    metrics.totalCrosstalk_dB = result.totalCrosstalk_dB;
    metrics.receivedPower_dBm = result.worstReceivedPower_dBm;
    metrics.estimatedSNR_dB = result.worstSNR_dB;
    metrics.estimatedBER = result.worstBER;
    metrics.signalMargin_dB = result.signalMargin_dB;
    metrics.meetsSensitivity = (result.worstReceivedPower_dBm >= constraints.receiverSensitivity_dBm);
    metrics.budgetRerouteTriggered = shouldRerouteForBudget(metrics);

    // Temperature-aware metrics
    metrics.totalTuningPower_mW = result.totalTuningPower_mW;
    metrics.maxRingDetuning_nm = result.maxRingDetuning_nm;
    metrics.tempAdjustedLoss_dB = result.tempAdjustedLoss_dB;
    if (opticalEnableThermalEffects) {
        totalOpticalTuningPower_mW += result.totalTuningPower_mW;
        opticalBudgetComputations++;
    }

    // Per-wavelength detail
    metrics.perWavelengthTotalLoss_dB = result.perWavelengthTotalLoss_dB;
    metrics.perWavelengthCrosstalk_dB = result.perWavelengthCrosstalk_dB;
    metrics.perWavelengthReceivedPower_dBm = result.perWavelengthReceivedPower_dBm;
    metrics.perWavelengthSNR_dB = result.perWavelengthSNR_dB;
    metrics.perWavelengthBER = result.perWavelengthBER;

    // Legacy hop-level fields (backward compat)
    metrics.sourceModulatorLoss_dB = opticalSourceModulatorLoss_dB;
    metrics.hopInsertionLoss_dB = opticalHopInsertionLoss_dB * metrics.hopCount;
    metrics.hopCrosstalkLoss_dB = opticalHopCrosstalkLoss_dB * metrics.hopCount;
    metrics.receiverDemodulatorLoss_dB = opticalReceiverDemodulatorLoss_dB;

    return true;
}

// ────────────────────────────────────────────────────────────
//  Check if budget warrants a reroute attempt
// ────────────────────────────────────────────────────────────
bool LogicalTopologyManager::shouldRerouteForBudget(const OpticalPathMetrics &metrics) const {
    if (!enableBudgetBasedRerouting) return false;
    if (metrics.signalMargin_dB < rerouteMarginThreshold_dB) return true;
    if (metrics.estimatedBER > 1e-12) return true;
    return false;
}

// ────────────────────────────────────────────────────────────
//  Per-wavelength occupancy query
// ────────────────────────────────────────────────────────────
int LogicalTopologyManager::getWavelengthUtilization(long long edgeKey,
        int spatialChannel, int wavelengthIndex) const {
    std::map<long long, std::vector<std::vector<int> > >::const_iterator it =
        opticalEdgeOccupancy.find(edgeKey);
    if (it == opticalEdgeOccupancy.end()) return 0;
    if (spatialChannel < 0 || spatialChannel >= static_cast<int>(it->second.size())) return 0;
    if (wavelengthIndex < 0 || wavelengthIndex >= static_cast<int>(it->second[spatialChannel].size()))
        return 0;
    return it->second[spatialChannel][wavelengthIndex];
}

int LogicalTopologyManager::getTotalWavelengthSlots(long long edgeKey) const {
    std::map<long long, std::vector<std::vector<int> > >::const_iterator it =
        opticalEdgeOccupancy.find(edgeKey);
    if (it == opticalEdgeOccupancy.end()) return 0;
    int total = 0;
    for (size_t s = 0; s < it->second.size(); ++s) {
        total += static_cast<int>(it->second[s].size());
    }
    return total;
}

bool LogicalTopologyManager::reserveOpticalPathForSetup(int srcId,
        int dstId,
        int &circuitToken,
        int &selectedSpatialChannel,
        int &selectedWavelengthMask,
        bool &insufficientResources,
        std::string &failureReason) {
    circuitToken = 0;
    selectedSpatialChannel = -1;
    selectedWavelengthMask = 0;
    insufficientResources = false;
    failureReason.clear();

    std::vector<int> selectedWavelengths;

    const int maxAttempts = 1024;
    for (int attempt = 0; attempt < maxAttempts; ++attempt) {
        int candidate = nextCircuitToken;
        nextCircuitToken++;
        if (nextCircuitToken <= 0) {
            nextCircuitToken = 1;
        }
        if (candidate <= 0) {
            continue;
        }
        if (opticalPacketAllocations.find(candidate) != opticalPacketAllocations.end()) {
            continue;
        }

        bool ok = tryAllocateOpticalPathForPacket(srcId,
                dstId,
                candidate,
                selectedSpatialChannel,
                selectedWavelengths,
                insufficientResources,
                failureReason);
        if (!ok) {
            return false;
        }

        int mask = 0;
        for (size_t i = 0; i < selectedWavelengths.size(); ++i) {
            int wl = selectedWavelengths[i];
            if (wl <= 0 || wl > 31) {
                continue;
            }
            mask |= (1 << (wl - 1));
        }

        circuitToken = candidate;
        selectedWavelengthMask = mask;
        return true;
    }

    failureReason = "failed to find free circuit token";
    return false;
}

bool LogicalTopologyManager::tryAllocateOpticalPathForPacket(int srcId,
        int dstId,
        int pktId,
        int &selectedSpatialChannel,
        std::vector<int> &selectedWavelengths,
        bool &insufficientResources,
        std::string &failureReason) {
    selectedSpatialChannel = -1;
    selectedWavelengths.clear();
    insufficientResources = false;
    failureReason.clear();

    if (!isValidNodeId(srcId) || !isValidNodeId(dstId)) {
        failureReason = "invalid src/dst id";
        return false;
    }
    if (pktId <= 0) {
        failureReason = "invalid pkt id";
        return false;
    }

    std::map<int, OpticalPacketAllocation>::const_iterator existing = opticalPacketAllocations.find(pktId);
    if (existing != opticalPacketAllocations.end()) {
        selectedSpatialChannel = existing->second.spatialChannel;
        selectedWavelengths = existing->second.wavelengths;
        return true;
    }

    std::vector<long long> pathEdges;
    buildXYPathEdges(srcId, dstId, pathEdges);

    int required = getRequiredOpticalWavelengths(srcId, dstId);
    if (required <= 0) {
        required = defaultOpticalWavelengths;
    }
    if (required > maxOpticalWavelengths) {
        required = maxOpticalWavelengths;
    }

    // Choose best-fit wavelengths: prefer lowest-indexed (fewest through-rings → least loss,
    // plus thermal tuning penalty per ring increases with wavelength index)
    for (int spatial = 0; spatial < numOpticalSpatialChannels; ++spatial) {
        // Collect ALL free wavelengths, then pick the lowest-indexed `required` ones
        std::vector<int> candidateWls;
        for (int wlIdx = 0; wlIdx < maxOpticalWavelengths; ++wlIdx) {
            if (isWavelengthFreeOnPath(pathEdges, spatial, wlIdx)) {
                candidateWls.push_back(wlIdx + 1);
                if (static_cast<int>(candidateWls.size()) == required * 4) break; // check up to 4× needed
            }
        }

        if (static_cast<int>(candidateWls.size()) < required) {
            continue;
        }
        // Trim to `required` lowest-indexed wavelengths (best-fit)
        candidateWls.resize(required);

        for (size_t e = 0; e < pathEdges.size(); ++e) {
            std::vector<std::vector<int> > &edgeOcc = getOrCreateEdgeOccupancy(pathEdges[e]);
            for (size_t w = 0; w < candidateWls.size(); ++w) {
                int wlIdx = candidateWls[w] - 1;
                edgeOcc[spatial][wlIdx] = pktId;
            }
        }

        OpticalPacketAllocation alloc;
        alloc.srcId = srcId;
        alloc.dstId = dstId;
        alloc.pktId = pktId;
        alloc.spatialChannel = spatial;
        alloc.wavelengths = candidateWls;
        alloc.pathEdges = pathEdges;
        opticalPacketAllocations[pktId] = alloc;

        selectedSpatialChannel = spatial;
        selectedWavelengths = candidateWls;

        if (logOpticalAllocDecisions) {
            EV_INFO << "Allocated optical path for pkt=" << pktId
                    << " pair " << srcId << "->" << dstId
                    << " spatial=" << spatial
                    << " wavelengths=" << candidateWls.size()
                    << " (required=" << required << ")" << endl;
        }

        // Pre-compute budget at reservation time (temperature ≈ same as send time)
        OpticalPathMetrics budgetMetrics;
        getDeviceLevelPathMetrics(srcId, dstId, candidateWls, budgetMetrics);
        cachedBudgets[pktId] = budgetMetrics;
        return true;
    }

    std::ostringstream oss;
    oss << "no feasible allocation on XY path for pair " << srcId << "->" << dstId
        << " (requiredWavelengths=" << required
        << ", maxWavelengths=" << maxOpticalWavelengths
        << ", spatialChannels=" << numOpticalSpatialChannels << ")";
    insufficientResources = true;
    failureReason = oss.str();
    return false;
}

void LogicalTopologyManager::releaseOpticalPathByToken(int circuitToken) {
    releaseOpticalPathForPacket(circuitToken);
}

void LogicalTopologyManager::releaseOpticalPathForPacket(int pktId) {
    std::map<int, OpticalPacketAllocation>::iterator it = opticalPacketAllocations.find(pktId);
    if (it == opticalPacketAllocations.end()) {
        return;
    }

    const OpticalPacketAllocation &alloc = it->second;
    for (size_t e = 0; e < alloc.pathEdges.size(); ++e) {
        std::map<long long, std::vector<std::vector<int> > >::iterator occIt = opticalEdgeOccupancy.find(alloc.pathEdges[e]);
        if (occIt == opticalEdgeOccupancy.end()) {
            continue;
        }

        std::vector<std::vector<int> > &edgeOcc = occIt->second;
        if (alloc.spatialChannel < 0 || alloc.spatialChannel >= static_cast<int>(edgeOcc.size())) {
            continue;
        }

        for (size_t w = 0; w < alloc.wavelengths.size(); ++w) {
            int wlIdx = alloc.wavelengths[w] - 1;
            if (wlIdx < 0 || wlIdx >= static_cast<int>(edgeOcc[alloc.spatialChannel].size())) {
                continue;
            }
            if (edgeOcc[alloc.spatialChannel][wlIdx] == pktId) {
                edgeOcc[alloc.spatialChannel][wlIdx] = 0;
            }
        }
    }

    if (logOpticalAllocDecisions) {
        EV_INFO << "Released optical path for pkt=" << pktId
                << " pair " << alloc.srcId << "->" << alloc.dstId
                << " spatial=" << alloc.spatialChannel << endl;
    }

    opticalPacketAllocations.erase(it);
}

const std::string &LogicalTopologyManager::getCurrentTopology() const {
    // Exposed to routing modules for diagnostics and error messages.
    return currentTopology;
}
