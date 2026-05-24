#ifndef __HNOCS_ONOC_LOGICAL_TOPOLOGY_MANAGER_H_
#define __HNOCS_ONOC_LOGICAL_TOPOLOGY_MANAGER_H_

#include <omnetpp.h>

#include <map>
#include <string>
#include <vector>

using namespace omnetpp;

#include "onoc/common/OpticalPathMetrics.h"
#include "onoc/common/OpticalDeviceModel.h"

// Maintains a runtime logical adjacency graph on top of a fixed physical Torus.
// Routing modules query this manager for next-hop decisions under current topology mode.
class LogicalTopologyManager : public cSimpleModule {
  private:
    // Physical grid dimensions.
    int rows;
    int columns;
    int numNodes;

    // Star/Tree root and star fanout controls.
    int starCenterId;
    int starLeafLimit;
    std::string starLeafOrderMode;

    // Optical planning defaults and per-pair overrides.
    int defaultOpticalWavelengths;
    int maxOpticalWavelengths;
    int numOpticalSpatialChannels;
    double opticalLaunchPower_dBm;
    double opticalReceiverSensitivity_dBm;
    double opticalSourceModulatorLoss_dB;
    double opticalHopInsertionLoss_dB;       // deprecated – retained for compatibility
    double opticalHopCrosstalkLoss_dB;       // deprecated – retained for compatibility
    double opticalReceiverDemodulatorLoss_dB;// deprecated – retained for compatibility
    bool logOpticalAllocDecisions;

    // Device-level optical parameters (new)
    std::string opticalDeviceParamsFile;
    double opticalWaveguideMaxPower_dBm;
    double opticalThermalNoiseFloor_dBm;
    int    opticalModulationBitsPerSymbol;
    bool   opticalEnableSOA;
    bool   enableBudgetBasedRerouting;
    double rerouteMarginThreshold_dB;

    // Per-device per-wavelength parameter table
    OpticalParamTable deviceParamTable;

    // Pre-built router turn metadata matrices: key is (nodeId) → matrix
    // Matrix stores formula-based through/bend counts; expanded per wavelength at runtime.
    std::map<int, RouterTurnMetadataMatrix> routerTurnMatrices;

    // Temperature-aware optical parameters
    bool   opticalEnableThermalEffects;
    double opticalTambient_K;
    double opticalThermoOpticCoeff_nm_per_K;
    double opticalTuningEfficiency_mW_per_nm;
    double opticalRingIL_TempCoeff_dB_per_K;
    double opticalSoaGain_TempCoeff_dB_per_K;
    double opticalWaveguideLoss_TempCoeff_dB_per_cm_per_K;

    // Accumulated temperature-aware stats
    mutable double totalOpticalTuningPower_mW;
    mutable int opticalBudgetComputations;

    // Waveguide distance parameters (cm)
    OpticalWaveguideDistances wgDistances;

    std::vector<std::vector<int> > pairRequiredWavelengths;

    // Edge occupancy map: key is undirected edge id, value is [spatial][wavelength] owner packet id.
    std::map<long long, std::vector<std::vector<int> > > opticalEdgeOccupancy;

    struct OpticalPacketAllocation {
      int srcId;
      int dstId;
      int pktId;
      int spatialChannel;
      std::vector<int> wavelengths; // 1-based wavelength ids
      std::vector<long long> pathEdges;
    };
    std::map<int, OpticalPacketAllocation> opticalPacketAllocations;
    mutable std::map<int, OpticalPathMetrics> cachedBudgets;  // pre-computed at reservation time
    int nextCircuitToken;

    // Runtime behavior controls.
    bool logTopologyTransitions;
    std::string ringMode;

    // Current logical topology name and adjacency matrix A(t).
    std::string currentTopology;
    std::vector<std::vector<unsigned char> > logicalAdjacency;

    // Scheduled self-messages for topology transitions.
    std::vector<cMessage *> scheduledSwitchMsgs;

  private:
    // Coordinate/id conversion helpers.
    int nodeIdByRowCol(int x, int y) const;
    void rowColByNodeId(int nodeId, int &x, int &y) const;

    // Node id validation helpers.
    int normalizeNodeId(int nodeId) const;
    bool isValidNodeId(int nodeId) const;

    // Adjacency graph primitives.
    void clearAdjacency();
    void addUndirectedEdge(int a, int b);

    // Topology construction routines.
    void addTorusEdges();
    void addMeshEdges();
    void addRingEdges();
    void buildSnakeRingOrder(std::vector<int> &order) const;
    int torusDistanceByNodeIds(int fromId, int toId) const;
    void buildStarLeafOrderByPhysicalProximity(std::vector<int> &order, int center) const;
    void addStarEdges();
    void addTreeEdges();

    // Returns physical torus neighbors of a node id.
    void getTorusNeighbors(int nodeId, std::vector<int> &neighbors) const;

    // String normalization helpers for user parameters.
    std::string trim(const std::string &text) const;
    std::string toLower(const std::string &text) const;
    void parseOpticalPairWavelengthOverrides(const std::string &spec);
    int parsePositiveInt(const std::string &token, const char *fieldName) const;

    // Physical topology type for optical path computation.
    std::string physicalTopology;

    // Optical path helpers for WDM/SDM overlap-constrained allocation.
    long long makeUndirectedEdgeKey(int a, int b) const;
    int getNextRouterOnTorusXYPath(int fromId, int dstId) const;
    void buildTorusXYPathEdges(int srcId, int dstId, std::vector<long long> &pathEdges) const;
    int getNextRouterOnMeshXYPath(int fromId, int dstId) const;
    void buildMeshXYPathEdges(int srcId, int dstId, std::vector<long long> &pathEdges) const;
    void buildXYPathEdges(int srcId, int dstId, std::vector<long long> &pathEdges) const;
    std::vector<std::vector<int> > &getOrCreateEdgeOccupancy(long long edgeKey);
    bool isWavelengthFreeOnPath(const std::vector<long long> &pathEdges, int spatialChannel, int wavelengthIndex) const;

    // Applies a topology and schedules topology-switch events.
    void applyTopology(const std::string &topologyName);
    void scheduleTopologySwitches(const std::string &switchSpec);

    // Counts undirected edges currently active in the logical graph.
    int countActiveEdges() const;

  public:
    LogicalTopologyManager();
    virtual ~LogicalTopologyManager();

    // Query API used by routing modules.
    int getLogicalNextHop(int srcId, int dstId) const;
    bool isLogicalEdgeUp(int srcId, int dstId) const;
    int getRequiredOpticalWavelengths(int srcId, int dstId) const;
    bool getOpticalPathMetrics(int pktId, OpticalPathMetrics &metrics) const;
        bool reserveOpticalPathForSetup(int srcId,
          int dstId,
          int &circuitToken,
          int &selectedSpatialChannel,
          int &selectedWavelengthMask,
          bool &insufficientResources,
          std::string &failureReason);
        bool tryAllocateOpticalPathForPacket(int srcId, int dstId, int pktId,
          int &selectedSpatialChannel,
          std::vector<int> &selectedWavelengths,
              bool &insufficientResources,
          std::string &failureReason);
        void releaseOpticalPathByToken(int circuitToken);
        void releaseOpticalPathForPacket(int pktId);
    const std::string &getCurrentTopology() const;

    // Device-level optical budget queries (new).
    bool getDeviceLevelPathMetrics(int srcId, int dstId,
            const std::vector<int> &wavelengths,
            OpticalPathMetrics &metrics) const;
    bool shouldRerouteForBudget(const OpticalPathMetrics &metrics) const;
    int  getWavelengthUtilization(long long edgeKey, int spatialChannel, int wavelengthIndex) const;
    int  getTotalWavelengthSlots(long long edgeKey) const;

  protected:
    virtual void initialize();
    virtual void handleMessage(cMessage *msg);
    virtual void finish();
};

#endif
