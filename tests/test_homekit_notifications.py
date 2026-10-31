"""Run production optional-service methods with inert HomeSpan/actuator boundaries.

The native HomeSpan substitute models the pause/traversal mutex and deletion;
it does not establish ESP32 timing, heap savings, or SDK network behavior.
"""
from pathlib import Path
import os
import shutil
import shlex
import subprocess
import tempfile
import unittest


def function(source, signature):
    start = source.index(signature)
    begin = source.index('{', start)
    depth = 1
    end = begin + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


HARNESS = r'''
#include "homekit_notifications.h"
#include <cassert>
#include <atomic>
#include <functional>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <deque>
#include <string>
#include <cstring>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define RATGDO32_DISCO
#define LASER_PIN 1
#define HOMEKIT_AID_LASER 8
using TaskHandle_t = const void *;
TaskHandle_t xTaskGetCurrentTaskHandle() { static thread_local int task; return &task; }
using boolean = bool;
std::atomic<unsigned> allocations{0};
struct GDOEvent { void *c; union { bool b; unsigned u; } value; };
struct Queue { std::deque<GDOEvent> values; };
using QueueHandle_t = Queue *;
QueueHandle_t xQueueCreate(int, unsigned) { ++allocations; return new Queue; }
int uxQueueMessagesWaiting(QueueHandle_t q) { assert(q); return q->values.size(); }
void xQueueReceive(QueueHandle_t q, GDOEvent *e, int) { *e=q->values.front(); q->values.pop_front(); }
void queueSendHelper(QueueHandle_t q, GDOEvent e, const char *) { if(q) q->values.push_back(e); }
namespace Service { struct LightBulb {}; }
namespace Characteristic {
struct On {
    static constexpr bool OFF=false;
    bool value;
    explicit On(bool value):value(value){}
    void setVal(bool next) { value=next; }
    template<class T> T getNewVal() { return value; }
};
}
enum class Light_t { GDO_LIGHT, ASSIST_LASER };
struct DEV_Light : Service::LightBulb {
    Characteristic::On *on;
    QueueHandle_t event_q=nullptr; // Legacy methods compile in baseline regression.
    Light_t type;
    explicit DEV_Light(Light_t type=Light_t::GDO_LIGHT);
    ~DEV_Light() { delete on; }
    void loop();
    boolean update();
};
DEV_Light *assistLaser=nullptr;
struct SpanAccessory { explicit SpanAccessory(int){} };
struct DEV_Info { explicit DEV_Info(const char *){} };
// Model framework construction objects without persistent allocations. The
// service itself is allocated/deleted by the production helper below.
struct Config {
    bool getLaserEnabled(){return true;}
    bool getLaserHomeKit(){return true;}
} config;
Config *userConfig=&config;
unsigned actuations=0;
void set_light(bool){++actuations;}
struct Laser {
    void onChange(void(*)(bool)){}
    void on(){++actuations;}
    void off(){++actuations;}
} laser;
struct HomeSpan {
    std::shared_mutex mutex;
    unsigned updates=0;
    std::shared_mutex &getMutex(){return mutex;}
    bool deleteAccessory(int){ delete assistLaser; return true; }
    void updateDatabase(){++updates;}
} homeSpan;
static bool isPaired=true;
bool suspend_service_loop=false;
static HomekitBooleanMailbox stateMailboxes[static_cast<unsigned>(HomekitSignal::Count)];
static HomekitServiceRequests serviceRequests;
static std::atomic<bool> pollingStarted{false};
static std::atomic<TaskHandle_t> mutationOwner{nullptr};
void notify_homekit_laser(bool);
bool enable_service_homekit_laser(bool);
bool enable_service_homekit_light(bool){return false;}
void enable_service_homekit_vehicle(bool){}
bool enable_service_homekit_motion_sensor(bool){return false;}
bool enable_service_homekit_room_occupancy(bool){return false;}
bool enable_service_homekit_stop(bool){return false;}
'''

CASES = r'''
int main(int argc,char **argv) {
    (void)argc;
    std::string mode=argv[1];
    if(mode=="mailbox") {
        HomekitBooleanMailbox latest;
        bool value;
        for(int i=0;i<10000;++i) latest.publish(i&1);
        assert(latest.take(value) && value);
        assert(!latest.take(value));
        HomekitBooleanMailbox pulse;
        pulse.publish(true,true); pulse.publish(false,true);
        assert(pulse.take(value) && value);
        assert(pulse.take(value) && !value);
        assert(!pulse.take(value));
        pulse.publish(true,true); pulse.publish(false,true);
        pulse.beginObservation();
        assert(pulse.take(value) && !value); // disabled history is not a fresh detection
        assert(!pulse.take(value));
        pulse.publish(true,true); pulse.publish(false,true);
        assert(pulse.take(value) && value);
        assert(pulse.take(value) && !value);
        HomekitFloatMailbox reading;
        reading.publish(12.5f); reading.publish(13.25f);
        float sample;
        assert(reading.take(sample) && sample==13.25f && !reading.take(sample));
        return 0;
    }
    if(mode=="disabled") {
        // Producer may run after deletion and before replacement construction.
        notify_homekit_laser(true);
        enable_service_homekit_laser(true);
        assert(assistLaser);
        assistLaser->loop();
        assert(assistLaser->on->value);
        return 0;
    }
    if(mode=="cycles") {
        for(int i=0;i<1000;++i) {
            enable_service_homekit_laser(true);
            assert(assistLaser);
            enable_service_homekit_laser(false);
            assert(!assistLaser);
        }
        assert(allocations.load()==0);
        return 0;
    }
    pollingStarted.store(true);
    if(mode=="deferred") {
        enable_service_homekit_laser(true);
        assert(!assistLaser); // no mutation from command/web callback
        homekit_loop();
        assert(assistLaser);
        notify_homekit_laser(true); notify_homekit_laser(false);
        assistLaser->loop();
        assert(!assistLaser->on->value && actuations==0);
        enable_service_homekit_laser(false);
        assert(assistLaser);
        homekit_loop();
        assert(!assistLaser);
        return 0;
    }
    if(mode=="contended") {
        std::atomic<bool> locked{false}, release{false};
        std::thread poll([&]{
            std::unique_lock<std::shared_mutex> lock(homeSpan.getMutex());
            locked.store(true);
            while(!release.load()) std::this_thread::yield();
        });
        while(!locked.load()) std::this_thread::yield();
        enable_service_homekit_laser(true);
        homekit_loop(); // must return without waiting for the poll task
        assert(!assistLaser);
        release.store(true); poll.join();
        homekit_loop();
        assert(assistLaser);
        suspend_service_loop=true;
        enable_service_homekit_laser(false); homekit_loop();
        assert(assistLaser); // OTA retains its existing pause across callbacks
        suspend_service_loop=false; homekit_loop();
        assert(!assistLaser);
        return 0;
    }
    // Producer has no reference to deletable service or characteristic storage.
    std::atomic<bool> stop{false};
    std::thread producer([&]{while(!stop.load()) {notify_homekit_laser(true);notify_homekit_laser(false);}});
    for(int i=0;i<1000;++i) {
        enable_service_homekit_laser(true); homekit_loop();
        {std::unique_lock<std::shared_mutex> poll(homeSpan.getMutex()); assistLaser->loop();}
        enable_service_homekit_laser(false); homekit_loop();
    }
    stop.store(true); producer.join();
    assert(!assistLaser && allocations.load()==0);
}
'''


class HomekitNotificationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ.get('HOMEKIT_TEST_SOURCE', 'src/homekit.cpp')).read_text()
        signatures = ['DEV_Light::DEV_Light(', 'void DEV_Light::loop()', 'boolean DEV_Light::update()',
                      'void notify_homekit_laser(bool', 'bool enable_service_homekit_laser(bool']
        prefix = ''
        if 'static bool deferServiceChange(' in source:
            prefix = function(source, 'static HomekitBooleanMailbox &mailbox(') + '\n'
            prefix += function(source, 'static bool deferServiceChange(') + '\n'
        bodies = prefix + '\n'.join(function(source, name) for name in signatures)
        # Trivial construction metadata is unrelated to the service queue lifetime.
        bodies = bodies.replace('new SpanAccessory(HOMEKIT_AID_LASER);', '(void)HOMEKIT_AID_LASER;')
        bodies = bodies.replace('new DEV_Info("Laser");', '(void)0;')
        if '// Called from the existing Arduino loop' in source:
            start = source.index('// Called from the existing Arduino loop')
            bodies += '\n' + function(source[start:], 'void homekit_loop()')
        else:
            bodies += '\nvoid homekit_loop() {}'
        cls.directory = tempfile.TemporaryDirectory()
        cpp = Path(cls.directory.name)/'notifications.cpp'
        cls.binary = Path(cls.directory.name)/'notifications'
        cpp.write_text(HARNESS+bodies+CASES)
        compiler = shutil.which('c++')
        subprocess.run([compiler,'-std=c++17','-pthread','-Wall','-Wextra',
                        *shlex.split(os.environ.get('HOMEKIT_TEST_CXXFLAGS', '')),
                        '-Wno-unused-variable','-Wno-unused-function','-I',str(Path('src').resolve()),
                        str(cpp),'-o',str(cls.binary)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def run_case(self, name):
        result = subprocess.run([str(self.binary),name],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_permanent_queue_allocation_is_safe(self):
        source = Path(os.environ.get('HOMEKIT_TEST_SOURCE', 'src/homekit.cpp')).read_text()
        body = function(source, 'void DEV_GarageDoor::loop()')
        harness = r"""
#include <cassert>
#include "homekit_notifications.h"
enum class LockTargetState { TGT_UNLOCKED, TGT_LOCKED };
static HomekitBooleanMailbox lockTargetMailbox;
HomekitBooleanMailbox &mailbox(HomekitSignal){return lockTargetMailbox;}
#define ESP_LOGD(...) ((void)0)
void runtime_diagnostics_homekit_progress(){}
struct Value { template<class T> void setVal(T){} };
struct GDOEvent { Value *c; union { bool b; unsigned u; } value; };
unsigned uxQueueMessagesWaiting(void *queue){assert(queue);return 0;}
void xQueueReceive(void *,GDOEvent *,int){}
struct DEV_GarageDoor {
    void *event_q=nullptr;
    Value *current=nullptr,*target=nullptr,*obstruction=nullptr,*lockCurrent=nullptr,*lockTarget=nullptr;
    void loop();
};
"""
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory)/'null-queue.cpp'
            binary = Path(directory)/'null-queue'
            cpp.write_text(harness+body+'\nint main(){DEV_GarageDoor service; service.loop();}')
            subprocess.run([shutil.which('c++'),'-std=c++17','-I',str(Path('src').resolve()),str(cpp),'-o',str(binary)],
                           check=True,capture_output=True)
            result = subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_room_recreation_starts_from_cleared_logical_state(self):
        source = Path(os.environ.get('HOMEKIT_TEST_SOURCE', 'src/homekit.cpp')).read_text()
        signatures = ['DEV_Occupancy::DEV_Occupancy(', 'void DEV_Occupancy::loop()',
                      'void notify_homekit_room_occupancy(bool',
                      'bool enable_service_homekit_room_occupancy(bool']
        bodies = function(source, 'static HomekitBooleanMailbox &mailbox(') + '\n'
        bodies += '\n'.join(function(source, name) for name in signatures)
        bodies = bodies.replace('new SpanAccessory(HOMEKIT_AID_ROOM_OCCUPANCY);', '(void)0;')
        bodies = bodies.replace('new DEV_Info("Room Occupancy");', '(void)0;')
        harness = r"""
#include "homekit_notifications.h"
#include <cassert>
#include <cstdint>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define HOMEKIT_AID_ROOM_OCCUPANCY 9
namespace Service {struct OccupancySensor {};}
namespace Characteristic {
struct OccupancyDetected {
    static constexpr bool NOT_DETECTED=false;
    bool value;
    explicit OccupancyDetected(bool value):value(value){}
    void setVal(bool next){value=next;}
};
}
struct DEV_Occupancy:Service::OccupancySensor {
    Characteristic::OccupancyDetected *occupied;
    HomekitSignal signal;
    explicit DEV_Occupancy(HomekitSignal signal=HomekitSignal::Vehicle);
    ~DEV_Occupancy(){delete occupied;}
    void loop();
};
DEV_Occupancy *roomOccupancy=nullptr,*vehicle=nullptr;
struct Motion {} motionService;
Motion *motion=&motionService;
struct {bool room_occupied=false;uint32_t room_occupancy_timeout=0;}garage_door;
struct Config {unsigned getOccupancyDuration(){return 300;}}config;
Config *userConfig=&config;
uint32_t _millis(){return 1000;}
struct HomeSpan {
    bool deleteAccessory(int){delete roomOccupancy;return true;}
    void updateDatabase(){}
}homeSpan;
static HomekitBooleanMailbox stateMailboxes[static_cast<unsigned>(HomekitSignal::Count)];
bool deferServiceChange(HomekitService,bool){return false;}
void notify_homekit_room_occupancy(bool);
"""
        main = r"""
int main(){
    assert(enable_service_homekit_room_occupancy(true));
    notify_homekit_room_occupancy(true);roomOccupancy->loop();
    assert(roomOccupancy->occupied->value&&garage_door.room_occupied);
    assert(enable_service_homekit_room_occupancy(false));
    assert(!roomOccupancy&&!garage_door.room_occupied);
    // No further motion or timer publication occurs while the service is absent.
    assert(enable_service_homekit_room_occupancy(true));roomOccupancy->loop();
    assert(!roomOccupancy->occupied->value); // Match the authoritative logical state.
    assert(!garage_door.room_occupied);
    enable_service_homekit_room_occupancy(false);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            cpp, binary = Path(directory)/'room.cpp', Path(directory)/'room'
            cpp.write_text(harness+bodies+main)
            subprocess.run([shutil.which('c++'),'-std=c++17',
                            *shlex.split(os.environ.get('HOMEKIT_TEST_CXXFLAGS', '')),
                            '-I',str(Path('src').resolve()),str(cpp),'-o',str(binary)],
                           check=True,capture_output=True)
            result = subprocess.run([str(binary)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_latest_value_and_detection_pulse(self): self.run_case('mailbox')
    def test_notification_while_service_absent(self): self.run_case('disabled')
    def test_create_delete_releases_queue_resources(self): self.run_case('cycles')
    def test_mutations_defer_to_paused_owner(self): self.run_case('deferred')
    def test_busy_poll_retains_request_without_blocking(self): self.run_case('contended')
    def test_notification_overlaps_deletion(self): self.run_case('overlap')
