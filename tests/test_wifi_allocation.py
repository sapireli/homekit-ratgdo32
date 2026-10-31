"""Low-memory Wi-Fi pages must fail before headers or configuration writes."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = source.index(name + '\n{')
    opening = source.index('{', start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if not depth:
            return source[start:end + 1]
    raise AssertionError(name)


class WiFiAllocation(unittest.TestCase):
    def test_actual_handlers_allocation_failures(self):
        source = (ROOT / 'src/softAP.cpp').read_text()
        functions = '\n'.join(function(source, n) for n in
                              ['void handle_wifinets()', 'void handle_setssid()'])
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <string>
#include <list>
#include <map>
class String:public std::string {public:using std::string::string;String(const std::string&s):std::string(s){}bool equals(const char*s)const{return *this==s;}};
struct WifiScanResults {bool acquire(){return true;}};
struct wifiNet_t {String ssid="home";int rssi=-40,channel=1;uint8_t bssid[6]{};};
std::list<wifiNet_t>wifiNets{{}};
struct WiFiClass{bool isConnected(){return true;}String SSID(){return "home";}}WiFi;
unsigned configChanges=0,restarts=0,chunks=0;int status=0;
struct Client{void setNoDelay(bool){}};
struct Server{
    std::map<std::string,String> args_{{"net","0"},{"userSSID","new"},{"advanced","off"},{"pw","secret"}};
    unsigned args(){return 4;}String arg(const char*k){return args_[k];}String uri(){return "/wifinets";}
    Client client(){return {};}
    void sendContent(const char*,size_t){++chunks;}
    void send_P(int code,const char*,const char*){status=code;}
}server;
void delay(unsigned){}
void set_new_ssid(const char*,const char*,const uint8_t*){++configChanges;}
void sync_and_restart(){++restarts;}
void htmlEscape(const char*s,char*d,size_t n){snprintf(d,n,"%s",s);}
#define ESP_LOGI(...) ((void)0)
#define PSTR(s) s
#define snprintf_P snprintf
#define TXT_BUFFER_SIZE 1024
const char *softAPhttpPreamble="header",*softAPtableHead="table",*softAPtableRow="row",*softAPtableLastRow="last",*type_txt="text/plain",*response400invalid="bad";
unsigned allocations=0,failAt=0,live=0;
void *allocate(size_t n){if(++allocations==failAt)return nullptr;void*p=std::malloc(n);assert(p);++live;return p;}
void release(void*p){if(p){--live;std::free(p);}}
#define malloc allocate
#define free release
''' + functions + r'''
int main(){
    for(unsigned fail=1;fail<=2;++fail){
        failAt=fail;allocations=chunks=0;status=0;
        handle_wifinets();
        assert(status==503&&chunks==0&&live==0&&configChanges==0&&restarts==0);
    }
    failAt=1;allocations=0;status=0;
    handle_setssid();assert(status==503&&live==0&&configChanges==0&&restarts==0);
    failAt=0;allocations=chunks=0;status=0;
    handle_wifinets();assert(chunks>=4&&live==0);
    handle_setssid();assert(status==200&&live==0&&configChanges==1&&restarts==1);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'wifi.cpp'
            binary = Path(directory) / 'wifi'
            cpp.write_text(fixture)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-Wno-format-extra-args', '-fsanitize=address,undefined',
                            str(cpp), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
