#include "../lib/ratgdo/sse_write.h"
#include <cassert>
#include <cerrno>
#include <fcntl.h>
#include <initializer_list>
#include <sys/socket.h>
#include <unistd.h>

int main()
{
    const char frame[] = "event: message\ndata: {}\n\n";
    for (long result : {-1L, 0L, 3L, static_cast<long>(sizeof(frame) - 1)})
    {
        unsigned sends = 0, closes = 0;
        bool ok = write_sse_frame(frame, sizeof(frame) - 1,
            [&](const char *p, std::size_t n) -> long {
                ++sends;
                assert(p == frame && n == sizeof(frame) - 1);
                return result;
            }, [&] { ++closes; });
        assert(sends == 1); // No retry or wait on backpressure or short writes.
        assert(ok == (result == sizeof(frame) - 1));
        assert(closes == (ok ? 0U : 1U));
    }

    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    assert(fcntl(sockets[0], F_SETFL, O_NONBLOCK) == 0);
    char fill[4096] = {};
    while (send(sockets[0], fill, sizeof(fill), MSG_DONTWAIT) > 0) {}
    assert(errno == EAGAIN || errno == EWOULDBLOCK);
    bool closed = false;
    assert(!write_sse_frame(frame, sizeof(frame) - 1,
        [&](const char *p, std::size_t n) -> long {
            return send(sockets[0], p, n, MSG_DONTWAIT);
        }, [&] { closed = true; }));
    assert(closed);
    close(sockets[0]);
    close(sockets[1]);
}
