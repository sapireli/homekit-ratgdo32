"""Production feedback publication must not rewrite command-owned state."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_homekit_notifications import function
from test_homekit_lock_target import HARNESS


class HomekitFeedbackPublicationTest(unittest.TestCase):
    def test_feedback_publishers_are_pure_and_keep_consumer_channels(self):
        source=Path(os.environ.get('HOMEKIT_TEST_SOURCE','src/homekit.cpp')).read_text()
        pieces=[]
        for suffix in ['current_lock','light']:
            publisher='void publish_homekit_'+suffix+'('
            legacy='void notify_homekit_'+suffix+'('
            if publisher in source:
                pieces.append(function(source,publisher))
            else:
                pieces.append(function(source,legacy).replace(legacy,publisher,1))
            pieces.append(function(source,legacy))
        harness=HARNESS.replace('struct {LockTargetState target_lock=TGT_UNLOCKED;}garage_door;',
            'enum LockCurrentState : uint8_t {CURR_UNLOCKED=0,CURR_LOCKED=1};\n'
            'struct {LockTargetState target_lock=TGT_UNLOCKED; LockCurrentState current_lock=CURR_UNLOCKED;bool light=false;}garage_door;')
        harness=harness.replace('void queueSendHelper(QueueHandle_t,GDOEvent,const char *){++queued;}',
            'void queueSendHelper(QueueHandle_t q,GDOEvent e,const char *){++queued;if(q)q->push_back(e);}')
        harness+='''
int current_lock_state=0,light_state=0;
#define HOMEKIT_BOOL_CPP(value) unsigned(value)
enum class Light_t {GDO_LIGHT,ASSIST_LASER};
struct DEV_Light {Value *on;Light_t type=Light_t::GDO_LIGHT;void loop();};
'''
        cases=r'''
int main(){
    garage_door.current_lock=CURR_UNLOCKED;garage_door.light=false;
    Value current,lightValue;
    std::deque<GDOEvent> events;
    service.event_q=&events;service.lockCurrent=&current;
    publish_homekit_current_lock(CURR_LOCKED);
    assert(garage_door.current_lock==CURR_UNLOCKED); // no write-back outside command ownership
    publish_homekit_light(true);
    assert(!garage_door.light);
#ifdef ESP32
    assert(events.empty()); // unpaired current notifications retain their existing admission rule
    isPaired=true;
    publish_homekit_current_lock(CURR_LOCKED);
    publish_homekit_current_lock(CURR_UNLOCKED);
    assert(events.size()==2&&events[0].c==&current&&events[0].value.u==CURR_LOCKED);
    service.loop();assert(current.value==CURR_LOCKED);
    service.loop();assert(current.value==CURR_UNLOCKED);
    DEV_Light light{&lightValue};
    light.loop();assert(lightValue.value==1); // parameter, not the unchanged garage field
    publish_homekit_light(true);publish_homekit_light(false);
    light.loop();assert(lightValue.value==0&&lightValue.writes==2); // existing latest channel
    publish_homekit_current_lock(LockCurrentState(0xff));assert(events.empty());
    service.lockCurrent=nullptr;publish_homekit_current_lock(CURR_LOCKED);assert(events.empty());
    service.lockCurrent=&current;
    notify_homekit_current_lock(CURR_LOCKED);
    assert(garage_door.current_lock==CURR_LOCKED&&events.size()==1);
    notify_homekit_light(true);assert(garage_door.light);
#else
    assert(notifications==2&&lastNotification==1);
    publish_homekit_current_lock(LockCurrentState(0xff));assert(notifications==2);
    running=false;publish_homekit_current_lock(CURR_LOCKED);publish_homekit_light(false);
    assert(notifications==2);
    running=true;notify_homekit_current_lock(CURR_LOCKED);notify_homekit_light(true);
    assert(garage_door.current_lock==CURR_LOCKED&&garage_door.light&&notifications==4);
#endif
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp,binary=Path(directory)/'feedback.cpp',Path(directory)/'feedback'
            for platform in ['ESP32','ESP8266']:
                body=harness+'\n#define '+platform+'\n'+'\n'.join(pieces)
                if platform=='ESP32':
                    body+='\n'+function(source,'void DEV_GarageDoor::loop()')
                    body+='\n'+function(source,'void DEV_Light::loop()')
                cpp.write_text(body+cases)
                subprocess.run([shutil.which('c++'),'-std=c++17','-fsanitize=address,undefined',
                                '-I',str(Path('src').resolve()),str(cpp),'-o',str(binary)],
                               check=True,capture_output=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
