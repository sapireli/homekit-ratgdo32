"""Exercise production metadata callbacks with truncated and malformed input."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class WebMetadata(unittest.TestCase):
    def test_metadata_validation_and_atomic_failure(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "src/web.cpp").read_text()
        code = source[source.index("struct RequestJsonField"):source.index("bool helperFactoryReset")]
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <variant>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define ESP8266_SAVE_CONFIG() ((void)0)
constexpr unsigned SSE_MAX_CHANNELS=2;
constexpr const char *cfg_wwwUsername="name",*cfg_wwwCredentials="credentials",*nvram_ratgdo_pw="password";
struct configSetting {};
struct configStr { size_t max; char *str; };
struct Config {
    std::string name="old-user",credentials="old-credentials";
    unsigned writes=0;
    auto get(const char*) { return std::variant<configStr>(configStr{32,nullptr}); }
    void set(const char *key,const char *value) {
        ++writes;
        (key==cfg_wwwUsername?name:credentials)=value;
    }
} config,*userConfig=&config;
std::string password="old-password";
void write_door_str(const char*,const char *value){++config.writes;password=value;}
size_t strlcpy(char *out,const char *in,size_t size){size_t n=strlen(in);if(size){size_t copy=n<size-1?n:size-1;memcpy(out,in,copy);out[copy]=0;}return n;}
struct Client {bool connected(){return true;}};
struct SSESubscription {bool SSEconnected=true;std::string clientUUID="session";Client client;};
SSESubscription subscription[SSE_MAX_CHANNELS];
SSESubscription *firmwareUpdateSub=&subscription[1];
size_t firmwareSize=777;
char firmwareMD5[36]="old-md5";
struct SSELock {explicit operator bool()const{return true;}};
''' + code + r'''
using Callback=bool(*)(const std::string&,const char*,configSetting*);
bool run(Callback callback,std::string value){return callback("",value.c_str(),nullptr);}
void rejected(Callback callback,const std::string&value){
    const unsigned writes=config.writes;const auto oldName=config.name,oldPassword=password,oldCredentials=config.credentials;
    const auto size=firmwareSize;const std::string md5=firmwareMD5;const auto sub=firmwareUpdateSub;
    assert(!run(callback,value));
    assert(config.writes==writes&&config.name==oldName&&password==oldPassword&&config.credentials==oldCredentials);
    assert(firmwareSize==size&&md5==firmwareMD5&&sub==firmwareUpdateSub);
}
int main(){
    subscription[0].clientUUID="other-session";
    const std::string creds=R"({"username":"alice","credentials":"0123456789abcdef0123456789abcdef","password":"secret"})";
    const std::string update=R"({"md5":"0123456789abcdef0123456789abcdef","size":128,"uuid":"session"})";
    for(size_t n=0;n<creds.size();++n)rejected(helperCredentials,creds.substr(0,n));
    for(size_t n=0;n<update.size();++n)rejected(helperUpdateUnderway,update.substr(0,n));
    for(const auto&value:std::vector<std::string>{"", "null", "[]", "{", "{\"username\":\"alice\",\"credentials\":\"x\",\"password\":\"unterminated", creds+" trailing",
        R"({"username":"alice","credentials":"0123456789abcdef0123456789abcdef","username":"again"})",
        R"({"username":"alice","credentials":"not-hex","password":"secret"})",
        R"({"username":"alice","credentials":"0123456789abcdef0123456789abcdef","password":"\u0000"})",
        R"({"username":"alice","credentials":"0123456789abcdef0123456789abcdef","password":"\uD800"})",
        R"({"username":"alice","credentials":"0123456789abcdef0123456789abcdef","password":"\x"})"})rejected(helperCredentials,value);
    for(const auto&size:std::vector<std::string>{"-1","+1","0","01","1e3","1.0","\"128\"","4294967296","18446744073709551616","1garbage"}){
        std::string value=update;value.replace(value.find("128"),3,size);rejected(helperUpdateUnderway,value);
    }
    assert(run(helperCredentials,creds));assert(config.name=="alice"&&password=="secret");
    assert(run(helperCredentials,R"({"password":"username \"hello\" \\ /\n\u00E9\uD83D\uDE00","username":"bob","credentials":"ABCDEF0123456789ABCDEF0123456789"})"));
    assert(config.name=="bob"&&password=="username \"hello\" \\ /\n\xC3\xA9\xF0\x9F\x98\x80");
    assert(run(helperUpdateUnderway,update));
    assert(firmwareSize==128&&std::string(firmwareMD5)=="0123456789abcdef0123456789abcdef"&&firmwareUpdateSub==&subscription[1]);
    // Embedded field-name strings must not redirect key matching.
    assert(run(helperCredentials,R"({"password":"username credentials password","credentials":"0123456789abcdef0123456789abcdef","username":"carol"})"));
    assert(config.name=="carol"&&password=="username credentials password");
    // Every single-byte mutation remains memory safe; malformed requests do not commit.
    for(size_t n=0;n<update.size();++n)for(unsigned c=1;c<128;++c){
        auto value=update;value[n]=static_cast<char>(c);run(helperUpdateUnderway,value);
    }
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "metadata.cpp"
            binary = Path(directory) / "metadata"
            cpp.write_text(fixture)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-parameter", "-fsanitize=address,undefined",
                            str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
