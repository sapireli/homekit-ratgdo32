"""Exercise the actual scan renderer and deferred HTTP pump without sockets."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def block(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if not depth:
            return source[start:end + 1]
    raise AssertionError(declaration)


class WifiScanDeliveryTest(unittest.TestCase):
    def test_large_page_short_writes_and_ap_pump(self):
        web = (ROOT / "src/web.cpp").read_text()
        soft = (ROOT / "src/softAP.cpp").read_text()
        fields = web[web.index("enum class HttpOwnedState"):web.index("struct HttpOwnedCounters")]
        renderer = soft[soft.index("struct WifiScanPageCursor"):soft.index("\n#endif", soft.index("struct WifiScanPageCursor"))]
        handler = block(soft, "void handle_wifinets()\n{")
        legacy = "void legacy_page()\n{\n" + handler[handler.index("    bool connected = WiFi.isConnected();"):]
        entry = handler[:handler.index("    bool connected = WiFi.isConnected();")] + "}\n"
        formats = soft[soft.index("static const char softAPhttpPreamble"):soft.index("static const char softAPsuccess")]
        scan = (block(soft, "static void storeWifiScanResults(") +
                block(soft, "bool wifi_scan(bool retainResults)") + block(soft, "static void pollWifiScan()"))
        result_class = block((ROOT / "src/softAP.h").read_text(), "class WifiScanResults") + ";\n"
        cli = block((ROOT / "src/serialCLI.cpp").read_text(), "uint32_t scanWifi(bool uniqueSSID, WifiScanResults &results)\n{")
        provision = block((ROOT / "src/provision.cpp").read_text(), "void getAvailableWifiNetworks()")
        pending = block(soft, "void soft_ap_loop()\n{")
        pending = pending[:pending.index("    if (!softAPinitialized)")] + "}\n"
        self.assertIn("setup_http_response_delivery();", block(soft, "void start_soft_ap()\n{"))
        self.assertLess(web.index("const bool bodyPending = pollHttpResponses();", web.index("void web_loop()")),
                        web.index("if (!web_setup_done)", web.index("void web_loop()")))
        self.assertIn("#if !defined(ESP32) || !defined(RATGDO_HTTP_LIFECYCLE_EXPERIMENT)\n    server.handleClient();",
                      block(soft, "void soft_ap_loop()\n{"))
        harness = r"""
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <set>
#include <vector>
#include <cstdarg>
#include <string>
#define ESP32 1
#define RATGDO_HTTP_LIFECYCLE_EXPERIMENT 1
#define PROGMEM
#define PSTR(x) x
#define ESP_LOGI(...) ((void)0)
#define TXT_BUFFER_SIZE 1024
class String:public std::string {public:
 using std::string::string;using std::string::operator=;
 String()=default;String(const std::string&s):std::string(s){}String(int n):std::string(std::to_string(n)){}bool equals(const char*s)const{return *this==s;}
};
struct wifiNet_t {String ssid;int32_t rssi=-40,channel=1;uint8_t bssid[6]{};int encryptionType=0;};
struct Compare {bool operator()(const wifiNet_t&a,const wifiNet_t&b)const{return a.ssid<b.ssid||(a.ssid==b.ssid&&a.rssi>b.rssi);}};
std::multiset<wifiNet_t,Compare>wifiNets;
static std::atomic<bool>wifiScanOwned{false},wifiScanPending{false},wifiScanRunning{false},wifiScanFailed{false};
constexpr int WIFI_SCAN_RUNNING=-1,WIFI_AUTH_OPEN=0;
unsigned scans=0,asyncScans=0,scanPolls=0;
int asyncStart=WIFI_SCAN_RUNNING,scanStatus=WIFI_SCAN_RUNNING,syncCount=0;
struct Wifi {
 bool isConnected(){return true;}
 String SSID(){return "registered & <SSID>";}
 String SSID(int){return "new scan";}
 int scanNetworks(bool async=false){if(async){++asyncScans;return asyncStart;}++scans;return syncCount;}
 int scanComplete(){++scanPolls;return scanStatus;}
 int channel(int){return 1;}int RSSI(int){return -40;}
 const uint8_t*BSSID(int){static uint8_t b[6]{};return b;}
 String BSSIDstr(int){return "00:00:00:00:00:00";}
 int encryptionType(int){return 0;}void scanDelete(){}
}WiFi;
const char *encryptionToString(int){return "";}
std::string expected;
int responseStatus=0;
struct Client {void setNoDelay(bool){}};
unsigned configured=0,restarted=0;
void set_new_ssid(const char*,const char*,const uint8_t*){assert(!wifiScanOwned);++configured;}
void sync_and_restart(){++restarted;}
#define snprintf_P snprintf
const char *response400invalid="bad";
struct Server {unsigned handled=0;Client client(){return {};}
 unsigned args(){return 4;}
 String arg(const char*k){return std::strcmp(k,"net")==0?"0":std::strcmp(k,"advanced")==0?"on":"manual";}
 String uri(){return "/setssid";}
 void sendContent(const char*p,size_t n){expected.append(p,n);}
 void send_P(int status,const char*,const char*){responseStatus=status;}
 void handleClient(){++handled;}
}server;
const char *type_txt="text/plain";
bool suppressSerialLog=false;
void readerProgress();
struct SerialMock {void println(){} void printf_P(const char*fmt,...){if(std::strstr(fmt,"%3d:"))readerProgress();}}Serial;
namespace improv {constexpr int ERROR_UNKNOWN=1,GET_WIFI_NETWORKS=2;
 std::vector<uint8_t>build_rpc_response(int,const std::vector<std::string>&data,bool){return {static_cast<uint8_t>(data.empty()?0:1)};}}
unsigned responses=0,finalResponses=0,errors=0;
void send_response(const std::vector<uint8_t>&data){++responses;if(data[0]==0)++finalResponses;}
void set_error(int){++errors;}
void delay(unsigned ms){if(ms==1)readerProgress();}

unsigned now=0;
uint32_t _millis(){return now;}
struct netconn;struct tcp_pcb;struct ip_addr_t{};
struct NetworkClient{int fd()const{return 7;}};
struct LOG {struct MessageCursor{};struct DiagnosticCursor{};
 size_t readMessageLog(MessageCursor&,uint8_t*,size_t,bool&){return 0;}
 size_t readDiagnosticLog(DiagnosticCursor&,uint8_t*,size_t,bool&){return 0;}
}logger,*ratgdoLogger=&logger;
char writeBuffer[512];
bool web_setup_done=false,httpOwnedPending=false;
unsigned retirementCalls=0;
bool drainRetiredSSE(){++retirementCalls;return true;}
bool httpOwnedPoll(){return !httpOwnedPending;}
void *httpOwnedMessage=(void*)1;
constexpr uint32_t HTTP_BODY_MAX_LIFETIME_MS=5000;
constexpr int MSG_DONTWAIT=1;
using ssize_t=long;
size_t sendLimit=17;
int sendError=0;
unsigned sendCalls=0;
std::string delivered;
ssize_t send(int,const void*p,size_t n,int flags){
 assert(flags==MSG_DONTWAIT);++sendCalls;
 if(sendError){errno=sendError;return -1;}
 n=std::min(n,sendLimit);delivered.append((const char*)p,n);return n;
}
""" + formats + fields + r"""
HttpOwnedResponse httpOwned[2],*httpWriting=&httpOwned[0];
""" + "bool wifi_scan(bool retainResults=false);\n" + block(web, "bool defer_http_generated_body(") + block(web, "bool drainHttpBodies()") + block(web, "bool pollHttpResponses()") + block(soft, "void htmlEscape(") + renderer + scan + block(soft, "bool acquire_wifi_scan_results()") + block(soft, "void release_wifi_scan_results()") + result_class + cli + provision + pending + legacy + entry + block(soft, "void handle_rescan()") + block(soft, "void handle_setssid()") + r"""
void readerProgress(){
 unsigned before=asyncScans;
 wifiScanPending=true;pollWifiScan();
 assert(wifiScanOwned&&asyncScans==before);
}
void reset(){
 finishHttpBody(httpOwned[0]);httpOwned[0]=HttpOwnedResponse{};
 httpOwned[0].state=HttpOwnedState::Active;httpOwned[0].fd=7;httpWriting=&httpOwned[0];
 delivered.clear();sendCalls=0;sendError=0;now=0;
}
void populate(){
 for(int i=0;i<127;++i){wifiNet_t n;n.ssid=std::string(28,'&')+std::to_string(i/2);n.rssi=-i;wifiNets.insert(n);}
}
int main(){
 populate();legacy_page();assert(expected.size()>32000);
 reset();handle_wifinets();assert(wifiScanOwned&&httpOwned[0].body==HttpBody::Generated);
 // A pending core inspection suppresses all writer/handler operations.
 httpOwnedPending=true;assert(pollHttpResponses()&&sendCalls==0&&server.handled==0);
 httpOwnedPending=false;
 // Registry stays pinned even when a concurrent rescan is requested.
 wifi_scan();assert(scans==0&&wifiNets.size()==127&&wifiScanPending);
 unsigned count=0;
 do{
   unsigned before=sendCalls;
   // Periodic EAGAIN leaves the exact scratch span and row cursor untouched.
   sendError=(count%7==0)?EAGAIN:0;
   const auto index=wifiScanPage.index;
   const bool retainedSpan=httpOwned[0].bodyOffset<httpOwned[0].bodyLength;
   std::string scratch(writeBuffer,sizeof(writeBuffer));
   bool busy=pollHttpResponses();
   assert(sendCalls-before<=1&&retirementCalls==0); // Onboarding skips SSE services.
   if(sendError&&retainedSpan){
     assert(index==wifiScanPage.index);
     assert(scratch==std::string(writeBuffer,sizeof(writeBuffer)));
   }
   if(!busy)break;
   assert(server.handled==0); // No handler can reuse a partially sent scratch span.
   assert(++count<10000);
 }while(true);
 assert(delivered==expected&&!wifiScanOwned&&server.handled==1);
 // The deferred scan runs only after the entire old registry was consumed.
 soft_ap_loop();assert(asyncScans==1&&scans==0&&wifiNets.size()==127&&wifiScanRunning&&wifiScanOwned);
 unsigned commsIterations=0;
 for(unsigned i=0;i<100;++i){++commsIterations;soft_ap_loop();}
 assert(commsIterations==100&&scanPolls==100&&asyncScans==1&&scans==0);
 handle_rescan();assert(responseStatus==202&&!wifiScanPending);
 handle_wifinets();assert(responseStatus==202&&httpOwned[0].body==HttpBody::None);
 scanStatus=0;soft_ap_loop();assert(wifiNets.empty()&&!wifiScanRunning&&!wifiScanOwned&&!wifiScanFailed);
 // Start and completion failures release the lease and never serve old results.
 asyncStart=-2;handle_rescan();soft_ap_loop();assert(wifiScanFailed&&!wifiScanOwned&&!wifiScanRunning);
 handle_wifinets();assert(responseStatus==503);
 asyncStart=WIFI_SCAN_RUNNING;scanStatus=-2;handle_rescan();soft_ap_loop();soft_ap_loop();
 assert(wifiScanFailed&&!wifiScanOwned&&!wifiScanRunning);
 // Existing serial/Improv calls remain immediate when the registry is free.
 wifi_scan();assert(scans==1&&!wifiScanFailed&&!wifiScanOwned);
 // Normal web mode includes retirement servicing without duplicate handling.
 web_setup_done=true;unsigned handled=server.handled;pollHttpResponses();
 assert(retirementCalls==1&&server.handled==handled+1);
 populate();reset();handle_wifinets();sendError=EHOSTUNREACH;
 assert(!drainHttpBodies()&&!wifiScanOwned&&httpOwned[0].discardQueued);
 reset();handle_wifinets();now=5000;
 assert(!drainHttpBodies()&&!wifiScanOwned&&httpOwned[0].discardQueued);
 // Owner removal/disconnect calls the same idempotent cleanup path.
 reset();handle_wifinets();finishHttpBody(httpOwned[0]);finishHttpBody(httpOwned[0]);
 assert(!wifiScanOwned);
 // Renderer overflow returns a failure sentinel, never a truncated span.
 reset();handle_wifinets();uint8_t tiny[4];assert(readWifiScanPage(tiny,sizeof(tiny))==SIZE_MAX);
 finishHttpBody(httpOwned[0]);
 // Synchronous result readers keep the registry leased through iteration and
 // the CLI selection scope. The main scanner never waits for that reader.
 wifiScanPending=false;syncCount=2;
 {
   WifiScanResults results;assert(scanWifi(false,results)==2);
   assert(wifiScanOwned&&!suppressSerialLog&&wifiNets.size()==2);
   const unsigned before=asyncScans;pollWifiScan();
   assert(asyncScans==before&&wifiNets.size()==2);
 }
 assert(!wifiScanOwned);scanStatus=0;soft_ap_loop();soft_ap_loop();
 assert(!wifiScanOwned&&!wifiScanRunning);
 // Busy CLI/Improv must report unavailable, never iterate old results or emit
 // a successful Improv final marker; suppression always returns to its value.
 reset();handle_wifinets();
 for(bool saved:{false,true}){
   suppressSerialLog=saved;WifiScanResults results;
   assert(scanWifi(true,results)==UINT32_MAX&&suppressSerialLog==saved);
 }
 getAvailableWifiNetworks();assert(errors==1&&responses==0&&finalResponses==0);
 finishHttpBody(httpOwned[0]);wifiScanPending=false;
 syncCount=-2;suppressSerialLog=false;
 {WifiScanResults results;assert(scanWifi(true,results)==UINT32_MAX&&!suppressSerialLog);}
 assert(!wifiScanOwned);
 syncCount=0;suppressSerialLog=true;
 {WifiScanResults results;assert(scanWifi(true,results)==0&&suppressSerialLog&&wifiScanOwned);}
 assert(!wifiScanOwned);
 syncCount=2;getAvailableWifiNetworks();
 assert(!wifiScanOwned&&responses==2&&finalResponses==1&&errors==1);
 wifiScanPending=false;
 // HTTP selection rejects busy registry access, and releases its result lease
 // before network reconfiguration or restart can invoke another producer.
 {WifiScanResults results;assert(results.acquire());handle_setssid();assert(responseStatus==503&&configured==0);}
 handle_setssid();assert(responseStatus==200&&configured==1&&restarted==1&&!wifiScanOwned);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source, binary = Path(directory)/"wifi.cpp", Path(directory)/"wifi"
            source.write_text(harness)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-variable", "-fsanitize=address,undefined",
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
