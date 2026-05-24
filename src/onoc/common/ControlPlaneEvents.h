#ifndef __HNOCS_ONOC_CONTROL_PLANE_EVENTS_H_
#define __HNOCS_ONOC_CONTROL_PLANE_EVENTS_H_

#include <omnetpp.h>

// Packet SL tag format (32-bit):
// [ class:8 | spatial:8 | wavelengthMask:16 ]
// wavelengthMask bit i means wavelength (i+1) is selected.
inline int onocEncodePacketTag(int packetClass, int spatialChannel, int wavelengthMask) {
    int tag = 0;
    tag |= (packetClass & 0xff) << 24;
    tag |= (spatialChannel & 0xff) << 16;
    tag |= (wavelengthMask & 0xffff);
    return tag;
}

inline void onocDecodePacketTag(int tag, int &packetClass, int &spatialChannel, int &wavelengthMask) {
    packetClass = (tag >> 24) & 0xff;
    spatialChannel = (tag >> 16) & 0xff;
    wavelengthMask = tag & 0xffff;
}

inline int onocGetPacketClass(int tag) {
    return (tag >> 24) & 0xff;
}

// Reuse FLIT SL field as packet class tag.
enum OnocPacketClass {
    ONOC_PKT_DATA = 0,
    ONOC_PKT_SETUP_REQ = 1,
    ONOC_PKT_SETUP_ACK = 2
};

// Event type emitted by sink modules to coordinate setup/ack handling.
enum OnocControlEventType {
    ONOC_EVT_SETUP_REQ = 1,
    ONOC_EVT_SETUP_ACK = 2,
    ONOC_EVT_DATA_EOP_RELEASE = 3
};

// Event payload format (64-bit):
// [ eventType:8 | requesterId:8 | targetId:8 | token:16 | spatial:8 | wavelengthMask:16 ]
inline omnetpp::intval_t onocEncodeControlEvent(
        int eventType,
        int requesterId,
        int targetId,
        int token,
        int spatialChannel,
        int wavelengthMask) {
    omnetpp::intval_t value = 0;
    value |= (static_cast<omnetpp::intval_t>(eventType) & 0xff) << 56;
    value |= (static_cast<omnetpp::intval_t>(requesterId) & 0xff) << 48;
    value |= (static_cast<omnetpp::intval_t>(targetId) & 0xff) << 40;
    value |= (static_cast<omnetpp::intval_t>(token) & 0xffff) << 24;
    value |= (static_cast<omnetpp::intval_t>(spatialChannel) & 0xff) << 16;
    value |= (static_cast<omnetpp::intval_t>(wavelengthMask) & 0xffff);
    return value;
}

inline void onocDecodeControlEvent(
        omnetpp::intval_t value,
        int &eventType,
        int &requesterId,
        int &targetId,
        int &token,
        int &spatialChannel,
        int &wavelengthMask) {
    eventType = static_cast<int>((value >> 56) & 0xff);
    requesterId = static_cast<int>((value >> 48) & 0xff);
    targetId = static_cast<int>((value >> 40) & 0xff);
    token = static_cast<int>((value >> 24) & 0xffff);
    spatialChannel = static_cast<int>((value >> 16) & 0xff);
    wavelengthMask = static_cast<int>(value & 0xffff);
}

#endif