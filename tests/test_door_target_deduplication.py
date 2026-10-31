"""Exercise public targets against actual bounded command admission."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ttc_cancel import block
from test_door_queue_atomic import QUEUE_HARNESS_PREFIX

ROOT = Path(__file__).resolve().parents[1]


class DoorTargetDeduplication(unittest.TestCase):
    def test_repeated_targets_keep_the_first_pair(self):
        source = (ROOT / "src/comms.cpp").read_text()
        declarations = ["inline bool txQueueCreate()", "inline uint32_t txQueueCount()",
                        "inline bool txQueuePushUnlocked(", "inline bool txQueueLock()",
                        "inline void txQueueUnlock()", "inline bool txQueuePush(",
                        "inline bool txQueuePushSequence(", "bool requestPendingDoorIntent(",
                        "bool door_command(DoorAction action, DoorCommandLifecycle::Intent intent)\n{",
                        "GarageDoorCurrentState rejectDoorCommand()",
                        "bool startDoorCloseCommand()", "void door_command_close()\n{",
                        "bool startDoorOpenCommand()", "void door_command_open()\n{",
                        "GarageDoorCurrentState open_door()", "GarageDoorCurrentState close_door(bool",
                        "GarageDoorCurrentState stop_door()", "GarageDoorCurrentState toggle_door(bool"]
        functions = "\n".join(block(source, declaration) for declaration in declarations)
        harness = QUEUE_HARNESS_PREFIX + (ROOT / "src/door_command_lifecycle.h").read_text().replace("#pragma once", "") + r'''
constexpr int DOOR_CONTROL_SEC_PLUS_V2=2,STATUS_DOOR_PIN=23;
#define DOOR_STATE(x) "state"
Door last_reported_garage_door;
Ticker checkDoorMoving,checkDoorCompleted;
struct Config{bool reverse=false;bool getReverseOnStop(){return reverse;}bool getUseToggle(){return false;}int getTTCseconds(){return 0;}}config,*userConfig=&config;
using _millis_t=uint32_t;
_millis_t now=1000,stopSentClosePending=0,stopSentOpenPending=0;
_millis_t _millis(){return now;}
DoorCommandLifecycle doorLifecycle;
bool wpDisconnectOnTx=false,TTCwasLightOn=false;
unsigned notifications=0;GarageDoorCurrentState lastNotified=CURR_OPEN;
int lastTargetNotified=-1;
void notify_homekit_current_door_state_change(GarageDoorCurrentState state){++notifications;lastNotified=state;}
void notify_homekit_target_door_state_change(int state){lastTargetNotified=state;}
void cancelPartialOpen(){}
bool functionDelayActive(){return false;}
void cancelFunctionDelay(){}
void cancel_builtin_TTC_countdown(){}
void set_light(bool){}
void delayFnCall(uint32_t,void(*)()){}
void cancelPendingDoorIntent(){doorLifecycle.cancel();pendingDoorCommand=false;}
bool door_command(DoorAction,DoorCommandLifecycle::Intent=DoorCommandLifecycle::Intent::None);
GarageDoorCurrentState open_door();GarageDoorCurrentState close_door(bool=false);
GarageDoorCurrentState stop_door();GarageDoorCurrentState toggle_door(bool=false);
void door_command_close();void door_command_open();
''' + functions + r'''
PacketAction pollPacket(){PacketData d{};return {Packet(PacketCommand::DoorAction,d,0),false,0};}
void reset(unsigned filled,GarageDoorCurrentState state){
    doorLifecycle.reset();pendingDoorCommand=false;assert(txQueueCreate());
    for(unsigned i=0;i<filled;++i)queueState.items.push_back(pollPacket());
    garage_door.current_state=state;config.reverse=false;
    garage_door.target_state=(state==CURR_CLOSED||state==CURR_CLOSING)?1:0;
    lastTargetNotified=-1;
    stopSentClosePending=stopSentOpenPending=0;checkDoorMoving.detach();checkDoorCompleted.detach();
}
int main(){
    reset(14,CURR_CLOSED);assert(open_door()==CURR_OPENING);
    const auto opening=queueState.items[14];assert(opening.pkt.m_data.value.door_action.action==DoorAction::Open);
    for(unsigned i=0;i<10;++i)assert(open_door()==CURR_CLOSED);
    assert(queueState.items.size()==16&&pendingDoorCommand&&doorLifecycle.allow(opening.doorGeneration,true));
    assert(queueState.items[14].doorGeneration==opening.doorGeneration&&checkDoorMoving.armed==1);
    // Wire Toggle still has the logical Close target.
    reset(14,CURR_OPEN);assert(close_door()==CURR_CLOSING);
    const auto closing=queueState.items[14];assert(closing.pkt.m_data.value.door_action.action==DoorAction::Toggle);
    for(unsigned i=0;i<10;++i)assert(close_door()==CURR_OPEN);
    assert(queueState.items.size()==16&&pendingDoorCommand&&doorLifecycle.allow(closing.doorGeneration,true));
    // Open -> Close(Stop) -> duplicate Close -> Open while physically opening.
    reset(14,CURR_OPENING);config.reverse=true;
    assert(open_door()==CURR_OPENING);assert(close_door()==CURR_STOPPED);
    const auto stopping=queueState.items[14];assert(stopping.pkt.m_data.value.door_action.action==DoorAction::Stop);
    assert(stopSentClosePending==now);close_door();
    assert(queueState.items.size()==16&&doorLifecycle.allow(stopping.doorGeneration,true)&&stopSentClosePending==now);
    assert(open_door()==CURR_OPENING);
    assert(!doorLifecycle.allow(stopping.doorGeneration,true)&&stopSentClosePending==0);
    // One available slot cannot accept a pair or arm optimistic watchdogs.
    reset(15,CURR_CLOSED);assert(open_door()==CURR_CLOSED);
    assert(queueState.items.size()==15&&!pendingDoorCommand&&!checkDoorMoving.armed&&!checkDoorCompleted.armed);
    assert(lastNotified==CURR_CLOSED&&lastTargetNotified==1);
    reset(15,CURR_OPEN);assert(close_door()==CURR_OPEN);
    assert(queueState.items.size()==15&&!pendingDoorCommand&&!checkDoorMoving.armed&&!checkDoorCompleted.armed);
    assert(lastNotified==CURR_OPEN&&lastTargetNotified==0);
    // The same void callback is used at TTC expiry; restore Target as well.
    lastTargetNotified=1;const auto delayedBefore=notifications;door_command_close();
    assert(notifications==delayedBefore+1&&lastNotified==CURR_OPEN&&lastTargetNotified==0);
    reset(15,CURR_OPENING);config.reverse=true;assert(close_door()==CURR_OPENING);
    assert(!pendingDoorCommand&&!stopSentClosePending);
    const auto before=notifications;door_command_close();
    assert(notifications==before+1&&lastNotified==CURR_OPENING&&lastTargetNotified==0);
    // Opposite intent cancels; a new Open replaces when room remains.
    reset(0,CURR_CLOSED);open_door();const auto old=queueState.items[0];
    close_door();assert(!doorLifecycle.allow(old.doorGeneration,true));
    assert(open_door()==CURR_OPENING&&queueState.items.size()==4&&pendingDoorCommand);
    assert(doorLifecycle.allow(queueState.items[2].doorGeneration,true)&&queueState.items[2].doorGeneration!=old.doorGeneration);
    // With only two free slots, the cancelled pair still occupies them. An
    // explicit rejection must leave actual state and watchdogs truthful.
    reset(14,CURR_CLOSED);open_door();close_door();
    assert(open_door()==CURR_CLOSED&&!pendingDoorCommand);
    assert(!checkDoorMoving.armed&&!checkDoorCompleted.armed);
    reset(15,CURR_OPENING);assert(stop_door()==CURR_OPENING&&!pendingDoorCommand);
    // Stop and Toggle are actions, so they do not share target deduplication.
    reset(0,CURR_OPENING);toggle_door();const auto toggling=queueState.items[0];toggle_door();
    assert(queueState.items.size()==4&&!doorLifecycle.allow(toggling.doorGeneration,true));
    // Reset removes the stored logical target, not just the pending flag.
    doorLifecycle.reset();pendingDoorCommand=false;queueState.items.clear();
    garage_door.current_state=CURR_CLOSED;
    assert(open_door()==CURR_OPENING&&queueState.items.size()==2&&pendingDoorCommand);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "targets.cpp", Path(directory) / "targets"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined", "-pthread",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
