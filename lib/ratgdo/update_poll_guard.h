#pragma once
#include <mutex>

// Pause polling at HomeSpan's own iteration boundary. Deleting its task leaves
// a stale handle and can strand locks or crash a subsequent upload attempt.
template <class Mutex> class UpdatePollGuard
{
    std::unique_lock<Mutex> lock;

public:
    explicit UpdatePollGuard(Mutex &mutex) : lock(mutex, std::defer_lock) {}
    void pause() { if (!lock.owns_lock()) lock.lock(); }
    void resume() { if (lock.owns_lock()) lock.unlock(); }
};
