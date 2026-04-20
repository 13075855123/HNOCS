//
// Task communication message extending NoC flit
//
// This message type carries task dependency data between Processing Elements (PEs)
// in the task-driven simulation model. It extends NoCFlitMsg so that existing
// router modules can forward it without modification.
//

import "../NoCs";

packet TaskMsg extends NoCFlitMsg {
    int taskId;              // target task ID on the receiving PE
    int producerPE;          // sending PE number
    int consumerPE;          // receiving PE number
    int producerTaskId;      // sending task ID
    int dataSize;            // data size (bytes)
    simtime_t computeTime;   // compute time that produced this data
}
