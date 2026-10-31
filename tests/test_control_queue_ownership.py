"""Execute production light/lock admission and lifecycle against a bounded SDK stub."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from test_door_queue_atomic import block, QUEUE_HARNESS_PREFIX

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("CONTROL_TEST_SOURCE", ROOT / "src/comms.cpp"))

class ControlQueueOwnership(unittest.TestCase):
    def test_production_controls(self):
        source = SOURCE.read_text()
        prefix = QUEUE_HARNESS_PREFIX.replace("PacketData m_data;Packet(", "PacketData m_data;Packet()=default;Packet(").replace("enum class PacketDataType {DoorAction};", "enum class PacketDataType {DoorAction,Light,Lock};")
        prefix = prefix.replace("enum class PacketCommand {DoorAction};", "enum class PacketCommand {DoorAction,Light,Lock};")
        prefix = prefix.replace("namespace secplus1Codes {", "namespace secplus1Codes {constexpr int LightButtonPress=3,LightButtonRelease=4,LockButtonPress=5,LockButtonRelease=6,QueryLightLockStatus=7;")
        prefix = prefix.replace("struct Value {struct Action", "struct Value {struct Light {LightState light=LightState::Off;bool pressed=false;}light;struct Lock {LockState lock=LockState::Off;bool pressed=false;}lock;struct Action")
        prefix = prefix.replace("enum class DoorAction", "enum class LightState {On,Off};enum class LockState {On,Off};enum LockCurrentState {CURR_UNLOCKED,CURR_LOCKED};constexpr int TGT_UNLOCKED=0,TGT_LOCKED=1;\nenum class DoorAction")
        prefix = prefix.replace("bool pinModeObstructionSensor=false;", "bool pinModeObstructionSensor=false,light=false,wallPanelEmulated=false;int current_lock=CURR_UNLOCKED,target_lock=TGT_UNLOCKED;")
        prefix = prefix.replace("QueueHandle_t xQueueCreate(unsigned,unsigned){queueState.items.clear();return &queueState;}", "bool failQueue=false;unsigned queueCreates=0;QueueHandle_t xQueueCreate(unsigned,unsigned){++queueCreates;if(failQueue)return nullptr;queueState.items.clear();return &queueState;}")
        prefix += r'''
int xQueueReceive(QueueHandle_t q,PacketAction *out,int){std::lock_guard<std::mutex>lock(q->mutex);if(q->items.empty())return 0;*out=q->items.front();q->items.pop_front();return pdTRUE;}
'''
        prefix += (ROOT / "src/door_command_lifecycle.h").read_text().replace("#pragma once", "") + r'''
DoorCommandLifecycle doorLifecycle;
uint32_t now=1000;uint32_t _millis(){return now;}
struct {int current_lock=0;bool light=false;}last_reported_garage_door;
void sec1_poll_status(int){}
bool functionDelayPending=false,functionDelayFinalWait=false;
void (*functionDelayCallback)()=nullptr;uint32_t functionDelayNextTick=0;
void sec1_light_press(uint32_t delay=0);
void sec1_light_release(uint8_t howManyReleases=2,uint32_t delay=0);
bool set_light(bool,bool=true);bool set_lock(bool,bool=true);
'''
        declarations = ["inline bool txQueueCreate()", "inline uint32_t txQueueCount()", "inline bool txQueuePushUnlocked(", "inline bool txQueueLock()", "inline void txQueueUnlock()", "inline bool txQueuePush(", "inline bool txQueuePushSequence(", "inline bool txQueuePop(", "inline bool txQueuePrepare()"]
        functions = "\n".join(block(source, d) for d in declarations)
        controls = source[source.index("#else  // USE_GDOLIB\nbool set_lock"):]
        functions += "\n" + block(controls, "bool set_lock(bool value, bool verify)")
        controls = controls[controls.index("void sec1_light_press"):]
        functions += "\n" + "\n".join(block(controls,d) for d in ["void sec1_light_press(","void sec1_light_release(","bool set_light("])
        functions += "\n" + block(source, "void cancelFunctionDelay()")
        # New production ownership helpers are included as one unit when present.
        start = source.find("// BEGIN CONTROL OWNERSHIP")
        end = source.find("// END CONTROL OWNERSHIP")
        ownership = source[start:end] if start >= 0 else "bool pendingLightOn=false,pendingLightOff=false,pendingLockOn=false,pendingLockOff=false;"
        harness = prefix + ownership + "\n" + functions + r'''
PacketAction filler(){PacketData d{};return {Packet(PacketCommand::DoorAction,d,0),false,0};}
void reset(unsigned count){queueState.items.clear();for(unsigned i=0;i<count;++i)queueState.items.push_back(filler());}
int main(){
 failQueue=true;assert(!txQueueCreate());assert(!txQueueReady&&txQueueCount()==0);
 auto rejected=filler();assert(!txQueuePush(&rejected));assert(!txQueuePushSequence(&rejected,1));
 failQueue=false;assert(txQueueCreate());unsigned created=queueCreates;
 assert(txQueueCreate()&&queueCreates==created);
 queueState.items.push_back(filler());lightReleaseReserved=true;
 assert(txQueuePrepare()&&queueState.items.empty()&&!lightReleaseReserved&&queueCreates==created);
 txQueueMutex->lock();assert(!txQueuePrepare());txQueueMutex->unlock();
 doorControlType=2;reset(16);
 assert(!set_light(true));reset(0);assert(set_light(true)); // Failed admission must permit retry.
 garage_door.light=true;set_light(true);garage_door.light=false;
 reset(16);assert(!set_lock(true));reset(0);assert(set_lock(true));
 now+=4000;reset(0);assert(set_lock(true)); // Missing acknowledgement cannot suppress forever.
 doorControlType=1;reset(15);assert(!set_light(false,false));assert(queueState.items.size()==15);
 reset(14);assert(set_light(false,false));assert(queueState.items.size()==16);
 assert(queueState.items[14].pkt.m_data.value.cmd==secplus1Codes::LightButtonPress);
 assert(queueState.items[15].pkt.m_data.value.cmd==secplus1Codes::LightButtonRelease);
 reset(15);assert(!set_lock(false,false));assert(queueState.items.size()==15);
 reset(14);assert(set_lock(false,false));assert(queueState.items.size()==16);
 reset(0);sec1_light_press(); // Held TTC press must reserve its eventual release.
 auto packet=filler();while(txQueuePush(&packet)){}
 assert(queueState.items.size()==15);sec1_light_release(4);
 assert(queueState.items.size()==16);
 assert(queueState.items.back().pkt.m_data.value.cmd==secplus1Codes::LightButtonRelease);
 reset(0);sec1_light_press();
 assert(set_light(false,false)&&lightReleaseReserved); // Explicit controls retain existing TTC behavior.
 while(txQueuePush(&packet)){}
 functionDelayPending=true;cancelFunctionDelay();
 assert(!functionDelayPending&&!lightReleaseReserved&&queueState.items.size()==16);
 assert(queueState.items.back().pkt.m_data.value.cmd==secplus1Codes::LightButtonRelease);
 // A transient producer collision cannot lose the held reservation.
 reset(0);sec1_light_press();txQueueMutex->lock();cancelFunctionDelay();
 assert(lightReleaseReserved);txQueueMutex->unlock();sec1_light_release();assert(!lightReleaseReserved);
 reset(0);lightIntent.reset();garage_door.light=false;
 bool first=false,second=false;
 std::thread a([&]{first=set_light(true);});std::thread b([&]{second=set_light(true);});
 a.join();b.join();assert(first!=second&&queueState.items.size()==3);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory)/"control.cpp", Path(directory)/"control"
            cpp.write_text(harness)
            subprocess.run(["c++","-std=c++17","-fsanitize=address,undefined","-pthread",str(cpp),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=5)

if __name__ == "__main__":
    unittest.main()
