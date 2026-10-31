"""Exercise actual polled door watchdogs; elapsed time is not position feedback."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ttc_cancel import block

ROOT = Path(__file__).resolve().parents[1]


class DoorStateDeadlines(unittest.TestCase):
    def test_stale_status_timeout_and_no_fabricated_end_position(self):
        source = (ROOT / "src/comms.cpp").read_text()
        deadline = block(source, "class PolledDoorDeadline") + ";"
        opening = block(source, "bool startDoorOpenCommand()")
        update = block(source, "void update_door_state(")
        status = update[update.index("    const bool stateChanged ="):update.index("    // Calculate door open/close duration")]
        harness = r'''
#include <cassert>
#include <cstdint>
#ifdef ESP8266
using _millis_t=uint32_t;
#else
using _millis_t=int64_t;
#endif
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
enum GarageDoorCurrentState { CURR_OPEN,CURR_CLOSED,CURR_OPENING,CURR_CLOSING,CURR_STOPPED };
enum class DoorAction {Open};
struct FunctionDelayLock{FunctionDelayLock(){}~FunctionDelayLock(){}};
_millis_t now=1000;
_millis_t _millis(){return now;}
bool comms_setup_done=true,wpDisconnectOnTx=false,admit=true;
constexpr int DOOR_CONTROL_SEC_PLUS_V2=2,DOOR_CONTROL_DRY_CONTACT=3,STATUS_DOOR_PIN=4,LOW=0,HIGH=1;
int doorControlType=2;
struct {int openDuration=2;GarageDoorCurrentState current_state=CURR_CLOSED;}garage_door,last_reported_garage_door;
unsigned queries=0,cancels=0,notifications=0;
GarageDoorCurrentState lastNotified=CURR_CLOSED;
void cancelPartialOpen(){}
void cancelPendingDoorIntent(){++cancels;}
void notify_homekit_current_door_state_change(GarageDoorCurrentState s){++notifications;lastNotified=s;}
void write_status_pin(int,int){}
void digitalWrite(int,int){}
void send_get_status(){++queries;}
bool door_command(DoorAction,DoorCommandLifecycle::Intent){return admit;}
bool functionDelayActive(){return false;}
void cancelFunctionDelay(){}
void cancel_builtin_TTC_countdown(){}
''' + deadline + r'''
PolledDoorDeadline checkDoorMoving,checkDoorCompleted;
''' + opening + r'''
void update(GarageDoorCurrentState current_state){
''' + status + r'''
    garage_door.current_state=current_state;
}
int main(){
    assert(startDoorOpenCommand());
    now+=500;update(CURR_CLOSED); // stale feedback is not movement confirmation
    now+=2500;checkDoorMoving.process();checkDoorCompleted.process();
    assert(cancels==1&&notifications==1&&lastNotified==CURR_CLOSED&&queries==0);
    assert(startDoorOpenCommand());now+=100;update(CURR_OPENING);
    now+=5000;checkDoorMoving.process();checkDoorCompleted.process();
    assert(cancels==2&&queries==1&&lastNotified==CURR_OPENING);
    assert(garage_door.current_state==CURR_OPENING); // Never invent fully Open.
    garage_door.current_state=CURR_CLOSED;now=UINT32_MAX-100;
    assert(startDoorOpenCommand());now+=2999;checkDoorMoving.process();assert(cancels==2);
    now+=1;checkDoorMoving.process();assert(cancels==3&&lastNotified==CURR_CLOSED);
    assert(startDoorOpenCommand());comms_setup_done=false;now+=6000;
    checkDoorMoving.process();checkDoorCompleted.process();assert(cancels==3);
}
'''
        harness = (ROOT / "src/door_command_lifecycle.h").read_text().replace("#pragma once", "") + harness
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "deadline.cpp", Path(directory) / "deadline"
            cpp.write_text(harness)
            for define in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined",
                                "-D" + define, str(cpp), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
