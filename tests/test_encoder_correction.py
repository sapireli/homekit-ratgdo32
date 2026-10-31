"""Exercise production encoder correction dispatch and cancellation boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_ttc_cancel import block

ROOT = Path(__file__).resolve().parents[1]


class EncoderCorrectionTest(unittest.TestCase):
    def test_correction_and_latest_command(self):
        encoder = (ROOT / "src/encoder.cpp").read_text()
        comms = (ROOT / "src/comms.cpp").read_text()
        functions = "\n".join(block(encoder, n) for n in [
            "void cancel_encoder_correction()", "static void process_encoder_correction()",
            "void encoder_loop()", "void reset_encoder_cal_locked()"])
        retry = block(encoder, "static void check_encoder_stopped()")
        retry = retry[:retry.index("  // Use the latched travel direction")] + "}\n"
        # Compile the exact scheduling branch selected by wrong-direction input.
        start = encoder.index("        direction_t intended = enc_intended_dir_;")
        schedule = encoder[start:encoder.index("\n      }", start)]
        wrappers = "\n".join(block(comms, n) for n in [
            "void encoder_control_loop()", "void reset_encoder_cal()"])
        # Check actual command entry code, including cancellation before the
        # not-ready/admission returns. The remaining actuator paths have their
        # own door-command lifecycle tests.
        entries = []
        for declaration in ["GarageDoorCurrentState open_door()",
                            "GarageDoorCurrentState stop_door()",
                            "GarageDoorCurrentState close_door(bool bypass_ttc)",
                            "GarageDoorCurrentState toggle_door(bool bypass_ttc)",
                            "GarageDoorCurrentState open_door_partial(int timePercentage)"]:
            actual = block(comms, declaration)
            prefix = actual[:actual.index("    if (!comms_setup_done)")]
            entries.append(prefix + "    return garage_door.current_state;\n}\n")
        shutdown = block(comms, "void shutdown_comms()")
        shutdown = shutdown[:shutdown.index("        // Cancel old work")] + "    }\n}\n"
        harness = r"""
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include <mutex>
#define RATGDO_ENCODER 1
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#ifdef ESP8266
using _millis_t=uint32_t;
#else
using _millis_t=int64_t;
#endif
_millis_t now=100;
_millis_t _millis(){return now;}
std::recursive_mutex commands;
int depth=0;
struct FunctionDelayLock {
    FunctionDelayLock(){commands.lock();++depth;}
    ~FunctionDelayLock(){--depth;commands.unlock();}
};
enum direction_t {DIR_CLOSING=-1,DIR_NONE=0,DIR_OPENING=1};
enum GarageDoorCurrentState {CURR_STOPPED,CURR_OPENING,CURR_CLOSING};
struct {GarageDoorCurrentState current_state=CURR_OPENING;} garage_door;
bool encoder_setup_done=true;
bool enc_dir_correction_pending_=false,enc_correction_stop_pending_=false;
direction_t enc_dir_correction_intended_=DIR_NONE,enc_intended_dir_=DIR_NONE;
_millis_t enc_correction_stop_at_=0,enc_last_pulse_ms_=0;
constexpr uint32_t ENC_STOPPED_WATCHDOG_MS=2000;
bool enc_watchdog_armed_=false;
int16_t enc_delta=0,enc_last_=0,enc_min_=0,enc_max_=0,enc_cycle_count=0;
bool enc_min_cal_=false,enc_max_cal_=false;
direction_t enc_travel_dir_=DIR_NONE;
int enc_reverse_count_=0;
struct EncCalBlob {int16_t min,max,last;bool min_cal,max_cal;};
const char *nvram_enc_cal="enc_cal";
unsigned saves=0,stops=0,opens=0,closes=0;
void write_door_data(const char*,const void*,size_t){assert(depth);++saves;}
void noInterrupts(){}
void interrupts(){}
void on_encoder_update(int16_t){}
void cancel_encoder_correction();
GarageDoorCurrentState stop_door();
GarageDoorCurrentState open_door();
GarageDoorCurrentState close_door(bool);
static void check_encoder_stopped();
void encoder_loop();
void reset_encoder_cal_locked();
""" + functions + retry + wrappers + r"""
void schedule(direction_t desired){
    FunctionDelayLock lock;
    enc_intended_dir_=desired;
""" + schedule + r"""
}
"""
        # Rename the production entry bodies so internal mock actuator calls
        # can count dispatch separately from explicit command acceptance.
        harness += "\n".join(entries).replace(" open_door(", " user_open_door(").replace(
            " stop_door(", " user_stop_door(").replace(" close_door(", " user_close_door(").replace(
            " toggle_door(", " user_toggle_door(").replace(" open_door_partial(", " user_open_door_partial(")
        harness += shutdown + r"""
GarageDoorCurrentState stop_door(){assert(depth);cancel_encoder_correction();++stops;return CURR_STOPPED;}
GarageDoorCurrentState open_door(){assert(depth);cancel_encoder_correction();++opens;return CURR_OPENING;}
GarageDoorCurrentState close_door(bool){assert(depth);cancel_encoder_correction();++closes;return CURR_CLOSING;}
int main(){
    // One delayed Stop, then one retry after a full stopped-motion interval.
    schedule(DIR_OPENING);now+=499;encoder_control_loop();assert(stops==0);
    now+=1;encoder_control_loop();assert(stops==1&&enc_dir_correction_pending_);
    encoder_control_loop();assert(stops==1);
    now+=1999;encoder_control_loop();assert(opens==0);
    now+=1;encoder_control_loop();assert(opens==1&&!enc_dir_correction_pending_);
    now+=5000;encoder_control_loop();assert(stops==1&&opens==1);
    // Every public command cancels the old correction, including no-op paths.
    for(int entry:{0,1,2,3,4}){
        schedule(DIR_CLOSING);
        if(entry==0)user_stop_door();
        if(entry==1)user_open_door();
        if(entry==2)user_close_door(false);
        if(entry==3)user_toggle_door(false);
        if(entry==4)user_open_door_partial(20);
        now+=5000;encoder_control_loop();assert(stops==1&&closes==0);
        assert(!enc_correction_stop_pending_&&!enc_dir_correction_pending_);
    }
    // A replacement after Stop also cancels the later retry.
    schedule(DIR_CLOSING);now+=500;encoder_control_loop();assert(stops==2);
    user_stop_door();now+=3000;encoder_control_loop();assert(closes==0);
    schedule(DIR_OPENING);reset_encoder_cal();now+=3000;encoder_control_loop();
    assert(stops==2&&opens==1&&saves==1);
    schedule(DIR_CLOSING);shutdown_comms();now+=3000;encoder_control_loop();
    assert(stops==2&&closes==0&&!enc_dir_correction_pending_);
    // Normal Close retry and wrapped deadline remain one-shot.
    now=UINT32_MAX-200;schedule(DIR_CLOSING);now+=499;encoder_control_loop();assert(stops==2);
    now+=1;encoder_control_loop();assert(stops==3);
    now+=2000;encoder_control_loop();assert(closes==1&&!enc_dir_correction_pending_);
    // A delayed main-loop poll must not issue Stop and retry in the same tick.
    schedule(DIR_OPENING);now+=3000;encoder_control_loop();assert(stops==4&&opens==1);
    now+=1999;encoder_control_loop();assert(opens==1);
    now+=1;encoder_control_loop();assert(opens==2);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            cpp, binary = Path(directory)/"encoder.cpp", Path(directory)/"encoder"
            cpp.write_text(harness)
            for target in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                "-Wno-unused-variable", "-Wno-unused-parameter", "-D" + target,
                                "-fsanitize=address,undefined", str(cpp), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
