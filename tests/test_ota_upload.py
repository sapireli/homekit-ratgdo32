#!/usr/bin/env python3
"""Compile the real upload callback with fake HTTP/flash I/O and a polling mutex."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for i in range(opening, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError("Unclosed callback")


class OtaUpload(unittest.TestCase):
    def test_actual_callback_pause_cleanup_and_md5_ownership(self):
        source = (ROOT / "src/web.cpp").read_text()
        callback = function(source, "void handle_firmware_upload()\n{")
        harness = r'''
#include <cassert>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <future>
#include <map>
#include <mutex>
#include <shared_mutex>
#include <string>
#define ESP32 1
#define PSTR(x) x
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define TAKE_MUTEX() ((void)0)
#define GIVE_MUTEX() ((void)0)
#define JSON_START(...) ((void)0)
#define JSON_ADD_INT(...) ((void)0)
#define JSON_END() ((void)0)
#define JSON_REMOVE_NL(...) ((void)0)
#define snprintf_P snprintf
using String=std::string;
constexpr int U_FLASH=0;
enum UploadStatus { UPLOAD_FILE_START, UPLOAD_FILE_WRITE, UPLOAD_FILE_END, UPLOAD_FILE_ABORTED };
struct HTTPUpload {
    UploadStatus status=UPLOAD_FILE_START;
    String filename="firmware.bin";
    size_t currentSize=64, totalSize=128;
    uint8_t buf[64]{};
};
struct HttpServer {
    HTTPUpload data;
    std::map<String,String> arguments{{"action","update"},{"size","128"},
                                    {"md5","0123456789abcdef0123456789abcdef"}};
    HTTPUpload &upload() { return data; }
    String arg(const char *key) { return arguments[key]; }
} server;
struct HomeSpan {
    std::shared_mutex mutex;
    std::shared_mutex &getMutex() { return mutex; }
} homeSpan;
bool pollCanRun() {
    return std::async(std::launch::async, [] {
        if (!homeSpan.mutex.try_lock()) return false;
        homeSpan.mutex.unlock(); return true;
    }).get();
}
struct Config { bool password=true; bool getPasswordRequired() { return password; } } config, *userConfig=&config;
bool authenticated=true, _authenticatedUpdate=false;
bool requestAuthenticated() { return authenticated; }
String _updaterError;
size_t firmwareSize=0;
char firmwareMD5[33]{};
bool suspend_service_loop=false;
unsigned shutdowns=0;
void shutdown_comms() { ++shutdowns; assert(!pollCanRun()); }
size_t strlcpy(char *to,const char *from,size_t size) {
    size_t n=strlen(from); if (size) { size_t copy=n<size-1?n:size-1; memcpy(to,from,copy);to[copy]=0; }return n;
}
struct Esp {
    uint32_t getFreeSketchSpace() { return 0x200000; }
    uint32_t getFlashChipSpeed() { return 40000000; }
} ESP;
struct SerialPort { template<class T> void print(T) {} } Serial;
struct Client { bool connected() { return false; } };
struct SSESubscription { Client client; bool active=false; };
std::atomic<SSESubscription *> firmwareUpdateSub{nullptr};
struct SSELock { explicit operator bool() const { return true; } };
char statusStorage[256]{}, *status_json=statusStorage, writeBuffer[512]{};
void clientWrite(Client,const char *) {}
void sendSSEEvent(Client,const char *,const char *) {}
struct FlashUpdate {
    bool beginOk=true, writeOk=true, endOk=true, active=false;
    unsigned begins=0, writes=0, ends=0;
    String checksum;
    bool begin(size_t,int) { ++begins; assert(!pollCanRun()); active=beginOk; return beginOk; }
    size_t write(uint8_t *,size_t size) { ++writes; assert(!pollCanRun()); return writeOk?size:0; }
    bool end(bool=false) { ++ends; if (active) assert(!pollCanRun()); active=false; return endOk; }
    void setMD5(const char *value) { checksum=value; }
} Update;
void _setUpdaterError() { _updaterError="mock flash error"; }
''' + callback + r'''
void event(UploadStatus status) { server.data.status=status; handle_firmware_upload(); }
void start(bool verify=false) {
    server.arguments["action"]=verify?"verify":"update";
    event(UPLOAD_FILE_START);
}
int main() {
    // A pause survives returns from the real callback between upload chunks.
    assert(pollCanRun()); start(); assert(!pollCanRun());
    assert(Update.checksum=="0123456789abcdef0123456789abcdef");
    event(UPLOAD_FILE_WRITE); assert(!pollCanRun());
    event(UPLOAD_FILE_END); assert(pollCanRun());
    event(UPLOAD_FILE_END); assert(pollCanRun());

    // Re-entering START is idempotent; aborted and repeated uploads can recover.
    start(); start(); assert(!pollCanRun());
    event(UPLOAD_FILE_ABORTED); assert(pollCanRun());
    event(UPLOAD_FILE_ABORTED); assert(pollCanRun());
    start(); event(UPLOAD_FILE_WRITE); event(UPLOAD_FILE_END); assert(pollCanRun());

    // Failed flash setup/write/finalization still releases the pause at END.
    Update.beginOk=false; start(); assert(!pollCanRun());
    event(UPLOAD_FILE_END); assert(pollCanRun()); Update.beginOk=true;
    Update.writeOk=false; start(); event(UPLOAD_FILE_WRITE);
    event(UPLOAD_FILE_END); assert(pollCanRun()); Update.writeOk=true;
    Update.endOk=false; start(); event(UPLOAD_FILE_END);
    assert(pollCanRun()); Update.endOk=true;

    // Verify and rejected authentication do not stop HomeSpan or GDO services.
    const unsigned before=shutdowns;
    start(true); assert(pollCanRun());
    event(UPLOAD_FILE_WRITE); event(UPLOAD_FILE_END); assert(pollCanRun());
    authenticated=false; start(); assert(pollCanRun());
    event(UPLOAD_FILE_WRITE); event(UPLOAD_FILE_END); assert(pollCanRun());
    assert(shutdowns==before);
    authenticated=true; start(); event(UPLOAD_FILE_ABORTED); assert(pollCanRun());
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            cpp = Path(temporary) / "ota-upload.cpp"
            binary = Path(temporary) / "ota-upload"
            cpp.write_text(harness)
            subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra",
                            "-Werror", "-Wno-unused-variable", "-pthread",
                            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                            str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
