#include "../src/log_snapshot.h"

#include <cassert>
#include <chrono>
#include <future>
#include <mutex>
#include <string>
#include <thread>

struct Ring
{
    unsigned wrapped;
    unsigned head;
    char buffer[16];
};

// Match the logger's aligned-ring traversal, including wrapped tail first.
static std::string contents(const Ring &ring)
{
    std::string text;
    const size_t start = ((ring.head + 4) & ~size_t(3)) % sizeof(ring.buffer);
    if (ring.wrapped)
        text.append(ring.buffer + start, sizeof(ring.buffer) - start);
    text.append(ring.buffer, std::strlen(ring.buffer));
    return text;
}

static void exercise(bool wrapped)
{
    Ring ring = {wrapped ? 1u : 0u, 3, {'n', 'e', 'w', '\0',
        'o', 'l', 'd', 'e', 's', 't', ' ', 'l', 'i', 'n', 'e', '\n'}};
    const std::string expected = wrapped ? "oldest line\nnew" : "new";
    assert(contents(ring) == expected);
    std::recursive_mutex mutex;
    std::promise<void> outputStarted;
    std::promise<void> releaseOutput;
    auto release = releaseOutput.get_future();
    std::string result;
    std::thread output([&]() {
        assert(withLogSnapshot(&ring, [&]() { mutex.lock(); }, [&]() { mutex.unlock(); },
            [&](const Ring *snapshot) {
                outputStarted.set_value();
                release.wait(); // A slow network write/flush.
                result = contents(*snapshot);
            }));
    });
    outputStarted.get_future().wait();
    auto writer = std::async(std::launch::async, [&]() {
        std::lock_guard<std::recursive_mutex> guard(mutex);
        ring.wrapped = 0;
        ring.head = 7;
        std::memcpy(ring.buffer, "changed", 8);
    });
    const bool progressed = writer.wait_for(std::chrono::seconds(2)) == std::future_status::ready;
    // Always unblock/join before asserting, so a regression fails without hanging.
    releaseOutput.set_value();
    writer.get();
    output.join();
    assert(progressed);
    assert(result == expected);
    assert(contents(ring) == "changed");
}

int main()
{
    exercise(false);
    exercise(true);
    Ring ring = {};
    bool locked = false;
    bool wrote = false;
    assert(!withLogSnapshot(&ring, [&]() { locked = true; }, []() {},
        [&](const Ring *) { wrote = true; }, [](size_t) -> void * { return nullptr; }));
    assert(!locked && !wrote);
    assert(withLogSnapshot(static_cast<const Ring *>(nullptr), [&]() { locked = true; }, []() {},
        [&](const Ring *snapshot) { assert(snapshot == nullptr); wrote = true; }));
    assert(!locked && wrote);
}
