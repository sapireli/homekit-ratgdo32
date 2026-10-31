"""Run the actual nonblocking HTTP writer and log cursor with ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HTTPResponse(unittest.TestCase):
    def test_streaming_and_failures(self):
        web = (ROOT / "src/web.cpp").read_text()
        log = (ROOT / "src/log.cpp").read_text()
        self.assertIn("HTTP_BODY_MAX_LIFETIME_MS = HTTP_MAX_SEND_WAIT;", web)
        self.assertIn("class OwnedWebServer : public WebServer", web)
        fields = web[web.index("enum class HttpOwnedState"):web.index("struct HttpOwnedCounters")]
        writer = web[web.index("size_t httpResponseWrite(NetworkClient &client"):
                     web.index("void setupHttpOwnedExperiment()")]
        cursor = log[log.index("void LOG::beginMessageLog"):
                     log.index("void LOG::printMessageLogHeader")]
        diagnostic = log[log.index("namespace {\n// Formatting writes"):
                         log.index("void LOG::beginMessageLog")]
        fixture = r'''
#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <string>
using ssize_t=long;
struct netconn;struct tcp_pcb;struct ip_addr_t{};
static unsigned now;
static uint32_t _millis(){return now;}
static unsigned calls,fallback;
static size_t sendLimit=SIZE_MAX;
static int sendError;
static std::string sent;
constexpr int MSG_DONTWAIT=1;
static ssize_t send(int fd,const void*p,size_t n,int flags){
 assert(fd==7&&flags==MSG_DONTWAIT);++calls;
 if(sendError){errno=sendError;return -1;}
 n=std::min(n,sendLimit);sent.append((const char*)p,n);return n;
}
class Print {public:virtual ~Print()=default;virtual size_t write(uint8_t)=0;
 virtual size_t write(const uint8_t*,size_t)=0;};
struct NetworkClient {int descriptor=7;int fd()const{return descriptor;}
 size_t write(const uint8_t*,size_t n){++fallback;return n;}};
static char writeBuffer[512];
static uint64_t logAppendBytes;
static uint32_t diagnosticRevision;
static unsigned crashCount=1;
static unsigned held;
#define TAKE_MUTEX() (++held)
#define GIVE_MUTEX() (--held)
struct LOG {
 struct MessageCursor{uint64_t next=0,end=0;size_t index=0;};
 struct DiagnosticCursor{size_t offset=0;uint32_t revision=0;uint8_t stage=0;bool crash=false,savedCrash=false;};
 std::string savedText,crashText,coreText;
 struct Buffer {bool wrapped=false;size_t head=0;char buffer[16384];} storage{},*msgBuffer=&storage;
 void beginMessageLog(MessageCursor&);
 size_t readMessageLog(MessageCursor&,uint8_t*,size_t,bool&);
 void printMessageLogHeader(Print&p){const char*h="Header\n";p.write((const uint8_t*)h,strlen(h));}
 void beginDiagnosticLog(DiagnosticCursor&,bool);
 size_t readDiagnosticLog(DiagnosticCursor&,uint8_t*,size_t,bool&);
 void printSavedLog(Print&p){p.write((const uint8_t*)savedText.data(),savedText.size());}
 void printCrashLog(Print&p,bool includeCore){assert(!includeCore);p.write((const uint8_t*)crashText.data(),crashText.size());}
 void printCoreDump(Print&p,bool saved){assert(saved);p.write((const uint8_t*)coreText.data(),coreText.size());}
 void append(const std::string&s){for(char c:s){storage.buffer[storage.head++]=c;
 if(storage.head==sizeof(storage.buffer)){storage.head=0;storage.wrapped=true;}
 storage.buffer[storage.head]=0;++logAppendBytes;}}
};
static LOG logger,*ratgdoLogger=&logger;
''' + diagnostic + cursor + fields + r'''
static HttpOwnedResponse httpOwned[2],*httpWriting;
static bool httpOwnedPending;
constexpr uint32_t HTTP_BODY_MAX_LIFETIME_MS=5000;
''' + writer + r'''
static void reset(){httpOwned[0]=HttpOwnedResponse{};httpOwned[0].state=HttpOwnedState::Active;
 httpOwned[0].fd=7;httpWriting=&httpOwned[0];now=0;calls=fallback=sendError=0;
 sendLimit=SIZE_MAX;sent.clear();}
static void finish(){for(unsigned i=0;i<10000;++i){if(!drainHttpBodies())return;
 assert(!held);}assert(false);}
int main(){
 std::string asset(65536,'a');
 reset();assert(deferHttpAsset((const uint8_t*)asset.data(),asset.size()));
 sendLimit=137;finish();assert(sent==asset&&calls>100&&fallback==0);
 // A full send buffer waits for another iteration without closing or spinning.
 reset();deferHttpAsset((const uint8_t*)asset.data(),asset.size());sendError=EAGAIN;
 assert(drainHttpBodies()&&calls==1&&!httpOwned[0].writeFailed);
 sendError=0;finish();assert(sent==asset);
 // Immediate headers and small responses discard on any incomplete write.
 for(int error:{0,EAGAIN,ENOMEM,EHOSTUNREACH}){
  reset();sendLimit=2;sendError=error;NetworkClient client;
  assert(httpResponseWrite(client,(const uint8_t*)"header",6)<6);
  assert(httpOwned[0].writeFailed&&httpOwned[0].discardQueued&&client.fd()==7);
  unsigned previous=calls;httpResponseWrite(client,(const uint8_t*)"body",4);
  assert(calls==previous&&fallback==0);
 }
 // A fatal deferred write preserves ownership for the verified retirement path.
 reset();deferHttpAsset((const uint8_t*)asset.data(),asset.size());sendError=EHOSTUNREACH;
 assert(!drainHttpBodies()&&httpOwned[0].discardQueued&&httpOwned[0].owner.fd()==7);
 reset();deferHttpAsset((const uint8_t*)asset.data(),asset.size());httpOwnedPending=true;
 assert(drainHttpBodies()&&calls==0);httpOwnedPending=false;
 now=4999;assert(drainHttpBodies());now=5000;
 assert(!drainHttpBodies()&&httpOwned[0].discardQueued);
 reset();now=UINT32_MAX-100;deferHttpAsset((const uint8_t*)asset.data(),asset.size());
 now=4898;assert(drainHttpBodies());now=4899;
 assert(!drainHttpBodies()&&httpOwned[0].discardQueued);
 // Snapshot headers and ring bytes are streamed in order, excluding later appends.
 std::string initial;for(unsigned i=0;i<16000;++i)initial+=char('A'+i%26);
 logger.append(initial);reset();deferHttpMessageLog();logger.append("later\n");
 finish();assert(sent=="Header\n"+initial&&!held);
 logger.append(std::string(5000,'z'));std::string all=initial+"later\n"+std::string(5000,'z');
 reset();deferHttpMessageLog();finish();assert(sent=="Header\n"+all.substr(all.size()-16383));
 reset();deferHttpMessageLog();assert(drainHttpBodies());logger.append(std::string(17000,'n'));
 finish();assert(sent=="Header\n\nLog truncated: newer messages overwrote unread log data.\n");
 // Failed header formatting cannot expose a stale/partial log body.
 reset();HttpBufferPrint p;std::string oversized(513,'x');
 assert(p.write((const uint8_t*)oversized.data(),oversized.size())==512&&p.failed);
 assert(fallback==0&&!held);
 // Retained reboot and crash output must also complete under short writes.
 logger.savedText=std::string(16384,'r');logger.crashText=std::string(8192,'c');logger.coreText="Core summary\n";
 reset();deferHttpDiagnosticLog(false);sendLimit=37;finish();
 assert(sent==logger.savedText&&fallback==0&&!held);
 reset();deferHttpDiagnosticLog(true);sendLimit=31;finish();
 assert(sent==logger.crashText+logger.coreText&&fallback==0&&!held);
 reset();deferHttpDiagnosticLog(false);assert(drainHttpBodies());++diagnosticRevision;
 finish();assert(sent==logger.savedText.substr(0,256)+"\nDiagnostic log changed during download; please request it again.\n");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "response.cpp"
            binary = Path(directory) / "response"
            cpp.write_text(fixture)
            subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
