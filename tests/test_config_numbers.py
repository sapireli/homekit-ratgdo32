"""Reject invalid settings before persistence or hardware side effects."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, declaration):
    start = source.index(declaration)
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1]
    raise AssertionError(declaration)


class ConfigNumbers(unittest.TestCase):
    def test_actual_setter_and_helpers(self):
        source = (ROOT / 'src/config.cpp').read_text()
        names = ['static bool parseConfigInt(',
                 'bool userSettings::set(const std::string &key, const char *value)',
                 'bool helperWiFiPower(', 'bool helperWiFiPhyMode(',
                 'bool helperGDOSecurityType(', 'bool helperMotionTriggers(',
                 'bool helperBuiltInTTC(', 'bool helperVehicleThreshold(']
        # Helpers also have forward declarations; select their definitions.
        definitions = source[source.index('bool setDeviceName(const std::string &key, const char *name, configSetting *action)\n{'):]
        actual = '\n'.join(function(source if n.startswith(('static', 'bool userSettings')) else definitions, n) for n in names)
        fixture = r'''
#include <cassert>
#include <cerrno>
#include <climits>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>
#include <map>
#include <variant>
#define ESP32
#define RATGDO32_DISCO
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
bool held=false;
#define TAKE_MUTEX() do {assert(!held);held=true;}while(0)
#define GIVE_MUTEX() do {assert(held);held=false;}while(0)
size_t strlcpy(char*d,const char*s,size_t n){size_t z=strlen(s);if(n){size_t c=z<n-1?z:n-1;memcpy(d,s,c);d[c]=0;}return z;}
struct configStr {size_t max;char*str;};
struct configSetting {std::variant<int,bool,configStr> value;bool reboot=false;};
struct NV {unsigned writes=0;void write(const std::string&,int){++writes;}void write(const std::string&,const char*){++writes;}} nv, *nvRam=&nv;
struct userSettings {
    bool dirty=false;std::map<std::string,configSetting> settings;
    configSetting*getDetail(const std::string&k){auto i=settings.find(k);return i==settings.end()?nullptr:&i->second;}
    bool set(const std::string&,const char*);
    bool set(const std::string&k,int v){settings.at(k).value=v;++nv.writes;return true;}
    int getBuiltInTTC(){return std::get<int>(settings.at("ttc").value);}
} config,*userConfig=&config;
unsigned resets=0,motionChanges=0,commands=0;
void reset_door(){++resets;}
void enable_service_homekit_motion(bool){++motionChanges;}
void send_cancel_ttc(){++commands;}
void send_set_ttc(int){++commands;}
const char*cfg_motionTriggers="motion";
struct {uint8_t asInt=0;} motionTriggers;
struct {int builtInTTC=0;}garage_door;
uint32_t vehicleThresholdDistance=100;
''' + actual + r'''
int main(){
    config.settings={{"power",{20}},{"phy",{0}},{"security",{1}},
                     {"motion",{0}},{"ttc",{0}},{"distance",{10}},{"flag",{false}}};
    auto *action=config.getDetail("power");
    const char *bad[]={nullptr,""," ","oops","12oops","1.5","2147483648","-2147483649","999999999999999999999999999999"};
    for(const char*v:bad){
        unsigned writes=nv.writes;
        assert(!helperWiFiPower("power",v,action));
        assert(!helperWiFiPhyMode("phy",v,config.getDetail("phy")));
        assert(!helperGDOSecurityType("security",v,config.getDetail("security")));
        assert(!helperMotionTriggers("motion",v,config.getDetail("motion")));
        assert(!helperBuiltInTTC("ttc",v,config.getDetail("ttc")));
        assert(!helperVehicleThreshold("distance",v,config.getDetail("distance")));
        assert(!config.set("power",v));assert(!config.set("flag",v));
        assert(nv.writes==writes&&!held&&resets==0&&commands==0&&motionChanges==0);
        assert(std::get<int>(action->value)==20&&!action->reboot&&vehicleThresholdDistance==100);
    }
    assert(!helperMotionTriggers("motion","256",config.getDetail("motion")));
    assert(!helperMotionTriggers("motion","-1",config.getDetail("motion")));
    assert(!helperVehicleThreshold("distance","-1",config.getDetail("distance")));
    assert(!helperVehicleThreshold("distance","429496730",config.getDetail("distance")));
    assert(helperWiFiPower("power","19",action)&&action->reboot);
    assert(helperWiFiPower("power","19",action)&&!action->reboot);
    assert(helperMotionTriggers("motion","31",config.getDetail("motion"))&&motionTriggers.asInt==31);
    assert(helperVehicleThreshold("distance","123",config.getDetail("distance"))&&vehicleThresholdDistance==1230);
    assert(config.set("flag","true")&&std::get<bool>(config.settings.at("flag").value));
    assert(config.set("flag","false")&&!std::get<bool>(config.settings.at("flag").value));
    assert(config.set("power","2147483647")&&std::get<int>(action->value)==INT_MAX);
    assert(config.set("power","-2147483648")&&std::get<int>(action->value)==INT_MIN);
    assert(config.set("power"," 12\t")&&std::get<int>(action->value)==12);
    assert(!held);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'config.cpp'
            binary = Path(directory) / 'config'
            cpp.write_text(fixture)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-parameter', '-fsanitize=address,undefined',
                            str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
