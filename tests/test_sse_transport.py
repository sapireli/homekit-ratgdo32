from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class SSETransport(unittest.TestCase):
    def test_actual_nonblocking_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            src = (ROOT / 'src/web.cpp').read_text()
            start = src.index('bool clientWrite(WiFiClient client, const char *data)')
            end = src.index('// Helper functions for connection throttling', start)
            code = r'''
            #include <cassert>
            #include <cerrno>
            #include <cstring>
            #include <fcntl.h>
            #include <initializer_list>
            #include <string>
            #include <sys/socket.h>
            #include <unistd.h>
            struct WiFiClient {
                int socket;
                unsigned *closed;
                int fd() { return socket; }
                void stop() { ++*closed; }
            };
            static long result;
            static unsigned calls;
            static std::string captured;
            static bool realSend;
            static ssize_t testSend(int fd, const void *data, size_t length, int flags) {
                assert(flags == MSG_DONTWAIT);
                ++calls;
                captured.assign(static_cast<const char *>(data), length);
                if (realSend) return ::send(fd, data, length, flags);
                return result == -2 ? static_cast<ssize_t>(length) : result;
            }
            #define ESP32
            #define send testSend
            '''+src[start:end]+r'''
            #undef send
            int main() {
                const std::string expected = "event: message\ndata: {}\n\n";
                for (long r : {-1L, 0L, 3L, -2L}) {
                    unsigned closed = 0; calls = 0; result = r;
                    WiFiClient c{0, &closed};
                    bool ok = sendSSEEvent(c, "message", "{}");
                    assert(calls == 1 && captured == expected);
                    assert(ok == (r == -2));
                    assert(closed == (ok ? 0U : 1U));
                }
                unsigned closed = 0; calls = 0; result = -2;
                std::string payload(8192, 'x');
                WiFiClient c{0, &closed};
                assert(sendSSEEvent(c, "logger", payload.c_str()));
                assert(calls == 1 && captured == "event: logger\ndata: " + payload + "\n\n");
                int sockets[2];
                assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
                assert(fcntl(sockets[0], F_SETFL, O_NONBLOCK) == 0);
                char fill[4096] = {};
                while (::send(sockets[0], fill, sizeof(fill), MSG_DONTWAIT) > 0) {}
                assert(errno == EAGAIN || errno == EWOULDBLOCK);
                realSend = true; calls = 0; closed = 0;
                c.socket = sockets[0];
                assert(!sendSSEEvent(c, "message", "{}"));
                assert(calls == 1 && closed == 1);
                close(sockets[0]); close(sockets[1]);
            }
            '''
            root=Path(temporary); (root/'source_test.cpp').write_text(code)
            subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(root/'source_test.cpp'),'-o',str(root/'source_test')],check=True)
            subprocess.run([str(root/'source_test')],check=True)
            print('Actual web.cpp SSE functions: full, short, zero, error, large frame, and full socket tests passed')

if __name__ == "__main__":
    unittest.main()
