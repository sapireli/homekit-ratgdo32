"""Exercise actual control admission/dispatch with serial and feedback boundaries stubbed."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_control_queue_ownership import SOURCE, control_fixture
from test_door_queue_atomic import block

class ControlArbitration(unittest.TestCase):
    def test_queued_written_and_feedback_transitions(self):
        source = SOURCE.read_text()
        harness = control_fixture(source).replace("enum class LightState {On,Off}", "enum class LightState {On,Off,Toggle,Toggle2}").replace("enum class LockState {On,Off}", "enum class LockState {On,Off,Toggle}") + r'''
constexpr int DOOR_CONTROL_SEC_PLUS_V2=2,MAX_COMMS_RETRY=2,SECPLUS1_TX_WINDOW_CLOSE=200;
uint32_t last_tx=0,tx_minimum_delay=0,msg_start=0;
bool wallPanelDetected=false,clearToSend=true,collision=false;
bool isRxPending(){return false;}
void notify_homekit_target_lock(int value){garage_door.target_lock=value;}
PacketAction *writingDoorPacket=nullptr;
std::deque<PacketAction> sent;
std::function<void()> duringWrite;
void markDoorPacketWriting();
bool transmitSec1(unsigned){
 if(collision)return false;
 markDoorPacketWriting();if(packetControl(*writingDoorPacket))sent.push_back(*writingDoorPacket);last_tx=now;
 if(duringWrite){auto callback=duringWrite;duringWrite=nullptr;callback();}
 return true;
}
bool transmitSec2(PacketAction&){return transmitSec1(0);}
bool txQueuePeek(PacketAction *out){if(queueState.items.empty())return false;*out=queueState.items.front();return true;}
'''
        harness += "\n".join(block(source, declaration) for declaration in [
            "void markDoorPacketWriting()", "bool process_PacketAction(PacketAction &pkt_ac)\n{",
            "bool process_send_queue()"])
        if "void processControlIntents()" in source:
            harness += "\n" + block(source, "void processControlIntents()\n{")
        else:
            harness += "\nvoid processControlIntents(){}"
        fresh = "void status(bool value)" in source
        if fresh:
            harness += "\n" + block(source, "bool recordLightStatus(bool value)")
            harness += "\n" + block(source, "bool recordLockStatus(bool value)")
            harness += "\nvoid observeLight(bool value){recordLightStatus(value);}"
            harness += "\nvoid observeLock(bool value){recordLockStatus(value);}"
        else:
            harness += "\nvoid observeLight(bool value){garage_door.light=value;lightIntent.clear();}"
            harness += "\nvoid observeLock(bool value){garage_door.current_lock=value?CURR_LOCKED:CURR_UNLOCKED;lockIntent.clear();}"
        status_case = block(source[source.index("void sec1_process_message"):], "case secplus1Codes::QueryLightLockStatus:")
        harness += r'''
#define ESP_LOGV(...) ((void)0)
#define bitRead(value,bit) (((value)>>(bit))&1)
bool functionDelayActive(){return functionDelayPending;}
struct {struct {bool lightKey=false,lockKey=false;}bit;}motionTriggers;
void publish_homekit_light(bool){}
void notify_homekit_light(bool value){garage_door.light=value;}
void publish_homekit_current_lock(int){}
void notify_homekit_motion(bool){}
void manual_recovery(){}
using LockTargetState=int;
'''
        harness += "\nvoid receiveStatus(uint8_t value){switch(secplus1Codes::QueryLightLockStatus){" + status_case + "}}"
        command_cases = "\n".join(block(source[source.index("void comms_loop_sec2()"):], name) for name in ["case PacketCommand::Lock:", "case PacketCommand::Light:"])
        harness += "\nvoid receiveCommand(PacketCommand command,const Packet &pkt){switch(command){" + command_cases + "default:break;}}"

        harness += r'''
PacketAction filler(){PacketData d{};return {Packet(PacketCommand::DoorAction,d,0),false,0};}
void reset(int protocol=1){
 queueState.items.clear();lightIntent.reset();lockIntent.reset();sent.clear();collision=false;
 duringWrite=nullptr;doorControlType=protocol;now+=4000;garage_door.light=false;
 garage_door.current_lock=CURR_UNLOCKED;garage_door.target_lock=TGT_UNLOCKED;
}
void step(){++now;process_send_queue();}
void drain(){for(unsigned i=0;!queueState.items.empty()&&i<50;++i)step();assert(queueState.items.empty());}
unsigned presses(PacketDataType type){unsigned result=0;for(const auto &p:sent)if(p.pkt.m_data.type==type&&p.doorPress)++result;return result;}
int main(){
 assert(txQueueCreate());reset();
 assert(set_light(true));auto stale=queueState.items.front();
 assert(set_light(false));drain();assert(sent.empty()); // Cancel unwritten opposite, no toggle.
 assert(set_lock(true));assert(set_lock(false));drain();assert(sent.empty());

 reset();assert(set_light(true));step();auto token=sent.back().doorGeneration;
 assert(lightIntent.needsRelease(token));assert(set_light(false));
 observeLight(false);processControlIntents(); // Feedback before Release cannot authorize.
 assert(queueState.items.size()==4&&presses(PacketDataType::Light)==1);
 step();drain();processControlIntents();assert(queueState.items.empty());
 assert(lightIntent.pending(false));observeLight(false);processControlIntents();
 assert(!lightIntent.pending(false)&&queueState.items.empty()); // Unchanged status settles target.

 reset();assert(set_light(true));step();assert(set_light(false));step();drain();
 now+=3000;processControlIntents();assert(queueState.items.empty()&&!lightIntent.pending(false));
 assert(set_light(true));processControlIntents();drain();assert(presses(PacketDataType::Light)==1);
 observeLight(false);processControlIntents();assert(!queueState.items.empty()); // Expiry then fresh unchanged feedback recovers.
 drain();assert(presses(PacketDataType::Light)==2);

 reset();assert(set_light(true));step();token=sent.back().doorGeneration;
 while(txQueuePush(&stale)){};assert(queueState.items.size()==16);
 assert(set_light(false));assert(set_light(true));assert(set_light(false)); // Latest target wins.
 collision=true;for(unsigned i=0;i<10;++i)step();
 assert(lightIntent.needsRelease(token)&&queueState.items.size()==16);
 collision=false;step();observeLight(true);processControlIntents();
 assert(queueState.items.size()==15&&presses(PacketDataType::Light)==1); // Only one slot: retain deferred intent.
 drain();processControlIntents();assert(!queueState.items.empty());drain();
 assert(presses(PacketDataType::Light)==2);

 reset();assert(set_light(true));stale=queueState.items.front();collision=true;
 for(unsigned i=0;i<3;++i)step();collision=false;drain();
 assert(!lightIntent.pending(true)&&sent.empty());assert(set_light(true));
 assert(process_PacketAction(stale));assert(sent.empty()); // Terminal failure retires stale generation.

 reset(2);assert(set_light(true));
 duringWrite=[](){assert(set_light(false));observeLight(false);};step();
 drain();processControlIntents();assert(queueState.items.empty()); // Sec2 must complete before feedback counts.
 observeLight(true);processControlIntents();assert(queueState.items.size()==2);
 drain();assert(presses(PacketDataType::Light)==2);

 reset();assert(set_lock(true));step();assert(set_lock(false));step();drain();
 observeLight(true);processControlIntents();assert(queueState.items.empty()&&lockIntent.pending(false));
 observeLock(true);processControlIntents();assert(!queueState.items.empty());drain();
 assert(presses(PacketDataType::Lock)==2); // Only typed lock status authorizes lock reconciliation.
 reset();assert(set_light(true));step();drain();
 recordLightStatus(true); // Authoritative state precedes client publication.
 assert(set_light(false));publish_homekit_light(true);drain();
 assert(presses(PacketDataType::Light)==2);
 reset(2);assert(set_light(true));step();assert(set_light(false));drain();
 PacketData echoData{};echoData.type=PacketDataType::Light;echoData.value.light.light=LightState::On;
 receiveCommand(PacketCommand::Light,Packet(PacketCommand::Light,echoData,0));
 processControlIntents();assert(lightIntent.pending(false)&&queueState.items.empty());
 observeLight(true);processControlIntents();drain();assert(presses(PacketDataType::Light)==2);
 reset(2);assert(set_lock(true));step();assert(set_lock(false));drain();
 echoData.type=PacketDataType::Lock;echoData.value.lock.lock=LockState::On;
 receiveCommand(PacketCommand::Lock,Packet(PacketCommand::Lock,echoData,0));
 assert(garage_door.target_lock==TGT_UNLOCKED&&publishedTarget==TGT_UNLOCKED);
 processControlIntents();assert(lockIntent.pending(false)&&queueState.items.empty());
 observeLock(true);processControlIntents();drain();assert(presses(PacketDataType::Lock)==2);
 reset(2);assert(set_light(true));step();drain();now+=3000;processControlIntents();
 assert(set_light(false)); // Explicit absolute Sec2 retry after expiry is safe.
 assert(queueState.items.size()==2);drain();assert(presses(PacketDataType::Light)==2);
 reset();assert(set_light(true));step();assert(set_light(false));step();drain();
 receiveStatus(0x00);receiveStatus(0x00);processControlIntents();
 assert(queueState.items.empty()&&lightIntent.pending(false)); // Invalid repeated bytes are not feedback.
 receiveStatus(0x54);receiveStatus(0x54);processControlIntents();
 assert(!queueState.items.empty());drain();assert(presses(PacketDataType::Light)==2);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory)/"arbitration.cpp", Path(directory)/"arbitration"
            cpp.write_text(harness)
            subprocess.run(["c++","-std=c++17","-fsanitize=address,undefined","-pthread",str(cpp),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=5)

if __name__ == "__main__": unittest.main()
