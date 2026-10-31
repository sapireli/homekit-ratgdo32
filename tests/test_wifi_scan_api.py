"""Compile the public scan API and actual callers without the HTTP experiment."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_wifi_scan_delivery import block

ROOT = Path(__file__).resolve().parents[1]


class WifiScanApiTest(unittest.TestCase):
    def test_feature_disabled_targets(self):
        soft = (ROOT / "src/softAP.cpp").read_text()
        production = "\n".join(block(soft, declaration) for declaration in [
            "static void storeWifiScanResults(", "bool wifi_scan(bool retainResults)",
            "bool acquire_wifi_scan_results()", "void release_wifi_scan_results()", "void handle_rescan()"])
        production += block((ROOT / "src/serialCLI.cpp").read_text(), "uint32_t scanWifi(bool uniqueSSID, WifiScanResults &results)\n{")
        production += block((ROOT / "src/provision.cpp").read_text(), "void getAvailableWifiNetworks()")
        harness = r"""
#include <cassert>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <type_traits>
#define PROGMEM
#define PSTR(s) s
#define ESP_LOGI(...) ((void)0)
class String:public std::string {public:using std::string::string;using std::string::operator=;
 String()=default;String(const std::string&s):std::string(s){}String(int n):std::string(std::to_string(n)){};};
using wifi_auth_mode_t=int;
#include "softAP.h"
bool compare(const wifiNet_t&a,const wifiNet_t&b){return a.ssid<b.ssid;}
std::multiset<wifiNet_t,bool(*)(const wifiNet_t&,const wifiNet_t&)>wifiNets(compare);
#ifdef ESP32
static std::atomic<bool>wifiScanOwned{false};
#endif
int result=2;
unsigned scans=0;
struct Wifi {
 int scanNetworks(){++scans;return result;}void scanDelete(){}
 String SSID(int){return "home";}int RSSI(int){return -40;}int channel(int){return 1;}
 const uint8_t*BSSID(int){static uint8_t b[6]{};return b;}String BSSIDstr(int){return "mac";}
 int encryptionType(int){return 0;}
}WiFi;
const char*encryptionToString(uint16_t){return "";}
bool suppressSerialLog=false;
struct SerialMock{void println(){}void printf_P(const char*,...){}}Serial;
namespace improv {constexpr int ERROR_UNKNOWN=1,GET_WIFI_NETWORKS=2;
 std::vector<uint8_t>build_rpc_response(int,const std::vector<std::string>&s,bool){return {static_cast<uint8_t>(s.empty()?0:1)};}}
constexpr int AUTH_OPEN=0,WIFI_AUTH_OPEN=0;
unsigned responses=0,finalResponses=0,errors=0;
void send_response(const std::vector<uint8_t>&d){++responses;if(d[0]==0)++finalResponses;}
void set_error(int){++errors;}
void delay(unsigned){}
int status=0;
const char*type_txt="text/plain";
struct Server{void send_P(int s,const char*,const char*){status=s;}}server;
""" + production + r"""
int main(){
 static_assert(std::is_same<decltype(wifi_scan()),bool>::value,"scan returns status");
 assert(wifi_scan()&&wifiNets.size()==2);
 {WifiScanResults results;assert(results.scan());unsigned n=scans;assert(results.scan()&&scans==n);}
 {WifiScanResults results;assert(results.acquire());
#ifdef ESP32
  assert(!wifi_scan());
  WifiScanResults second;assert(!second.acquire());
#endif
 }
 for(bool saved:{false,true}){
  suppressSerialLog=saved;result=0;
  {WifiScanResults results;assert(scanWifi(true,results)==0&&suppressSerialLog==saved);}
  result=-2;
  {WifiScanResults results;assert(scanWifi(true,results)==UINT32_MAX&&suppressSerialLog==saved);}
 }
 result=2;{WifiScanResults results;assert(scanWifi(true,results)==1);}
 getAvailableWifiNetworks();assert(responses==2&&finalResponses==1&&errors==0);
 result=-2;getAvailableWifiNetworks();assert(responses==2&&finalResponses==1&&errors==1);
 handle_rescan();assert(status==503);
 result=0;handle_rescan();assert(status==200);
 release_wifi_scan_results();
}
"""
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "softAP.h").write_text((ROOT / "src/softAP.h").read_text())
            (directory / "ratgdo.h").write_text("#pragma once\n")
            source, binary = directory / "scan.cpp", directory / "scan"
            source.write_text(harness)
            for target in ["ESP32", "ESP8266"]:
                subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                "-Wno-unused-variable", "-D" + target,
                                "-fsanitize=address,undefined", str(source), "-o", str(binary)], check=True)
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
