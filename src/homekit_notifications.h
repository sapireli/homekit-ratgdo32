#pragma once
#include <cstdint>
#include <cstring>

// All producers run in task context (Arduino, HomeSpan, network event or
// ESP timer task). Keep one explicit lock instead of implementation-hidden
// libatomic locks. No caller may perform I/O, allocation, callbacks or nested
// mailbox work inside this guard. The longest body reads seven request words.
#ifdef ESP32
#include <esp_idf_version.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#if ESP_IDF_VERSION_MAJOR != 5 || ESP_IDF_VERSION_MINOR != 5
#error "Review notification critical-section adapter for this ESP-IDF version"
#endif
static_assert(sizeof(portMUX_TYPE) == 8, "Review notification spinlock resource budget");
inline portMUX_TYPE homekitNotificationMux = portMUX_INITIALIZER_UNLOCKED;
class HomekitNotificationGuard {
public:
    HomekitNotificationGuard() { portENTER_CRITICAL(&homekitNotificationMux); }
    ~HomekitNotificationGuard() { portEXIT_CRITICAL(&homekitNotificationMux); }
    HomekitNotificationGuard(const HomekitNotificationGuard &) = delete;
    HomekitNotificationGuard &operator=(const HomekitNotificationGuard &) = delete;
};
#else
#include <mutex>
inline std::mutex homekitNotificationMux;
class HomekitNotificationGuard {
    std::lock_guard<std::mutex> guard{homekitNotificationMux};
};
#endif

// Lifetime-stable state publication. Optional services never own producer handles.
// Pulse channels retain a detected state until one consumer observes it, then
// deliver the latest clear state. Repeated pulses may merge while polling stalls.
class HomekitBooleanMailbox {
    uint32_t pending = 0;
public:
    void publish(bool value, bool preservePulse = false) {
        HomekitNotificationGuard guard;
        pending = 1 | (value ? 2 : 0) |
                  (preservePulse ? ((pending & 4) | (value ? 4 : 0)) : 0);
    }
    // Recreated services start from current state, rather than replaying
    // detections accumulated before this observation boundary.
    void beginObservation() {
        HomekitNotificationGuard guard;
        pending = (pending & ~uint32_t(4)) | 1;
    }
    bool take(bool &value) {
        HomekitNotificationGuard guard;
        const uint32_t old = pending;
        if (!(old & 1)) return false;
        value = old & (4 | 2);
        pending = (old & 2) | ((old & 4) && !(old & 2) ? 1 : 0);
        return true;
    }
};

// DHT readings are independent HomeKit characteristics. NaN denotes no pending
// sample; callers already reject NaN sensor readings before publishing.
class HomekitFloatMailbox {
    static constexpr uint32_t Empty = 0x7fc00000;
    uint32_t pending = Empty;
public:
    void publish(float value) {
        uint32_t bits;
        static_assert(sizeof(bits) == sizeof(value), "32-bit float required");
        std::memcpy(&bits, &value, sizeof(bits));
        HomekitNotificationGuard guard;
        pending = bits;
    }
    bool take(float &value) {
        uint32_t bits;
        {
            HomekitNotificationGuard guard;
            bits = pending;
            pending = Empty;
        }
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
    uint32_t pending[static_cast<unsigned>(HomekitService::Count)]{};
public:
    bool hasPending() const {
        HomekitNotificationGuard guard;
        for (const auto &request : pending)
            if (request) return true;
        return false;
    }
    void publish(HomekitService service, bool enable) {
        HomekitNotificationGuard guard;
        pending[static_cast<unsigned>(service)] = enable ? 2 : 1;
    }
    bool take(HomekitService service, bool &enable) {
        HomekitNotificationGuard guard;
        auto &request = pending[static_cast<unsigned>(service)];
        const auto value = request;
        request = 0;
        enable = value == 2;
        return value != 0;
    }
};
