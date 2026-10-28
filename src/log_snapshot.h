#pragma once

#include <cstdlib>
#include <cstring>
#include <memory>

// Keep allocation and output outside the logger lock. The ring is copied as a
// whole so its head, wrap flag, and bytes describe the same instant.
template <typename Buffer, typename Lock, typename Unlock, typename Output>
bool withLogSnapshot(const Buffer *source, Lock lock, Unlock unlock, Output output,
                     void *(*allocate)(size_t) = std::malloc)
{
    if (!source)
    {
        output(source);
        return true;
    }
    std::unique_ptr<Buffer, decltype(&std::free)> snapshot(
        static_cast<Buffer *>(allocate(sizeof(Buffer))), &std::free);
    if (!snapshot)
        return false;
    lock();
    std::memcpy(snapshot.get(), source, sizeof(Buffer));
    unlock();
    output(snapshot.get());
    return true;
}
