"""Compile the LED implementation with host timer and GPIO stubs."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LEDFlashTest(unittest.TestCase):
    def test_stable_timer_and_admission(self):
        header = (ROOT / "src/led.h").read_text()
        source = (ROOT / "src/led.cpp").read_text()
        setup = (ROOT / "src/ratgdo.cpp").read_text()
        self.assertLess(setup.index("led.setupFlashTimer();"), setup.index("    setup_comms();"))
        self.assertLess(setup.index("laser.setupFlashTimer();"), setup.index("    setup_homekit();"))
        production = re.sub(r"^#include .*\n|^#pragma once\n", "", header + source, flags=re.M)
        harness = r'''
#include <atomic>
#include <cassert>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <thread>
#include <vector>
constexpr int OUTPUT=1, LED_BUILTIN=1, LED_BUILTIN_ON_STATE=1, LASER_PIN=2;
void pinMode(uint8_t,int) {}
void digitalWrite(uint8_t,uint8_t) {}
struct Timer { void(*callback)(void*);void*arg; };
using esp_timer_handle_t=Timer*;
inline constexpr int ESP_TIMER_TASK=0,ESP_OK=0;
struct esp_timer_create_args_t {void(*callback)(void*);void*arg;int dispatch_method;const char*name;};
std::atomic<unsigned> creates{0},starts{0};
bool failCreate=false,failStart=false;
Timer timers[8];
int esp_timer_create(const esp_timer_create_args_t*a,esp_timer_handle_t*t){
 unsigned index=creates++;if(failCreate)return -1;assert(index<8);
 timers[index]={a->callback,a->arg};*t=&timers[index];return ESP_OK;
}
int esp_timer_start_once(esp_timer_handle_t,uint64_t us){assert(us);++starts;return failStart?-1:ESP_OK;}
class Ticker {bool running=false;std::function<void()> callback;
 public: bool active(){return running;}
 void once_ms(uint64_t,std::function<void()> cb){running=true;callback=cb;}
};
''' + production + r'''
std::mutex gate;
std::condition_variable condition;
bool blockIdle=false,idleEntered=false,releaseIdle=false;
void notification(bool state){
 if(state)return;
 std::unique_lock<std::mutex> lock(gate);
 if(blockIdle){idleEntered=true;condition.notify_all();condition.wait(lock,[]{return releaseIdle;});}
}
int main(){
#ifdef ESP32
 // Global construction performs no timer allocation; setup owns creation.
 assert(creates==0);led.flash(10);assert(starts==0&&!led.state());
 assert(led.setupFlashTimer());assert(led.setupFlashTimer());assert(creates==1);
 Timer*timer=&timers[0];assert(timer->arg==&led);
 std::vector<std::thread> producers;
 for(int i=0;i<16;++i)producers.emplace_back([]{for(int j=0;j<100;++j)led.flash(10);});
 for(auto&t:producers)t.join();
 assert(starts==1&&led.state());
 // Expiration does not open admission until the callback has fully returned.
 led.onChange(notification);blockIdle=true;
 std::thread callback([&]{timer->callback(timer->arg);});
 {std::unique_lock<std::mutex> lock(gate);condition.wait(lock,[]{return idleEntered;});}
 led.flash(10);assert(starts==1);
 {std::lock_guard<std::mutex> lock(gate);releaseIdle=true;}condition.notify_all();callback.join();
 blockIdle=false;assert(!led.state());led.flash(10);assert(starts==2&&led.state());
 timer->callback(timer->arg);assert(!led.state()&&creates==1);
 // A failed start restores idle and permits the next request to try again.
 failStart=true;led.flash(10);assert(starts==3&&!led.state());
 failStart=false;led.flash(10);assert(starts==4&&led.state());timer->callback(timer->arg);
 unsigned previous=starts;led.flash(0);led.flash(UINT64_MAX);assert(starts==previous);
 // Failed creation is not retried by producers or repeated setup calls.
 failCreate=true;LED unavailable(3);assert(!unavailable.setupFlashTimer());
 assert(!unavailable.setupFlashTimer()&&creates==2);unavailable.flash(10);
 assert(starts==previous&&!unavailable.state());
#else
 assert(led.setupFlashTimer());led.flash(10);assert(led.state());
 assert(creates==0&&starts==0);
#endif
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "led.cpp"
            binary = Path(directory) / "led"
            cpp.write_text(harness)
            for target in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
                                "-D" + target, "-DRATGDO32_DISCO", "-fsanitize=address,undefined",
                                str(cpp), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
