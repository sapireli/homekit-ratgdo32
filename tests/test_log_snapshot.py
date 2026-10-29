#!/usr/bin/env python3
"""Exercise the source logger snapshot helper under ASan and UBSan."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("LOG_SNAPSHOT_TEST_SOURCE", ROOT / "src/log.cpp"))


class LogSnapshotTest(unittest.TestCase):
    def test_slow_output_preserves_concurrent_logging_and_snapshot(self):
        source = SOURCE.read_text()
        helper_start = source.index("// Keep allocation and output outside the logger lock.")
        helper_end = source.index("// Logger tag", helper_start)
        helper = source[helper_start:helper_end]
        harness = "#include <cstdlib>\n#include <cstring>\n#include <memory>\n" + helper + r'''


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
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp = Path(tmp) / "log-snapshot.cpp"
            executable = Path(tmp) / "log-snapshot"
            cpp.write_text(harness)
            subprocess.run([os.environ.get("CXX", "c++"), "-std=c++11", "-pthread",
                            "-Wall", "-Wextra", "-Werror", "-g", "-O1",
                            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            str(cpp), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
