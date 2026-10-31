#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>

static_assert(std::atomic<uint32_t>::is_always_lock_free, "HomeKit publication requires lock-free words");

// Lifetime-stable state publication. Optional services never own producer handles.
// Pulse channels retain a detected state until one consumer observes it, then
// deliver the latest clear state. Repeated pulses may merge while polling stalls.
class HomekitBooleanMailbox {
    std::atomic<uint32_t> pending{0};
public:
    void publish(bool value, bool preservePulse = false) {
        if (!preservePulse) {
            pending.store(value ? 3 : 1, std::memory_order_release);
        } else if (value) {
            pending.fetch_or(7, std::memory_order_release);
        } else {
            // Preserve a pending detection while recording the latest clear.
            // A consumer between these operations may see a duplicate clear.
            pending.fetch_and(~uint32_t(2), std::memory_order_acq_rel);
            pending.fetch_or(1, std::memory_order_release);
        }
    }
    // A new/recreated service starts from current state, rather than replaying
    // detections accumulated before it existed. New publications after this
    // boundary keep their normal pulse behavior.
    void beginObservation() {
        pending.fetch_and(~uint32_t(4), std::memory_order_acq_rel);
        pending.fetch_or(1, std::memory_order_release);
    }
    bool take(bool &value) {
        uint32_t old = pending.load(std::memory_order_acquire);
        while (old & 1) {
            value = old & (4 | 2);
            const uint32_t next = (old & 2) | ((old & 4) && !(old & 2) ? 1 : 0);
            if (pending.compare_exchange_weak(old, next, std::memory_order_acq_rel,
                                            std::memory_order_acquire)) return true;
        }
        return false;
    }
};

// DHT readings are independent HomeKit characteristics. NaN denotes no pending
// sample; callers already reject NaN sensor readings before publishing.
class HomekitFloatMailbox {
    static constexpr uint32_t Empty = 0x7fc00000;
    std::atomic<uint32_t> pending{Empty};
public:
    void publish(float value) {
        uint32_t bits;
        static_assert(sizeof(bits) == sizeof(value), "32-bit float required");
        std::memcpy(&bits, &value, sizeof(bits));
        pending.store(bits, std::memory_order_release);
    }
    bool take(float &value) {
        uint32_t bits = pending.exchange(Empty, std::memory_order_acq_rel);
        if (bits == Empty) return false;
        std::memcpy(&value, &bits, sizeof(bits));
        return true;
    }
};

enum class HomekitSignal : uint8_t {
    Light, Laser, Motion, Arriving, Departing, Vehicle, Room, Stop, Manual, Count
};
enum class HomekitService : uint8_t {
    Light, Laser, Motion, Vehicle, Room, Stop, Manual, Count
};

class HomekitServiceRequests {
    std::atomic<uint32_t> pending[static_cast<unsigned>(HomekitService::Count)]{};
public:
    bool hasPending() const {
        for (const auto &request : pending)
            if (request.load(std::memory_order_acquire)) return true;
        return false;
    }
    void publish(HomekitService service, bool enable) {
        pending[static_cast<unsigned>(service)].store(enable ? 2 : 1, std::memory_order_release);
    }
    bool take(HomekitService service, bool &enable) {
        const auto value = pending[static_cast<unsigned>(service)].exchange(0, std::memory_order_acq_rel);
        enable = value == 2;
        return value != 0;
    }
};
