
#include <algorithm>
#include <cassert>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>
#define F(x) x
#define FPSTR(x) x
#define log_v(...) ((void)0)
#define log_e(...) ((void)0)
#define WEBSERVER_MAX_POST_ARGS 32
#define HTTP_UPLOAD_BUFLEN 32
#define HTTP_MAX_POST_WAIT 5000
#define WEBSERVER_MAX_LINE_LEN 4096
#define WEBSERVER_MAX_POST_ARG_LEN 16384
#define WEBSERVER_MAX_MULTIPART_SKIP_LINES 64
#define WEBSERVER_MAX_LINE_WAIT 5000
static unsigned clockMs=0;
unsigned millis(){return clockMs;}
void delay(unsigned n){clockMs+=n;}
void yield(){++clockMs;}
struct String {
    std::string s;
    String()=default; String(const char*p):s(p){} String(std::string p):s(std::move(p)){}
    size_t length()const{return s.size();} const char*c_str()const{return s.c_str();}
    int indexOf(char c)const{auto n=s.find(c);return n==s.npos?-1:int(n);}
    String substring(size_t a,size_t b=std::string::npos)const{return a>=s.size()?String():String(s.substr(a,b-a));}
    bool startsWith(const String&p)const{return s.compare(0,p.s.size(),p.s)==0;}
    bool equalsIgnoreCase(const String&p)const{std::string a=s,b=p.s; std::transform(a.begin(),a.end(),a.begin(),::tolower);std::transform(b.begin(),b.end(),b.begin(),::tolower);return a==b;}
    String&operator+=(const String&p){s+=p.s;assert(s.size()<1024*1024);return *this;}
    String&operator+=(char c){s+=c;return *this;}
    friend bool operator==(const String&a,const String&b){return a.s==b.s;}
    friend String operator+(const String&a,const String&b){return String(a.s+b.s);}
};
struct NetworkClient {
    std::string bytes;size_t at=0;bool stayConnected=true;unsigned byteDelay=0;
    int read(){if(at>=bytes.size())return -1;clockMs+=byteDelay;return uint8_t(bytes[at++]);}
    int peek(){return at<bytes.size()?uint8_t(bytes[at]):-1;}
    int available(){return int(bytes.size()-at);}
    bool connected(){return stayConnected||at<bytes.size();}
    long getTimeout(){return 5;}
    String readStringUntil(char delimiter){String out;int c;while((c=read())>=0){if(c==delimiter)return out;out+=char(c);}clockMs+=5;return out;}
};
enum {UPLOAD_FILE_START,UPLOAD_FILE_WRITE,UPLOAD_FILE_END,UPLOAD_FILE_ABORTED};
struct HTTPUpload {int status;String name,filename,type;size_t totalSize=0,currentSize=0;uint8_t buf[HTTP_UPLOAD_BUFLEN]{};};
struct RequestArgument {String key,value;};
class WebServer;
struct Handler {std::vector<int>events;bool canUpload(WebServer&,const String&){return true;}void upload(WebServer&,const String&,HTTPUpload&u){events.push_back(u.status);}};
namespace mime {constexpr int txt=0;struct Mime{const char*mimeType;};static Mime mimeTable[]={{"text/plain"}};}
static const char Content_Type[]="Content-Type",filename[]="filename";
class WebServer {
public:
    RequestArgument*_postArgs=nullptr,*_currentArgs=nullptr;int _postArgsLen=0,_currentArgCount=0;
    Handler handler;Handler*_currentHandler=&handler;String _currentUri="/update";std::unique_ptr<HTTPUpload>_currentUpload;
    ~WebServer(){delete[]_postArgs;delete[]_currentArgs;}
    bool hasArg(const char*){return false;}String arg(const char*){return String();}
    void _uploadWriteByte(uint8_t);int _uploadReadByte(NetworkClient&);bool _parseForm(NetworkClient&,const String&,uint32_t);bool _parseFormUploadAborted();
};

// SOURCE_PARSER

int main(int argc,char**argv){
    assert(argc==2);std::string mode=argv[1];NetworkClient client;bool expected=false;
    const std::string file="--b\r\nContent-Disposition: form-data; name=\"content\"; filename=\"firmware.bin\"\r\nContent-Type: application/octet-stream\r\n\r\nABC\r\n--b";
    if(mode=="header-stall")client.bytes="--b\r\n";
    else if(mode=="field-stall")client.bytes="--b\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\nvalue\r\n";
    else if(mode=="trailer-stall")client.bytes=file;
    else if(mode=="payload-stall")client.bytes=file.substr(0,file.size()-7);
    else if(mode=="valid-file"){client.bytes=file+"--\r\n";expected=true;}
    else if(mode=="empty-field"){client.bytes="--b\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\n\r\n--b--\r\n";expected=true;}
    else if(mode=="multiline-field"){client.bytes="--b\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\na\r\n\r\nb\r\n--b--\r\n";expected=true;}
    else if(mode=="oversized-header"){client.bytes="--b\r\n"+std::string(5000,'X')+"\r\n";}
    else if(mode=="oversized-field"){client.bytes="--b\r\nContent-Disposition: form-data; name=\"note\"\r\n\r\n"+std::string(20000,'X')+"\r\n--b--\r\n";}
    else if(mode=="unknown-lines"){client.bytes="--b\r\n";for(int i=0;i<65;++i)client.bytes+="unknown\r\n";}
    else if(mode=="empty-lines"){client.bytes="--b\r\n";for(int i=0;i<65;++i)client.bytes+="\r\n";}
    else if(mode=="slow-header"){client.bytes="--b\r\n"+std::string(5000,'X')+"\r\n";client.byteDelay=4;}
    else return 2;
    WebServer server;bool result=server._parseForm(client,"b",client.bytes.size());assert(result==expected);
    if(mode=="valid-file"){assert(server.handler.events.front()==UPLOAD_FILE_START&&server.handler.events.back()==UPLOAD_FILE_END);}
    if(mode=="payload-stall"){assert(server.handler.events.back()==UPLOAD_FILE_ABORTED);}
    if(mode=="empty-field"){assert(server._currentArgCount==1&&server._currentArgs[0].value==String());}
    if(mode=="multiline-field"){assert(server._currentArgs[0].value==String("a\n\nb"));}
    if(mode=="slow-header"){assert(clockMs<6000);}
    printf("PASS %s elapsed=%u events=%zu\n",mode.c_str(),clockMs,server.handler.events.size());
}
