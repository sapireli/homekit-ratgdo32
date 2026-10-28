#pragma once
#include <cstddef>

// SSE is disposable: if a nonblocking send cannot accept the entire event,
// close the stream so EventSource reconnects instead of keeping a partial frame.
// The send operation must itself be nonblocking (MSG_DONTWAIT on ESP32).
template <class Send, class Close>
bool write_sse_frame(const char *data, std::size_t length, Send send, Close close)
{
    if (send(data, length) == static_cast<long>(length))
        return true;
    close();
    return false;
}
