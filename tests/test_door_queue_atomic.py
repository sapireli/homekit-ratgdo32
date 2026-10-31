"""Exercise actual command admission with bounded queues and racing producers."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SOURCE = Path(os.environ.get("COMMAND_TEST_SOURCE", Path(__file__).resolve().parents[1] / "src/comms.cpp"))


def block(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for i in range(opening, len(source)):
        depth += (source[i] == "{") - (source[i] == "}")
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError("unclosed source block")


class DoorQueueAtomic(unittest.TestCase):
    def test_press_release_admission(self):
        source = SOURCE.read_text()
        declarations = ["inline bool txQueueCreate()", "inline uint32_t txQueueCount()"]
        if "inline bool txQueuePushSequence(" in source:
            declarations += ["inline bool txQueuePushUnlocked(", "inline bool txQueueLock()",
                             "inline void txQueueUnlock()"]
        declarations += ["inline bool txQueuePush("]
        if "inline bool txQueuePushSequence(" in source:
            declarations += ["inline bool txQueuePushSequence("]
        declarations += ["bool door_command(DoorAction action)\n{"]
        functions = "\n".join(block(source, declaration) for declaration in declarations)
        harness = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <thread>
#define ESP32
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define COMMAND_QUEUE_SIZE 16
constexpr int pdTRUE=1,DOOR_CONTROL_DRY_CONTACT=3,DOOR_CONTROL_SEC_PLUS_V1=1;
constexpr int DISCRETE_OPEN_PIN=-1,DISCRETE_CLOSE_PIN=-1,UART_TX_PIN=22,HIGH=1,LOW=0;
enum class DoorAction {Open,Close,Stop,Toggle};
enum class PacketDataType {DoorAction};
enum class PacketCommand {DoorAction};
namespace secplus1Codes {constexpr int DoorButtonPress=1,DoorButtonRelease=2;}
struct PacketData {
    PacketDataType type;
    struct Value {struct Action {DoorAction action;bool pressed=false;int id=0;}door_action;int cmd=0;}value;
};
struct Packet {PacketData m_data;Packet(PacketCommand,PacketData data,uint32_t):m_data(data){}};
struct PacketAction {Packet pkt;bool inc_counter;uint32_t delay;};
struct Queue {std::deque<PacketAction>items;std::mutex mutex;}queueState;
using QueueHandle_t=Queue*;
using StaticSemaphore_t=std::mutex;
using SemaphoreHandle_t=std::mutex*;
QueueHandle_t pkt_q=nullptr;
StaticSemaphore_t txQueueMutexStorage;
SemaphoreHandle_t txQueueMutex=nullptr;
SemaphoreHandle_t xSemaphoreCreateMutexStatic(StaticSemaphore_t*p){return p;}
int xSemaphoreTake(SemaphoreHandle_t p,int){return p->try_lock();}
void xSemaphoreGive(SemaphoreHandle_t p){p->unlock();}
QueueHandle_t xQueueCreate(unsigned,unsigned){queueState.items.clear();return &queueState;}
unsigned uxQueueMessagesWaiting(QueueHandle_t q){std::lock_guard<std::mutex>lock(q->mutex);return q->items.size();}
std::atomic<bool> pausePress{false},pressQueued{false},continuePress{false};
int xQueueSendToBack(QueueHandle_t q,const PacketAction*p,int){
    {std::lock_guard<std::mutex>lock(q->mutex);if(q->items.size()==16)return 0;q->items.push_back(*p);}
    if(pausePress&&p->pkt.m_data.value.door_action.pressed){
        pressQueued=true;while(!continuePress)std::this_thread::yield();
    }
    return pdTRUE;
}
std::recursive_mutex controlMutex;
struct FunctionDelayLock {FunctionDelayLock(){controlMutex.lock();}~FunctionDelayLock(){controlMutex.unlock();}};
struct Ticker {template<class F>void once_ms(unsigned,F){}};
enum GarageDoorCurrentState{CURR_OPEN,CURR_CLOSED,CURR_STOPPED};
struct Door{GarageDoorCurrentState current_state=CURR_OPEN;}garage_door;
std::atomic<bool>pendingDoorCommand{false};
int doorControlType=2;uint32_t id_code=1;
void send_get_status(){}
void write_status_pin(int,int){}
void digitalWrite(int,int){}
''' + functions + r'''
PacketAction pollPacket(){PacketData d{};return {Packet(PacketCommand::DoorAction,d,0),false,0};}
void reset(unsigned filled){
    pendingDoorCommand=false;pausePress=false;pressQueued=false;continuePress=false;
    assert(txQueueCreate());for(unsigned i=0;i<filled;++i)queueState.items.push_back(pollPacket());
}
int main(){
    reset(15);
    assert(!door_command(DoorAction::Close));
    assert(queueState.items.size()==15); // Never leave an orphan button press.
    assert(!pendingDoorCommand);
    reset(14);
    assert(door_command(DoorAction::Close));
    assert(queueState.items.size()==16&&pendingDoorCommand);
    assert(queueState.items[14].pkt.m_data.value.door_action.pressed);
    assert(!queueState.items[15].pkt.m_data.value.door_action.pressed);

    reset(14);pausePress=true;
    bool accepted=false;
    std::thread door([&]{accepted=door_command(DoorAction::Close);});
    while(!pressQueued)std::this_thread::yield();
    auto poll=pollPacket();
    assert(!txQueuePush(&poll)); // Another producer cannot steal the release slot.
    continuePress=true;door.join();
    assert(accepted&&queueState.items.size()==16);
    assert(!queueState.items.back().pkt.m_data.value.door_action.pressed);

    reset(0);bool first=false,second=false;
    std::thread a([&]{first=door_command(DoorAction::Open);});
    std::thread b([&]{second=door_command(DoorAction::Close);});
    a.join();b.join();assert(first!=second&&queueState.items.size()==2);

    doorControlType=1;reset(14);
    assert(door_command(DoorAction::Close)); // Optional repeated release may be dropped.
    assert(queueState.items.size()==16&&!queueState.items.back().pkt.m_data.value.door_action.pressed);
}
'''
        with tempfile.TemporaryDirectory() as temp:
            cpp = Path(temp) / "queue.cpp"
            exe = Path(temp) / "queue"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined", "-pthread",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
