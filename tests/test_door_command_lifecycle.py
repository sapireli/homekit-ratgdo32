"""Run production intent arbitration with real high-level door decision paths."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_ttc_cancel import block

ROOT = Path(__file__).resolve().parents[1]


class DoorCommandLifecycleTest(unittest.TestCase):
    def test_pending_reversals_and_wire_commit(self):
        source = (ROOT / "src/comms.cpp").read_text()
        functions = "\n".join(block(source, declaration) for declaration in [
            "bool requestPendingDoorIntent(", "void processPendingDoorIntent()\n{",
            "GarageDoorCurrentState open_door()", "GarageDoorCurrentState close_door(bool",
            "GarageDoorCurrentState stop_door()", "GarageDoorCurrentState toggle_door(bool",
            "void processPartialOpen()\n{"])
        harness = r'''
#include <cassert>
#include <cstdint>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define DOOR_STATE(x) "state"
''' + (ROOT / "src/door_command_lifecycle.h").read_text().replace("#pragma once", "") + r'''
enum GarageDoorCurrentState { CURR_OPEN, CURR_CLOSED, CURR_OPENING, CURR_CLOSING, CURR_STOPPED };
enum class DoorAction { Open, Close, Stop, Toggle };
struct FunctionDelayLock {FunctionDelayLock(){} ~FunctionDelayLock(){}};
struct Ticker {void detach(){}} checkDoorMoving,checkDoorCompleted;
constexpr int DOOR_CONTROL_DRY_CONTACT=3;
int doorControlType=2;
using _millis_t=uint32_t;
_millis_t now=1000,stopSentClosePending=0,stopSentOpenPending=0;
_millis_t _millis(){return now;}
bool comms_setup_done=true,pendingDoorCommand=false,TTCwasLightOn=false;
struct Door {GarageDoorCurrentState current_state=CURR_OPEN;bool obstructed=false;}garage_door,last_reported_garage_door;
struct Config {bool getReverseOnStop(){return false;}int getTTCseconds(){return 0;}}config,*userConfig=&config;
DoorCommandLifecycle doorLifecycle;
bool doingPartial=false,partialAwaitingMotion=false;
_millis_t partialStartDeadline=0,partialStopDeadline=0,partialDuration=0;
GarageDoorCurrentState rejectDoorCommand(){return garage_door.current_state;}
void cancelPartialOpen(){doingPartial=false;partialAwaitingMotion=false;}
void cancel_builtin_TTC_countdown(){}
bool functionDelayActive(){return false;}
void cancelFunctionDelay(){}
void set_light(bool){}
void delayFnCall(uint32_t,void(*)()){}
struct Command {DoorAction action;uint32_t token;};
std::vector<Command> queued;
bool admit=true;
bool door_command(DoorAction action, DoorCommandLifecycle::Intent intent=DoorCommandLifecycle::Intent::None){
    if(!admit||pendingDoorCommand)return false;
    queued.push_back({action,doorLifecycle.begin(garage_door.current_state,now,intent)});
    pendingDoorCommand=true;return true;
}
bool startDoorOpenCommand(){return door_command(DoorAction::Open,DoorCommandLifecycle::Intent::Open);}
void door_command_open(){startDoorOpenCommand();}
bool startDoorCloseCommand(){return door_command(DoorAction::Close,DoorCommandLifecycle::Intent::Close);}
void door_command_close(){startDoorCloseCommand();}
GarageDoorCurrentState open_door();
GarageDoorCurrentState close_door(bool=false);
GarageDoorCurrentState stop_door();
GarageDoorCurrentState toggle_door(bool=false);
''' + functions + r'''
void status(GarageDoorCurrentState state){
    doorLifecycle.status(state);pendingDoorCommand=doorLifecycle.pending();garage_door.current_state=state;
}
void reset(GarageDoorCurrentState state){
    doorLifecycle.reset();pendingDoorCommand=false;queued.clear();garage_door.current_state=state;now+=100;
}
int main(){
    // Queued Close must be cancelled by Open even while cached state says Open.
    reset(CURR_OPEN);close_door();auto close=queued.back();
    open_door();assert(!doorLifecycle.allow(close.token,true));assert(!pendingDoorCommand);
    // Queued Stop must be cancelled by latest Open while still opening.
    reset(CURR_OPENING);close_door();auto stop=queued.back();assert(stop.action==DoorAction::Stop);
    open_door();assert(!doorLifecycle.allow(stop.token,true));assert(queued.size()==1);
    // Once Stop was attempted, preserve Release then resume after real STOPPED.
    reset(CURR_OPENING);close_door();stop=queued.back();doorLifecycle.writing(stop.token,true);
    open_door();status(CURR_OPENING);processPendingDoorIntent();assert(queued.size()==1);
    status(CURR_STOPPED);processPendingDoorIntent();assert(queued.size()==1);
    assert(doorLifecycle.allow(stop.token,false));doorLifecycle.writing(stop.token,false);
    processPendingDoorIntent();assert(queued.size()==2&&queued.back().action==DoorAction::Open);
    // A wire-committed Close followed by Open uses physical closing feedback to Stop.
    reset(CURR_OPEN);close_door();close=queued.back();doorLifecycle.writing(close.token,true);
    open_door();status(CURR_OPEN);doorLifecycle.writing(close.token,false);
    processPendingDoorIntent();assert(queued.size()==1&&pendingDoorCommand);
    status(CURR_CLOSING);processPendingDoorIntent();assert(queued.size()==2&&queued.back().action==DoorAction::Stop);
    // Collision before writing leaves the whole pair cancellable.
    reset(CURR_OPEN);close_door();close=queued.back();assert(doorLifecycle.allow(close.token,true));
    open_door();assert(!doorLifecycle.allow(close.token,true)&&!doorLifecycle.allow(close.token,false));
    // An echo failure after write must not retry the physical Press.
    reset(CURR_OPEN);close_door();close=queued.back();doorLifecycle.writing(close.token,true);
    assert(!doorLifecycle.allow(close.token,true)&&doorLifecycle.allow(close.token,false));
    // Intent expiry clears delayed motion, but keeps the mandatory release.
    open_door();now+=3000;processPendingDoorIntent();assert(!pendingDoorCommand&&queued.size()==1);
    assert(doorLifecycle.allow(close.token,false));doorLifecycle.writing(close.token,false);
    status(CURR_CLOSING);processPendingDoorIntent();assert(queued.size()==1);
    reset(CURR_OPEN);close_door();close=queued.back();doorLifecycle.writing(close.token,true);
    open_door();doorLifecycle.status(255);doorLifecycle.writing(close.token,false);
    processPendingDoorIntent();assert(queued.size()==1&&!pendingDoorCommand);
    // Physical movement before our queued Press invalidates stale intent.
    reset(CURR_OPEN);close_door();close=queued.back();status(CURR_CLOSING);
    assert(!doorLifecycle.allow(close.token,true));
    // Resource failure must not fabricate a pending command.
    reset(CURR_OPEN);admit=false;close_door();assert(!pendingDoorCommand&&queued.empty());admit=true;
    // Unsigned elapsed expiry is valid across the 32-bit uptime wrap.
    reset(CURR_OPEN);now=UINT32_MAX-100;close_door();close=queued.back();
    doorLifecycle.writing(close.token,true);open_door();now+=3001;processPendingDoorIntent();
    assert(!pendingDoorCommand&&queued.size()==1&&doorLifecycle.allow(close.token,false));
    comms_setup_done=false;processPendingDoorIntent();assert(!doorLifecycle.allow(close.token,false));
    comms_setup_done=true;reset(CURR_CLOSED);door_command(DoorAction::Open);
    auto opening=queued.back();doorLifecycle.writing(opening.token,true);status(CURR_OPENING);
    doingPartial=true;partialStopDeadline=now;processPartialOpen();
    assert(!doingPartial&&queued.size()==1);
    doorLifecycle.writing(opening.token,false);processPendingDoorIntent();
    assert(queued.size()==2&&queued.back().action==DoorAction::Stop);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "lifecycle.cpp", Path(directory) / "lifecycle"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
