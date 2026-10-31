"""Run the displayed built-in TTC functions and packet handlers without an opener."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ttc_cancel import block

ROOT = Path(__file__).resolve().parents[1]


class BuiltInTTCCountdown(unittest.TestCase):
    def test_elapsed_hold_cancel_and_wrap(self):
        source = (ROOT / "src/comms.cpp").read_text()
        lock = block(source, "class FunctionDelayLock") + ";"
        functions = "\n".join(block(source, declaration) for declaration in [
            "void cancel_builtin_TTC_countdown()", "void process_builtin_TTC_countdown()"])
        handlers = "\n".join(block(source, declaration) for declaration in [
            "case PacketCommand::UpdateTtc:", "case PacketCommand::CancelTtc:"])
        harness = r'''
#include <cassert>
#include <cstdint>
#include <mutex>
#ifdef ESP8266
using _millis_t=uint32_t;
#else
using _millis_t=int64_t;
#endif
#define ESP_LOGI(...) ((void)0)
#define ESP8266_SAVE_CONFIG() (++saves)
std::recursive_mutex mutex;
unsigned depth=0;
using SemaphoreHandle_t=std::recursive_mutex*;
constexpr int portMAX_DELAY=0;
SemaphoreHandle_t functionDelayMutex(){return &mutex;}
void xSemaphoreTakeRecursive(SemaphoreHandle_t p,int){p->lock();++depth;}
void xSemaphoreGiveRecursive(SemaphoreHandle_t p){--depth;p->unlock();}
enum GarageDoorCurrentState {CURR_OPEN,CURR_CLOSED,CURR_OPENING,CURR_CLOSING,CURR_STOPPED};
enum class PacketCommand {UpdateTtc,CancelTtc};
enum class CancelTtcState {Cancel,Hold};
struct {struct {struct {struct {uint16_t seconds=0;}update_ttc;struct {CancelTtcState state=CancelTtcState::Hold;}cancel_ttc;}value;}m_data;}pkt;
struct {GarageDoorCurrentState current_state=CURR_OPEN;uint32_t builtInTTC=60,builtInTTCremaining=0;bool builtInTTChold=false;}garage_door;
struct Config {uint32_t configured=60;uint32_t getBuiltInTTC(){return configured;}void set(int,uint32_t value){configured=value;}}config,*userConfig=&config;
constexpr int cfg_builtInTTC=0;
unsigned saves=0;
bool comms_setup_done=true,builtInTTCcountdownActive=false;
_millis_t now=1000,builtInTTClastTick=0;
_millis_t _millis(){return now;}
''' + lock + functions + r'''
void handle(PacketCommand command){switch(command){
''' + handlers + r'''
}}
void update(uint16_t seconds){pkt.m_data.value.update_ttc.seconds=seconds;handle(PacketCommand::UpdateTtc);}
void hold(){pkt.m_data.value.cancel_ttc.state=CancelTtcState::Hold;handle(PacketCommand::CancelTtc);}
int main(){
    update(10);assert(builtInTTCcountdownActive&&garage_door.builtInTTCremaining==10);
    now+=999;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==10);
    now+=2501;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==7);
    now+=500;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==6);
    // An authoritative update rebases even when an earlier count was active.
    now+=10000;update(8);process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==8);
    // Settle unheld time before Hold, then discard held elapsed time on release.
    now+=2500;hold();assert(garage_door.builtInTTChold&&garage_door.builtInTTCremaining==6);
    now+=9000;hold();assert(!garage_door.builtInTTChold&&garage_door.builtInTTCremaining==6);
    process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==6);
    now+=999;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==6);
    now+=1;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==5);
    hold();now+=5500;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==5);
    now+=4500;hold();assert(garage_door.builtInTTCremaining==5);
    now+=1000;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==4);
    hold();now+=12000;update(7);process_builtin_TTC_countdown();
    assert(!garage_door.builtInTTChold&&garage_door.builtInTTCremaining==7);
    hold();cancel_builtin_TTC_countdown();
    assert(!builtInTTCcountdownActive&&!garage_door.builtInTTChold&&!garage_door.builtInTTCremaining&&!builtInTTClastTick);
    now+=100000;process_builtin_TTC_countdown();assert(!garage_door.builtInTTCremaining);
    update(3);now+=100000;process_builtin_TTC_countdown();
    assert(!builtInTTCcountdownActive&&garage_door.builtInTTCremaining==0);
    process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==0);
    now=UINT32_MAX-1499;update(5);now+=2500;process_builtin_TTC_countdown();
    assert(garage_door.builtInTTCremaining==3);
    now+=500;process_builtin_TTC_countdown();assert(garage_door.builtInTTCremaining==2);
    now=UINT32_MAX-100;update(4);hold();now+=3000;process_builtin_TTC_countdown();
    hold();assert(garage_door.builtInTTCremaining==4);now+=1000;process_builtin_TTC_countdown();
    assert(garage_door.builtInTTCremaining==3);
    update(0);assert(!builtInTTCcountdownActive&&!garage_door.builtInTTCremaining);
    update(4);garage_door.current_state=CURR_CLOSED;update(5);
    assert(!builtInTTCcountdownActive&&!garage_door.builtInTTCremaining);
    garage_door.current_state=CURR_OPEN;update(7);
    pkt.m_data.value.cancel_ttc.state=CancelTtcState::Cancel;handle(PacketCommand::CancelTtc);
    assert(!builtInTTCcountdownActive&&garage_door.builtInTTC==0&&config.configured==0);
    // A packet already being dispatched cannot revive the display after teardown.
    comms_setup_done=false;update(120);hold();assert(!builtInTTCcountdownActive&&!garage_door.builtInTTCremaining&&config.configured==0);
    assert(depth==0);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "builtin.cpp", Path(directory) / "builtin"
            cpp.write_text(harness)
            for define in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined", "-pthread",
                                "-D" + define, str(cpp), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
