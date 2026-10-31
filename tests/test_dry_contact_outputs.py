#!/usr/bin/env python3
"""Run the actual output setup and dry-contact command blocks with fake GPIO."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for i in range(opening, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if not depth:
            return source[start:i + 1]
    raise AssertionError("unclosed block")


class DryContactOutputs(unittest.TestCase):
    def test_stable_release_and_wiring(self):
        helpers = ""
        source = (ROOT / "src/comms.cpp").read_text()
        start = source.index("        // Preserve legacy toggle-only wiring", source.index("bool door_command(DoorAction action, DoorCommandLifecycle::Intent intent)\n{"))
        end = source.index("\n    }\n    return true;", start)
        command = source[start:end]
        pulse = source[source.index("class DryContactPulse"):source.index("// times in miliseconds")]
        pulse = "#ifdef ESP32\n" + pulse[:pulse.rfind("#endif")] + "#endif\n"
        setup = block(source, "void setup_comms()")
        self.assertEqual(setup.count("setupDryContactTimers();"), 1)
        shutdown = block(source, "void shutdown_comms()")
        self.assertLess(shutdown.index("FunctionDelayLock lock;"), shutdown.index("cancelDryContactTimers();"))
        harness = r'''
#include <cassert>
#include <cstdint>
#include <vector>
#include <utility>
#include <atomic>
using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
int criticalDepth=0;
void portENTER_CRITICAL(portMUX_TYPE*){assert(criticalDepth++==0);}
void portEXIT_CRITICAL(portMUX_TYPE*){assert(--criticalDepth==0);}
#define OUTPUT 1
#define LOW 0
#define HIGH 1
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
std::vector<std::pair<int,int>> writes;
struct Timer {void(*callback)(void*);void*arg;bool active=false;};
using esp_timer_handle_t=Timer*;
struct esp_timer_create_args_t {void(*callback)(void*);void*arg;int dispatch_method;const char*name;};
inline constexpr int ESP_OK=0,ESP_TIMER_TASK=0;
Timer storage[3];unsigned creates=0;
std::vector<Timer*> timers;
bool failCreate=false,failStart=false,failToggleStart=false,expireDuringStart=false;
int esp_timer_create(const esp_timer_create_args_t*a,esp_timer_handle_t*t){
 assert(!criticalDepth);if(failCreate)return -1;assert(creates<3);auto*p=&storage[creates++];*p={a->callback,a->arg,false};*t=p;return ESP_OK;}
int esp_timer_start_once(esp_timer_handle_t t,uint64_t us){assert(!criticalDepth&&us==500000);
 if(failStart||(failToggleStart&&t==&storage[0]))return -1;assert(!t->active);t->active=true;timers.push_back(t);if(expireDuringStart){t->active=false;t->callback(t->arg);}return ESP_OK;}
int esp_timer_stop(esp_timer_handle_t t){assert(!criticalDepth);if(!t->active)return -1;t->active=false;return ESP_OK;}
void digitalWrite(int pin,int value) { assert(pin>=0); writes.emplace_back(pin,value); }
#ifndef ESP32
struct Ticker {void once_ms(unsigned ms,void(*cb)()){assert(ms==500);cb();}};
void delay(unsigned ms){assert(ms==500);}
#endif
enum class DoorAction { Open, Close, Toggle, Stop };
enum GarageDoorCurrentState { CURR_OPEN, CURR_CLOSED, CURR_STOPPED };
int DISCRETE_OPEN_PIN=-1, DISCRETE_CLOSE_PIN=-1;
constexpr int UART_TX_PIN=22;
''' + helpers + pulse + r'''
bool command(DoorAction action) {
    (void)action;
''' + command + r'''
    return true;
}
void clear() { writes.clear(); timers.clear(); }
void complete() { auto pending=timers; timers.clear(); for(auto*t:pending)if(t->active){t->active=false;t->callback(t->arg);} }
int main() {
#ifdef ESP32
    assert(creates==0);failCreate=true;setupDryContactTimers();
    assert(!command(DoorAction::Open)&&writes.empty());
    dryTogglePulse.~DryContactPulse();new(&dryTogglePulse)DryContactPulse();
    failCreate=false;setupDryContactTimers();setupDryContactTimers();assert(creates==1);
    for(auto action:{DoorAction::Open,DoorAction::Close,DoorAction::Toggle,DoorAction::Stop}){
      clear();assert(command(action));assert(writes.size()==1&&writes[0]==std::make_pair(22,HIGH));
      assert(!command(action)&&writes.size()==1&&timers.size()==1);
      complete();assert(writes.back()==std::make_pair(22,LOW));
    }
    clear();failStart=true;assert(!command(DoorAction::Open));
    assert(writes.empty());
    failStart=false;clear();expireDuringStart=true;assert(!command(DoorAction::Open)&&writes.empty());
    complete();expireDuringStart=false;clear();assert(command(DoorAction::Open));
    cancelDryContactTimers();assert(!command(DoorAction::Open));complete();
    setupDryContactTimers();clear();assert(command(DoorAction::Open));
    auto*t=timers.front();t->active=false;cancelDryContactTimers();setupDryContactTimers();
    auto count=writes.size();assert(!command(DoorAction::Open)&&writes.size()==count);
    t->callback(t->arg);timers.clear();clear();assert(command(DoorAction::Open));complete();
    assert(creates==1);

#else
    clear();assert(command(DoorAction::Open));
    assert((writes==std::vector<std::pair<int,int>>({{22,HIGH},{22,LOW}})));
    assert(creates==0);
#endif
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cpp = Path(temp) / "dry-contact.cpp"
            binary = Path(temp) / "dry-contact"
            cpp.write_text(harness)
            for target in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-D" + target,
                                "-fsanitize=address,undefined", str(cpp), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)



if __name__ == "__main__":
    unittest.main()
