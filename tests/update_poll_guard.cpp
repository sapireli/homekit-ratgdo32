#include "../lib/ratgdo/update_poll_guard.h"
#include <cassert>
#include <future>
#include <shared_mutex>

struct PollMutex
{
    bool locked = false;
    unsigned locks = 0, unlocks = 0;
    void lock() { assert(!locked); locked = true; ++locks; }
    void unlock() { assert(locked); locked = false; ++unlocks; }
};

int main()
{
    PollMutex mutex;
    {
        UpdatePollGuard<PollMutex> update(mutex);
        update.resume(); // No polling task, or an unauthenticated/verify request.
        assert(!mutex.locked && mutex.unlocks == 0);
        update.pause();
        update.pause(); // Re-entering after a failed transfer is idempotent.
        assert(mutex.locked && mutex.locks == 1);
        update.resume(); // Both success and abort resume polling.
        update.resume();
        assert(!mutex.locked && mutex.unlocks == 1);
        update.pause(); // A second upload does not use a deleted task handle.
        assert(mutex.locked && mutex.locks == 2);
    }
    assert(!mutex.locked && mutex.unlocks == 2);

    std::shared_mutex homekitMutex;
    UpdatePollGuard<std::shared_mutex> homekit(homekitMutex);
    auto pollCanRun = [&] {
        return std::async(std::launch::async, [&] {
            if (!homekitMutex.try_lock()) return false;
            homekitMutex.unlock();
            return true;
        }).get();
    };
    assert(pollCanRun());
    homekit.pause();
    assert(!pollCanRun());
    homekit.pause(); // A retry cannot lock recursively or touch a task handle.
    assert(!pollCanRun());
    homekit.resume();
    assert(pollCanRun());
    homekit.resume();
    assert(pollCanRun());
}
