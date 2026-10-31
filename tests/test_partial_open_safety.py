"""Exercise the production partial-opening controller without a physical opener."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_ttc_cancel import block


class PartialOpenSafety(unittest.TestCase):
    def test_only_stop_an_accepted_open_that_is_still_opening(self):
        source = (Path(__file__).resolve().parents[1] / "src/comms.cpp").read_text()
        functions = "\n".join(block(source, declaration) for declaration in [
            "void cancelPartialOpen()", "GarageDoorCurrentState open_door_partial(",
            "void processPartialOpen()\n{"])
        harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#ifdef ESP8266
using _millis_t=uint32_t;
#else
using _millis_t=int64_t;
#endif
#define ESP_LOGI(...) ((void)0)
struct FunctionDelayLock {};
enum GarageDoorCurrentState { CURR_OPEN, CURR_CLOSED, CURR_OPENING, CURR_CLOSING, CURR_STOPPED };
enum DoorAction { Stop };
struct Door { GarageDoorCurrentState current_state=CURR_CLOSED; int openDuration=10,closeDuration=10; } garage_door;
struct History { int duration[1]={10000}; int count=1; } openHistory;
constexpr int GDO_MAX_HISTORY=1;
int median(int *duration,int){return duration[0];}
bool doingPartial=false,partialAwaitingMotion=false,comms_setup_done=true,acceptOpen=false;
_millis_t partialDuration=0,partialStartDeadline=0,partialStopDeadline=0,now=1000;
_millis_t _millis(){return now;}
unsigned stops=0;
bool startDoorOpenCommand(){return acceptOpen;}
bool door_command(DoorAction){++stops;return true;}
GarageDoorCurrentState stop_door(){door_command(Stop);return garage_door.current_state;}
GarageDoorCurrentState open_door(){return garage_door.current_state;}
''' + functions + r'''
int main(){
    // A failed admission must never arm a later raw button press.
    open_door_partial(10);assert(!doingPartial);
    now+=5000;processPartialOpen();assert(stops==0);
    acceptOpen=true;open_door_partial(10);assert(doingPartial);
    // Time spent queued does not consume the opening interval.
    now+=2000;processPartialOpen();assert(stops==0&&partialAwaitingMotion);
    garage_door.current_state=CURR_OPENING;processPartialOpen();
    now+=999;processPartialOpen();assert(stops==0);
    now+=1;processPartialOpen();assert(stops==1&&!doingPartial);
    processPartialOpen();assert(stops==1);
    garage_door.current_state=CURR_CLOSED;open_door_partial(10);
    now+=3000;processPartialOpen();assert(!doingPartial&&stops==1);
    // A physical stop, reversal, or end stop supersedes the timed stop.
    for(auto state:{CURR_STOPPED,CURR_CLOSING,CURR_OPEN}){
        garage_door.current_state=CURR_CLOSED;open_door_partial(10);
        garage_door.current_state=CURR_OPENING;processPartialOpen();
        garage_door.current_state=state;now+=1500;processPartialOpen();
        assert(!doingPartial&&stops==1);
    }
    garage_door.current_state=CURR_CLOSED;open_door_partial(10);
    comms_setup_done=false;processPartialOpen();assert(!doingPartial&&stops==1);
    comms_setup_done=true;
    // Both the start timeout and motion interval survive the ESP8266 wrap.
    now=UINT32_MAX-500;open_door_partial(10);
    now+=700;processPartialOpen();assert(doingPartial);
    garage_door.current_state=CURR_OPENING;processPartialOpen();
    now+=1000;processPartialOpen();assert(stops==2&&!doingPartial);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp, exe = Path(directory) / "partial.cpp", Path(directory) / "partial"
            cpp.write_text(harness)
            for define in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-fsanitize=address,undefined",
                                "-D" + define, str(cpp), "-o", str(exe)], check=True)
                subprocess.run([str(exe)], check=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
