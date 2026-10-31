#!/usr/bin/env python3
"""Compile the production logger function against bounded host concurrency tests."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
using std::min;
static std::recursive_mutex storage;
static std::recursive_mutex *logMutex = &storage;
constexpr int pdTRUE=1, portMAX_DELAY=-1, LWIP_CORE_LOCK_QUERY_HOLDER=0;
static thread_local bool coreHeld=false;
static bool sys_thread_tcpip(int) { return coreHeld; }
static int xSemaphoreTakeRecursive(std::recursive_mutex *m,int wait) {
    if (!wait) return m->try_lock() ? pdTRUE : 0;
    m->lock(); return pdTRUE;
}
static void xSemaphoreGiveRecursive(std::recursive_mutex *m) { m->unlock(); }
#define TAKE_MUTEX() xSemaphoreTakeRecursive(logMutex,portMAX_DELAY)
#define GIVE_MUTEX() xSemaphoreGiveRecursive(logMutex)
static unsigned serialWrites, sseWrites, syslogWrites;
#define SERIAL_PRINT(x) (++serialWrites)
constexpr size_t LINE_BUFFER_SIZE=256;
static char lineBuffer[LINE_BUFFER_SIZE];
struct Ring { size_t head=0; bool wrapped=false; char buffer[4096]={}; };
static Ring ring;
static Ring *msgBuffer=&ring;
static uint64_t logAppendBytes=0;
static const char *toHHMMSSmmm(uint32_t) { return "00:00:00.001"; }
constexpr int LOG_MESSAGE=1;
static std::mutex coreMutex;
static bool recurse=false;
struct LOG { void logToBuffer(const char *,va_list); };
static LOG logger;
static void emit(const char *fmt,...) {
    va_list args; va_start(args,fmt); logger.logToBuffer(fmt,args); va_end(args);
}
static void SSEBroadcastState(const char *,int) {
    ++sseWrites;
    std::lock_guard<std::mutex> core(coreMutex);
    if (recurse) { recurse=false; emit("prefix () nested\n"); }
}
static void logToSyslog(char *) { ++syslogWrites; }
"""
CASES = r"""
int main() {
    emit("prefix () ordinary\n");
    assert(sseWrites==1 && syslogWrites==1 && serialWrites==1 && ring.head>0);
#ifndef ESP8266
    const unsigned oldSSE=sseWrites, oldSyslog=syslogWrites, oldSerial=serialWrites;
    const size_t oldHead=ring.head;
    {
        std::lock_guard<std::mutex> core(coreMutex);
        coreHeld=true;
        emit("prefix () core-held\n");
        coreHeld=false;
    }
    assert(sseWrites==oldSSE && syslogWrites==oldSyslog);
    assert(serialWrites==oldSerial+1 && ring.head>oldHead);
    // A logger already owns the logger lock and waits for core. The task
    // holding core must drop the contended message instead of waiting back.
    std::atomic<bool> acquired{false};
    std::thread worker;
    const unsigned serialBeforeContention=serialWrites;
    const size_t headBeforeContention=ring.head;
    {
        std::lock_guard<std::mutex> core(coreMutex);
        worker=std::thread([&] {
            storage.lock(); acquired=true;
            std::lock_guard<std::mutex> blocked(coreMutex);
            storage.unlock();
        });
        while (!acquired.load()) std::this_thread::yield();
        coreHeld=true;
        emit("prefix () contended\n");
        coreHeld=false;
    }
    worker.join();
    assert(serialWrites==serialBeforeContention && ring.head==headBeforeContention);
    assert(sseWrites==oldSSE && syslogWrites==oldSyslog);
#endif
    const unsigned beforeSSE=sseWrites, beforeSyslog=syslogWrites;
    recurse=true; emit("prefix () recurse\n");
    assert(sseWrites==beforeSSE+1 && syslogWrites==beforeSyslog+1);
}
"""


class LoggerCoreReentryTest(unittest.TestCase):
    def test_actual_logger_function(self):
        compiler = shutil.which(os.environ.get("CXX", "c++"))
        if not compiler:
            self.skipTest("C++ compiler unavailable")
        source = (ROOT / "src/log.cpp").read_text()
        start = source.index("void LOG::logToBuffer(")
        body = source[start:source.index("\nvoid LOG::clearCrashLog()", start)]
        with tempfile.TemporaryDirectory(prefix="ratgdo-logger-test-") as directory:
            cpp = Path(directory) / "logger.cpp"
            cpp.write_text(HARNESS + body + CASES)
            for target in ("ESP32", "ESP8266"):
                with self.subTest(target=target):
                    binary = Path(directory) / target
                    subprocess.run([compiler, "-std=c++17", "-pthread", "-g",
                                    "-fsanitize=address,undefined", "-D" + target,
                                    str(cpp), "-o", str(binary)], check=True, timeout=30)
                    subprocess.run([str(binary)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
