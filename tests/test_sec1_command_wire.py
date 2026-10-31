"""Execute actual Sec1 transmit/dispatch for collision, echo failure, and release."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ttc_cancel import block

ROOT = Path(__file__).resolve().parents[1]


class Sec1CommandWire(unittest.TestCase):
    def test_actual_uart_boundary_and_bounded_missing_echo(self):
        source = (ROOT / "src/comms.cpp").read_text()
        functions = "\n".join(block(source, declaration) for declaration in [
            "void markDoorPacketWriting()", "bool transmitSec1(byte toSend)\n{",
            "bool process_PacketAction(PacketAction &pkt_ac)\n{", "bool process_send_queue()"])
        timeout_setup = next(line.strip() for line in source.splitlines()
                             if "Sec1Serial.setTimeout(" in line)
        harness = r'''
#include <cassert>
#include <cstdint>
#include <algorithm>
#include <deque>
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGV(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
''' + (ROOT / "src/door_command_lifecycle.h").read_text().replace("#pragma once", "") + r'''
using byte=uint8_t;
struct FunctionDelayLock{FunctionDelayLock(){}~FunctionDelayLock(){}};
constexpr int UART_RX_PIN=1,STATUS_DOOR_PIN=2,WP_DISCONNECTED=1,WP_CONNECTED=0,FLASH_ACTIVITY_MS=10;
constexpr int DOOR_CONTROL_SEC_PLUS_V2=2;
constexpr int DOOR_CONTROL_SEC_PLUS_V1=1,MAX_COMMS_RETRY=2,SECPLUS1_TX_WINDOW_CLOSE=20;
int doorControlType=1;
namespace secplus1Codes {enum {QueryDoorStatus=0x38,QueryObstructionStatus=0x39,QueryLightLockStatus=0x3a,QueryUnknownStatus_0x53=0x53};}
struct {bool wallPanelEmulated=false;}garage_door;
struct {void flash(int){}}led;
bool wpDisconnectOnTx=false,clearToSend=true,comms_status_done=true,comms_setup_done=true,collision=false;
uint32_t now=1000,last_tx=0,comms_status_start=0;
uint32_t _millis(){return now;}
int digitalRead(int){return collision;}
bool isRxPending(){return false;}
void write_status_pin(int,int){}
void delay(unsigned ms){now+=ms;}
struct SerialPort {
    unsigned timeout=1000,writes=0;int echo=-1;
    bool available(){return false;}
    void setTimeout(unsigned ms){timeout=ms;}
    void write(byte){++writes;}
    int readBytes(byte *out,int){if(echo<0){now+=timeout;return 0;}*out=echo;return 1;}
    void flush(){}
}Sec1Serial;
struct PacketAction {struct {struct {struct {byte cmd=0x30;}value;}m_data;}pkt;uint32_t doorGeneration=0,delay=0;bool doorPress=false;};
DoorCommandLifecycle doorLifecycle;
PacketAction *writingDoorPacket=nullptr;
std::deque<PacketAction> queue;
bool wallPanelDetected=false;
uint32_t tx_minimum_delay=0,msg_start=0;
unsigned txQueueCount(){return queue.size();}
bool txQueuePeek(PacketAction *out){*out=queue.front();return true;}
bool txQueuePop(PacketAction *out){*out=queue.front();queue.pop_front();return true;}
bool transmitSec2(PacketAction&){return false;}
''' + functions + r'''
int main(){
    ''' + timeout_setup + r'''
    PacketAction press;press.doorGeneration=doorLifecycle.begin(0,now);press.doorPress=true;
    PacketAction release=press;release.doorPress=false;release.pkt.m_data.value.cmd=0x31;
    collision=true;assert(!process_PacketAction(press));assert(Sec1Serial.writes==0);
    assert(doorLifecycle.allow(press.doorGeneration,true));
    doorLifecycle.request(DoorCommandLifecycle::Intent::Open,now);
    collision=false;assert(process_PacketAction(press));assert(process_PacketAction(release));
    assert(Sec1Serial.writes==0);
    press.doorGeneration=doorLifecycle.begin(0,now);release.doorGeneration=press.doorGeneration;
    // Missing echo is bounded and counts as an attempted physical Press.
    const auto before=now;assert(process_PacketAction(press));assert(now-before==50);
    assert(Sec1Serial.writes==1&&!doorLifecycle.allow(press.doorGeneration,true));
    doorLifecycle.request(DoorCommandLifecycle::Intent::Open,now);
    doorLifecycle.expire(now+3000);
    assert(process_PacketAction(release));assert(Sec1Serial.writes==2);
    // A mismatched echo must not cause another physical Press on retry.
    press.doorGeneration=doorLifecycle.begin(0,now);release.doorGeneration=press.doorGeneration;
    Sec1Serial.echo=0x99;assert(!process_PacketAction(press));assert(Sec1Serial.writes==3);
    assert(process_PacketAction(press));assert(Sec1Serial.writes==3);
    Sec1Serial.echo=0x31;assert(process_PacketAction(release));assert(Sec1Serial.writes==4);
    // Repeated bus collisions cannot drop a mandatory Release at retry limit.
    press.doorGeneration=doorLifecycle.begin(0,now);release.doorGeneration=press.doorGeneration;
    Sec1Serial.echo=0x30;assert(process_PacketAction(press));assert(Sec1Serial.writes==5);
    doorLifecycle.expire(now+3000);queue.push_back(release);collision=true;
    for(unsigned i=0;i<10;++i){now+=100;process_send_queue();}
    assert(queue.size()==1&&Sec1Serial.writes==5);
    collision=false;Sec1Serial.echo=0x31;now+=100;process_send_queue();
    assert(queue.empty()&&Sec1Serial.writes==6);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "wire.cpp", Path(directory) / "wire"
            cpp.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
