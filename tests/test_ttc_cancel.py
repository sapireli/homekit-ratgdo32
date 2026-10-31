"""Run production delayed-close cancellation against a deterministic timer."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SOURCE = Path(os.environ.get("TTC_TEST_SOURCE", Path(__file__).resolve().parents[1] / "src/comms.cpp"))


def block(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for i in range(opening, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError("unclosed source block")


class TTCCancel(unittest.TestCase):
    def test_open_cancels_final_delayed_close(self):
        source = SOURCE.read_text()
        helpers = ""
        if "bool functionDelayActive()" in source:
            helpers = block(source, "class FunctionDelayLock") + ";\n"
            helpers += "\n".join(block(source, declaration) for declaration in
                                ["bool functionDelayActive()", "void cancelFunctionDelay()"])
        functions = "\n".join(block(source, declaration) for declaration in
                              ["GarageDoorCurrentState open_door()", "void processFunctionDelay()\n{", "void delayFnCall(", "void cancel_builtin_TTC_countdown()", "void shutdown_comms()"])
        harness = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <functional>
#include <mutex>
#include <thread>
#include <chrono>
#include <utility>
#if !defined(ESP8266) && !defined(ESP32)
#define ESP32
#endif
std::recursive_mutex delayMutex;
using SemaphoreHandle_t=std::recursive_mutex*;
constexpr int portMAX_DELAY=0;
SemaphoreHandle_t functionDelayMutex(){return &delayMutex;}
void xSemaphoreTakeRecursive(SemaphoreHandle_t m,int){m->lock();}
void xSemaphoreGiveRecursive(SemaphoreHandle_t m){m->unlock();}
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define DOOR_STATE(x) "state"
#ifdef ESP8266
using _millis_t=uint32_t;
#else
using _millis_t=int64_t;
#endif
enum GarageDoorCurrentState { CURR_OPEN, CURR_CLOSED, CURR_OPENING, CURR_CLOSING, CURR_STOPPED };
enum DoorAction { Stop };
constexpr int DOOR_CONTROL_DRY_CONTACT=3,DOOR_CONTROL_SEC_PLUS_V1=1;
int doorControlType=2;
constexpr int DOOR_CONTROL_SEC_PLUS_V2=2,UART_RX_PIN=21,UART_TX_PIN=22,DISCRETE_OPEN_PIN=-1,DISCRETE_CLOSE_PIN=-1,LOW=0;
bool comms_setup_done=true;
struct SerialPort{void end(){}}Sec1Serial,sw_serial;
void quiesce_gdo_tx(){}
void gpio_reset_pin(int){}
void gpio_pullup_dis(int){}
void gpio_pulldown_en(int){}
void digitalWrite(int,int){}
void write_status_pin(int,int){}
struct Door {GarageDoorCurrentState current_state=CURR_OPEN;bool light=false;uint32_t builtInTTCremaining=0;bool builtInTTChold=false;} garage_door,last_reported_garage_door;
struct Config {bool getReverseOnStop(){return false;}bool getTTClight(){return false;}} config,*userConfig=&config;
struct Ticker {
    std::function<void()> callback;
    bool enabled=false;
    bool active()const{return enabled;}
    void detach(){enabled=false;callback={};}
    template<class F>void once_ms(uint32_t,F f){enabled=true;callback=f;}
    template<class F>void attach_ms(uint32_t,F f){enabled=true;callback=f;}
    void fire(){auto f=callback;enabled=false;if(f)f();}
} TTCtimer,callbackDelay,checkDoorMoving,checkDoorCompleted;
uint32_t TTCiterations=0;
constexpr uint32_t TTCinterval=250;
_millis_t TTCendTime=0,stopSentClosePending=0,stopSentOpenPending=0;
bool TTCwasLightOn=false;
void (*functionDelayCallback)()=nullptr;
_millis_t functionDelayNextTick=0;
bool functionDelayPending=false,functionDelayFinalWait=false,functionDelayLight=false,functionDelaySound=false;
bool builtInTTCcountdownActive=false;
_millis_t builtInTTClastTick=0;
_millis_t now=1000;
_millis_t _millis(){return now;}
void set_light(bool,bool=true){}
void cancelPartialOpen(){}
constexpr int BEEPER_PIN=5;
void tone(int,int,int){}
void sec1_light_press(){}
void sec1_light_release(int){}
void sync_and_restart(){
#ifdef ESP32
    // Driver teardown may wait for an event task that needs the control lock.
    std::atomic<bool> finished{false};
    std::thread eventTask([&]{std::lock_guard<std::recursive_mutex> lock(delayMutex);finished=true;});
    for(int i=0;i<100&&!finished;++i)std::this_thread::sleep_for(std::chrono::milliseconds(1));
    assert(finished);
    eventTask.join();
#endif
}
unsigned closes=0;
std::atomic<bool> blockClose{false},closeEntered{false},releaseClose{false};
void door_command_close(){
    if(blockClose){closeEntered=true;while(!releaseClose)std::this_thread::yield();}
    ++closes;
}
void door_command_open(){}
bool door_command(DoorAction){return true;}
''' + (SOURCE.parent / "door_command_lifecycle.h").read_text().replace("#pragma once", "") + r'''
DoorCommandLifecycle doorLifecycle;
bool pendingDoorCommand=false;
GarageDoorCurrentState rejectDoorCommand(){return garage_door.current_state;}
bool startDoorOpenCommand(){return true;}
bool requestPendingDoorIntent(DoorCommandLifecycle::Intent){return false;}
bool door_command(DoorAction,DoorCommandLifecycle::Intent){return true;}
''' + helpers + functions + r'''
int main(){
    delayFnCall(0,door_command_close);
    now+=250;processFunctionDelay();
    assert(functionDelayActive() && functionDelayFinalWait);
    open_door();
    now+=1000;processFunctionDelay();processFunctionDelay();
    printf("close commands after explicit Open cancellation: %u\n",closes);
    assert(closes==0);

    delayFnCall(0,door_command_close);
    now+=250;processFunctionDelay();
    delayFnCall(0,nullptr);
    now+=250;processFunctionDelay();now+=500;processFunctionDelay();
    assert(closes==0);

    delayFnCall(0,door_command_close);now+=250;processFunctionDelay();
    builtInTTCcountdownActive=true;builtInTTClastTick=now;
    garage_door.builtInTTCremaining=17;garage_door.builtInTTChold=true;
    shutdown_comms();now+=1000;processFunctionDelay();
    assert(!builtInTTCcountdownActive&&!garage_door.builtInTTCremaining&&!garage_door.builtInTTChold&&!builtInTTClastTick);
    assert(closes==0);

    comms_setup_done=true;
    delayFnCall(0,door_command_close);
    now+=250;processFunctionDelay();now+=500;processFunctionDelay();processFunctionDelay();
    assert(closes==1);

#ifdef ESP32
    // A concurrent Open cannot slip between final acceptance and actuation.
    delayFnCall(0,door_command_close);now+=250;processFunctionDelay();now+=500;
    blockClose=true;
    std::thread executor([]{processFunctionDelay();});
    while(!closeEntered)std::this_thread::yield();
    std::atomic<bool> openReturned{false};
    std::thread canceller([&]{open_door();openReturned=true;});
    std::this_thread::sleep_for(std::chrono::milliseconds(20));
    assert(!openReturned);
    releaseClose=true;executor.join();canceller.join();
    assert(openReturned&&closes==2);
    delayFnCall(0,sync_and_restart);now+=250;processFunctionDelay();
    now+=500;processFunctionDelay();
#endif

    const unsigned beforeWrap=closes;
    now=UINT32_MAX-100;delayFnCall(0,door_command_close);
    now+=90;processFunctionDelay();
    assert(!functionDelayFinalWait&&closes==beforeWrap);
    now+=160;processFunctionDelay();assert(functionDelayFinalWait);
    now+=500;processFunctionDelay();assert(closes==beforeWrap+1);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cpp = Path(temp) / "ttc.cpp"
            exe = Path(temp) / "ttc"
            cpp.write_text(harness)
            for define in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined", "-pthread",
                                "-D" + define, *(["-DRATGDO32_DISCO"] if define == "ESP32" else []), str(cpp), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
