"""Execute production lock publication/owner consumption without actuator I/O."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from test_homekit_notifications import function


HARNESS = r'''
#include "homekit_notifications.h"
#include <cassert>
#include <deque>
#include <cstdint>
#define ESP_LOGD(...) ((void)0)
enum LockTargetState : uint8_t { TGT_UNLOCKED=0,TGT_LOCKED=1 };
struct {LockTargetState target_lock=TGT_UNLOCKED;}garage_door;
struct Value {
    unsigned value=0,writes=0;
    template<class T> void setVal(T next){value=unsigned(next);++writes;}
};
struct GDOEvent {Value *c=nullptr;union {bool b;uint8_t u;}value;};
using QueueHandle_t = std::deque<GDOEvent> *;
unsigned uxQueueMessagesWaiting(QueueHandle_t queue){assert(queue);return queue->size();}
void xQueueReceive(QueueHandle_t queue,GDOEvent *event,int){*event=queue->front();queue->pop_front();}
struct DEV_GarageDoor {
    QueueHandle_t event_q=nullptr;
    Value *current=nullptr,*target=nullptr,*obstruction=nullptr,*lockCurrent=nullptr,*lockTarget=nullptr;
    void loop();
};
DEV_GarageDoor service;
DEV_GarageDoor *door=&service;
static bool isPaired=false;
unsigned queued=0;
void queueSendHelper(QueueHandle_t,GDOEvent,const char *){++queued;}
void runtime_diagnostics_homekit_progress(){}
static HomekitBooleanMailbox stateMailboxes[static_cast<unsigned>(HomekitSignal::Count)];
static HomekitBooleanMailbox &mailbox(HomekitSignal signal){return stateMailboxes[static_cast<unsigned>(signal)];}
bool running=true;
bool arduino_homekit_get_running_server(){return running;}
int target_lock_state=0;
unsigned notifications=0,lastNotification=0;
void homekit_characteristic_notify(int *,unsigned value){++notifications;lastNotification=value;}
#define HOMEKIT_UINT8_CPP(value) unsigned(value)
'''


class HomekitLockTargetTest(unittest.TestCase):
    def test_target_publication_is_pure_latest_and_null_safe(self):
        source = Path(os.environ.get('HOMEKIT_TEST_SOURCE', 'src/homekit.cpp')).read_text()
        if 'void publish_homekit_target_lock(' in source:
            publisher = function(source, 'void publish_homekit_target_lock(')
        else:
            # Baseline had only the state-mutating notification API. Exercise
            # that production body as the old publication boundary: the purity
            # assertion fails before any queue or network activity can occur.
            publisher = function(source, 'void notify_homekit_target_lock(').replace(
                'void notify_homekit_target_lock(', 'void publish_homekit_target_lock(',1)
        wrapper = function(source, 'void notify_homekit_target_lock(')
        consumer = function(source, 'void DEV_GarageDoor::loop()')
        cases = r'''
int main(){
    garage_door.target_lock=TGT_UNLOCKED;
    publish_homekit_target_lock(TGT_LOCKED);
    assert(garage_door.target_lock==TGT_UNLOCKED); // publication must not undo command ownership
#ifdef ESP32
    Value target;
    service.lockTarget=&target;
    service.loop();assert(target.value==TGT_LOCKED&&target.writes==1);
    publish_homekit_target_lock(TGT_UNLOCKED);
    publish_homekit_target_lock(TGT_LOCKED);
    publish_homekit_target_lock(TGT_UNLOCKED);
    service.loop();assert(target.value==TGT_UNLOCKED&&target.writes==2);
    publish_homekit_target_lock(LockTargetState(0xff));
    service.loop();assert(target.writes==2); // invalid state never enters mailbox
    service.lockTarget=nullptr;
    publish_homekit_target_lock(TGT_LOCKED);service.loop(); // dry-contact service has no lock target
    service.lockTarget=&target;service.loop();assert(target.writes==2);
    notify_homekit_target_lock(TGT_LOCKED);
    assert(garage_door.target_lock==TGT_LOCKED);
    service.loop();assert(target.value==TGT_LOCKED&&target.writes==3);
    assert(queued==0); // lock targets must not remain behind stale FIFO events
#else
    assert(notifications==1&&lastNotification==TGT_LOCKED);
    publish_homekit_target_lock(LockTargetState(0xff));assert(notifications==1);
    running=false;publish_homekit_target_lock(TGT_UNLOCKED);assert(notifications==1);
    running=true;notify_homekit_target_lock(TGT_LOCKED);
    assert(garage_door.target_lock==TGT_LOCKED&&notifications==2);
#endif
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp,binary=Path(directory)/'lock-target.cpp',Path(directory)/'lock-target'
            for platform in ['ESP32','ESP8266']:
                # Host mutex adapter exercises producer/consumer logic. The
                # separate adapter test covers the ESP32 preprocessor branch.
                body = HARNESS + '\n#define '+platform+'\n'+publisher+'\n'+wrapper
                if platform=='ESP32': body += '\n'+consumer
                cpp.write_text(body+cases)
                subprocess.run([shutil.which('c++'),'-std=c++17','-fsanitize=address,undefined',
                                '-I',str(Path('src').resolve()),str(cpp),'-o',str(binary)],
                               check=True,capture_output=True)
                result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
