"""Compile the production ESP32 adapter against a narrow port contract shim.

The shim checks lock boundaries and races; SDK spinlock timing is a target test.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class HomekitNotificationAdapterTest(unittest.TestCase):
    def test_esp32_branch_serializes_complete_word_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'freertos').mkdir()
            (root/'esp_idf_version.h').write_text('#define ESP_IDF_VERSION_MAJOR 5\n#define ESP_IDF_VERSION_MINOR 5\n')
            (root/'freertos/FreeRTOS.h').write_text('#pragma once\n')
            (root/'freertos/portmacro.h').write_text(r'''
#pragma once
#include <cstdint>
#include <mutex>
#include <cassert>
struct portMUX_TYPE { uint32_t owner,count; };
#define portMUX_INITIALIZER_UNLOCKED {0,0}
inline std::mutex testPortMutex;
inline thread_local unsigned criticalDepth=0;
inline void testEnter(portMUX_TYPE *) {
    assert(criticalDepth==0);
    testPortMutex.lock(); ++criticalDepth;
}
inline void testExit(portMUX_TYPE *) {
    assert(criticalDepth==1);
    --criticalDepth; testPortMutex.unlock();
}
#define portENTER_CRITICAL(p) testEnter(p)
#define portEXIT_CRITICAL(p) testExit(p)
''')
            source = root/'adapter.cpp'
            source.write_text(r'''
#include "homekit_notifications.h"
#include <atomic>
#include <thread>
#include <cassert>
int main() {
    HomekitBooleanMailbox state;
    HomekitServiceRequests requests;
    HomekitFloatMailbox reading;
    std::atomic<bool> done{false};
    std::thread writer([&] {
        for(unsigned i=0;i<100000;++i) {
            state.publish(true,true); state.publish(false,true);
            requests.publish(HomekitService::Laser,i&1);
            reading.publish(float(i));
            assert(!criticalDepth);
        }
        state.publish(true);
        requests.publish(HomekitService::Laser,true);
        reading.publish(123.5f);
        done.store(true);
    });
    while(!done.load()) {
        bool value; float sample;
        state.take(value); requests.hasPending();
        requests.take(HomekitService::Laser,value); reading.take(sample);
        assert(!criticalDepth);
    }
    writer.join();
    // Publish after the overlap so final assertions do not depend on scheduling.
    state.publish(true,true); state.publish(false,true);
    bool value;
    assert(state.take(value)&&value);
    assert(state.take(value)&&!value&&!state.take(value));
    state.publish(true,true); state.publish(false,true);
    state.beginObservation();
    assert(state.take(value)&&!value&&!state.take(value));
    requests.publish(HomekitService::Manual,true);
    assert(requests.hasPending());
    assert(requests.take(HomekitService::Manual,value)&&value);
    reading.publish(23.5f); float sample;
    assert(reading.take(sample)&&sample==23.5f&&!reading.take(sample));
    assert(!criticalDepth);
}
''')
            binary = root/'adapter'
            command = [shutil.which('c++'),'-std=c++17','-DESP32','-pthread',
                       '-fsanitize=address,undefined','-I',str(root),'-I',str(Path('src').resolve()),
                       str(source),'-o',str(binary)]
            subprocess.run(command,check=True,capture_output=True)
            subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)
            (root/'esp_idf_version.h').write_text('#define ESP_IDF_VERSION_MAJOR 5\n#define ESP_IDF_VERSION_MINOR 4\n')
            incompatible = subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(incompatible.returncode,0)
            self.assertIn('Review notification critical-section adapter',incompatible.stderr)
