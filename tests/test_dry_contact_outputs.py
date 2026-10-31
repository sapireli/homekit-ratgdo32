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
    def test_disconnected_and_configured_outputs(self):
        header = (ROOT / "src/ratgdo.h").read_text()
        helpers = "\n".join(block(header, name) for name in [
            "inline void write_status_pin(", "inline void setup_status_pin(",
            "inline void configure_dry_contact_output("])
        source = (ROOT / "src/comms.cpp").read_text()
        start = source.index("        // Dry contact commands\n", source.index("bool door_command(DoorAction action, DoorCommandLifecycle::Intent intent)\n{"))
        end = source.index("\n    }\n    return true;", start)
        command = source[start:end]
        pulse = source[source.index("class DryContactPulse"):source.index("// times in miliseconds")]
        pulse = pulse[:pulse.rfind("#endif")]
        setup = block(source, "void setup_comms()")
        self.assertEqual(setup.count("setupDryContactTimers();"), 1)
        self.assertIn("configure_dry_contact_output(DISCRETE_CLOSE_PIN);\n#ifdef ESP32\n        setupDryContactTimers();", setup)
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
#define ESP32 1
#define OUTPUT 1
#define LOW 0
#define HIGH 1
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
using gpio_num_t=int;
constexpr int GPIO_MODE_OUTPUT=1, GPIO_PULLUP_DISABLE=0, GPIO_PULLDOWN_ENABLE=1, GPIO_INTR_DISABLE=0;
struct gpio_config_t { uint64_t pin_bit_mask; int mode, pull_up_en, pull_down_en, intr_type; };
std::vector<std::pair<int,int>> writes;
std::vector<int> modes, preloads;
std::vector<uint64_t> configs;
struct Timer {void(*callback)(void*);void*arg;bool active=false;};
using esp_timer_handle_t=Timer*;
struct esp_timer_create_args_t {void(*callback)(void*);void*arg;int dispatch_method;const char*name;};
constexpr int ESP_OK=0,ESP_TIMER_TASK=0;
Timer storage[3];unsigned creates=0;
std::vector<Timer*> timers;
bool failCreate=false,failStart=false,failToggleStart=false,expireDuringStart=false;
int esp_timer_create(const esp_timer_create_args_t*a,esp_timer_handle_t*t){
 assert(!criticalDepth);if(failCreate)return -1;assert(creates<3);auto*p=&storage[creates++];*p={a->callback,a->arg,false};*t=p;return ESP_OK;}
int esp_timer_start_once(esp_timer_handle_t t,uint64_t us){
    assert(!criticalDepth&&us==500000);
    if(failStart||(failToggleStart&&t==&storage[0]))
        return -1;
    assert(!t->active);
    t->active=true;
    timers.push_back(t);
    if(expireDuringStart){t->active=false;t->callback(t->arg);}
    return ESP_OK;
}
int esp_timer_stop(esp_timer_handle_t t){assert(!criticalDepth);if(!t->active)return -1;t->active=false;return ESP_OK;}
void gpio_set_level(int pin,int value) { assert(pin>=0 && value==0); preloads.push_back(pin); }
void gpio_config(const gpio_config_t *c) { assert(c->pin_bit_mask); configs.push_back(c->pin_bit_mask); }
void pinMode(int pin,int) { assert(pin>=0); modes.push_back(pin); }
void digitalWrite(int pin,int value) { assert(pin>=0); writes.emplace_back(pin,value); }
enum class DoorAction { Open, Close, Toggle, Stop };
enum GarageDoorCurrentState { CURR_OPEN, CURR_CLOSED, CURR_STOPPED };
struct { GarageDoorCurrentState current_state=CURR_CLOSED; } garage_door;
int DISCRETE_OPEN_PIN=-1, DISCRETE_CLOSE_PIN=-1;
constexpr int UART_TX_PIN=22;
''' + helpers + pulse + r'''
bool command(DoorAction action) {
''' + command + r'''
    return true;
}
void clear() { writes.clear(); modes.clear(); preloads.clear(); configs.clear(); timers.clear(); }
void complete() { auto pending=timers; timers.clear(); for(auto*t:pending)if(t->active){t->active=false;t->callback(t->arg);} }
int main() {
    assert(creates==0); // Protocol modes do not allocate pulse timers.
    configure_dry_contact_output(-1); setup_status_pin(-1); write_status_pin(-1,HIGH);
    assert(writes.empty() && modes.empty() && preloads.empty() && configs.empty());
    configure_dry_contact_output(UART_TX_PIN);
    assert(preloads==std::vector<int>{22} && configs==std::vector<uint64_t>{1ULL<<22});
    // Allocation failure must not assert any of a command's outputs.
    clear();failCreate=true;setupDryContactTimers();assert(!command(DoorAction::Open)&&writes.empty());
    // Reset failed setup fixture as a reboot would; production never retries allocation.
    dryTogglePulse.~DryContactPulse();new(&dryTogglePulse)DryContactPulse();
    failCreate=false;setupDryContactTimers();assert(creates==1);
    clear(); assert(command(DoorAction::Open));
    assert(writes.size()==1 && writes[0]==std::make_pair(22,HIGH) && timers.size()==1);
    assert(!command(DoorAction::Open)&&writes.size()==1&&timers.size()==1);
    complete(); assert(writes.back()==std::make_pair(22,LOW));
    clear(); garage_door.current_state=CURR_OPEN;
    assert(!command(DoorAction::Open) && writes.empty() && timers.empty());
    assert(command(DoorAction::Close) && writes.size()==1 && timers.size()==1);
    complete(); clear();
    garage_door.current_state=CURR_CLOSED;
    assert(!command(DoorAction::Close) && writes.empty() && timers.empty());
    DISCRETE_OPEN_PIN=16; DISCRETE_CLOSE_PIN=17;
    setupDryContactTimers();assert(creates==3);
    configure_dry_contact_output(16); configure_dry_contact_output(17);
    assert(configs.size()==2 && configs[0]==(1ULL<<16) && configs[1]==(1ULL<<17));
    clear(); assert(command(DoorAction::Open));
    assert(writes.size()==2 && writes[0]==std::make_pair(16,HIGH) && writes[1]==std::make_pair(22,HIGH));
    assert(timers.size()==2); complete();
    assert(writes[2]==std::make_pair(16,LOW) && writes[3]==std::make_pair(22,LOW));
    clear(); garage_door.current_state=CURR_OPEN; assert(command(DoorAction::Close));
    assert(writes[0]==std::make_pair(17,HIGH) && writes[1]==std::make_pair(22,HIGH));
    complete();clear();
    // Busy toggle must reject before a discrete output is asserted.
    assert(command(DoorAction::Toggle));size_t count=writes.size();
    garage_door.current_state=CURR_CLOSED;
    assert(!command(DoorAction::Open)&&writes.size()==count);complete();clear();
    // Failed start deasserts immediately and allows a later retry.
    failStart=true;assert(!command(DoorAction::Open));
    assert(writes.empty());
    failStart=false;failToggleStart=true;clear();assert(!command(DoorAction::Open));
    assert(writes.empty());
    complete();failToggleStart=false;clear();expireDuringStart=true;assert(!command(DoorAction::Open)&&writes.empty());
    complete();expireDuringStart=false;clear();assert(command(DoorAction::Open));
    // Teardown cancels timers and forces LOW without freeing callback storage.
    cancelDryContactTimers();assert(!command(DoorAction::Open));
    complete();assert(writes.back()==std::make_pair(17,LOW));
    setupDryContactTimers();assert(creates==3);clear();assert(command(DoorAction::Open));complete();
    // An expired callback remains the owner until it writes LOW and returns.
    clear();assert(command(DoorAction::Open));auto*t=timers.front();t->active=false;
    cancelDryContactTimers();setupDryContactTimers();count=writes.size();
    assert(!command(DoorAction::Open)&&writes.size()==count);
    t->callback(t->arg);timers.clear();clear();assert(command(DoorAction::Open));complete();
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cpp = Path(temp) / "dry-contact.cpp"
            binary = Path(temp) / "dry-contact"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
