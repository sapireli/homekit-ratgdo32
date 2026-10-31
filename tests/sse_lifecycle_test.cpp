// SOURCE_LIFECYCLE_HELPERS

#include <cassert>
#include <functional>
#include <string>
#include <thread>
#include <vector>

int main()
{
    // Only a bound active subscription emits a heartbeat. No timer work can
    // leak into a reused slot; rebinding sets a fresh deadline.
    uint32_t last = 100;
    assert(!takeSSEHeartbeat(false, true, 1, last, 1100));
    assert(!takeSSEHeartbeat(true, false, 1, last, 1100));
    assert(!takeSSEHeartbeat(true, true, 0, last, 1100));
    assert(!takeSSEHeartbeat(true, true, 61, last, 100000));
    assert(last == 100);
    assert(!takeSSEHeartbeat(true, true, 1, last, 1099));
    assert(takeSSEHeartbeat(true, true, 1, last, 1100));
    assert(!takeSSEHeartbeat(true, true, 1, last, 1100));
    last = 5000; // Slot admission/rebinding resets the deadline.
    assert(!takeSSEHeartbeat(true, true, 60, last, 64999));
    assert(takeSSEHeartbeat(true, true, 60, last, 65000));
    last = UINT32_MAX - 500;
    assert(!takeSSEHeartbeat(true, true, 1, last, 498));
    assert(takeSSEHeartbeat(true, true, 1, last, 499));
    assert(last == 499);

    // A stale EventSource request must not replace a reused slot's client.
    std::string uuid = "new-uuid", current = "live-client";
    assert(!bindSSEClient(true, uuid, std::string("old-uuid"), current, std::string("stale-client")));
    assert(current == "live-client");
    assert(!bindSSEClient(false, uuid, uuid, current, std::string("inactive-client")));
    assert(current == "live-client");
    assert(bindSSEClient(true, uuid, uuid, current, std::string("replacement-client")));
    assert(current == "replacement-client");

    // A heartbeat disconnect logs; the logger broadcasts synchronously and
    // discovers the same disconnected slot. Another client must remain counted.
    std::atomic<bool> disconnected(true), survivor(true);
    std::atomic<uint32_t> count(2);
    unsigned cleaned = 0, notified = 0;
    bool connected = true;
    std::function<void()> remove;
    remove = [&] {
        retireSSESubscription(disconnected, count,
            [&] {
                connected = false;
                ++cleaned;
                remove(); // Even cleanup can trigger a logging callback.
            },
            [&](uint32_t remaining) {
                assert(!connected);
                assert(remaining == 1);
                ++notified;
                remove(); // Diagnostic -> logToBuffer -> SSEBroadcastState.
            });
    };
    remove();
    remove(); // Outer heartbeat resumes after nested broadcast removal.
    assert(count == 1 && survivor && cleaned == 1 && notified == 1);

    // Simultaneous removals must also have one winner.
    disconnected = true;
    count = 2;
    std::atomic<unsigned> concurrentCleanup(0), concurrentNotify(0);
    std::vector<std::thread> removers;
    for (unsigned i = 0; i < 8; ++i)
        removers.emplace_back([&] {
            retireSSESubscription(disconnected, count,
                [&] { ++concurrentCleanup; },
                [&](uint32_t remaining) { assert(remaining == 1); ++concurrentNotify; });
        });
    for (auto &thread : removers)
        thread.join();
    assert(count == 1 && survivor && concurrentCleanup == 1 && concurrentNotify == 1);
}
