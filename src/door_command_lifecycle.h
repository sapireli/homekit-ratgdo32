/****************************************************************************
 * RATGDO HomeKit
 * https://ratcloud.llc
 * https://github.com/PaulWieland/ratgdo
 *
 * Copyright (c) 2023-26 David A Kerr... https://github.com/dkerr64/
 * All Rights Reserved.
 * Licensed under terms of the GPL-3.0 License.
 *
 * Contributions acknowledged from
 * Thomas Hagan...     https://github.com/tlhagan
 * Brandon Matthews... https://github.com/thenewwazoo
 * Jonathan Stroud...  https://github.com/jgstroud
 * Mitchell Solomon... https://github.com/mitchjs
 *
 */

#pragma once
#include <stdint.h>

// A queued button press is cancellable until its first UART write. Once written,
// its release must survive superseding requests and timeouts.
class DoorCommandLifecycle
{
public:
    enum class Intent { None, Open, Close, Stop, Toggle };
    uint32_t begin(int physicalState, uint32_t now, Intent logicalIntent = Intent::None)
    {
        generation = ++nextGeneration;
        if (!generation)
            generation = ++nextGeneration;
        initialState = physicalState;
        queuedIntent = logicalIntent;
        startedAt = now;
        committed = released = changed = false;
        deferred = Intent::None;
        return generation;
    }
    bool request(Intent intent, uint32_t now)
    {
        expire(now);
        if (!generation)
            return false;
        if (!committed)
        {
            if (keepsQueuedTarget(intent))
                return true; // Keep the original pair even when no queue space remains.
            cancel();
            return false;
        }
        defer(intent, now);
        return true;
    }
    void defer(Intent intent, uint32_t now)
    {
        if (generation)
        {
            deferred = intent;
            deferredAt = now;
        }
    }
    bool allow(uint32_t token, bool press) const
    {
        if (!token)
            return true;
        if (press)
            return token == generation && !committed;
        return token == generation || token == mandatoryRelease;
    }
    void writing(uint32_t token, bool press)
    {
        if (!token)
            return;
        if (press)
        {
            committed = true;
            mandatoryRelease = token;
        }
        else
        {
            if (token == generation)
                released = true;
            if (token == mandatoryRelease)
                mandatoryRelease = 0;
        }
    }
    void status(int state)
    {
        if (state < 0 || state > 4)
        {
            cancel(); // Unknown/corrupt feedback cannot authorize more movement.
            return;
        }
        if (!generation || state == initialState)
            return;
        if (!committed)
            cancel(); // A physical control superseded our still-queued command.
        else
            changed = true;
    }
    Intent poll(uint32_t now)
    {
        expire(now);
        if (!generation || !committed || !released || !changed)
            return Intent::None;
        Intent result = deferred;
        if (static_cast<uint32_t>(now - deferredAt) >= 3000)
            result = Intent::None;
        cancel();
        return result;
    }
    void expire(uint32_t now)
    {
        if (generation && static_cast<uint32_t>(now - startedAt) >= 3000)
            cancel();
    }
    void cancel()
    {
        generation = 0;
        deferred = Intent::None;
        queuedIntent = Intent::None;
        committed = released = changed = false;
    }
    void reset()
    {
        cancel();
        mandatoryRelease = 0;
    }
    bool pending() const { return generation != 0; }
    bool keepsQueuedTarget(Intent intent) const
    {
        return generation && !committed && intent == queuedIntent &&
               (intent == Intent::Open || intent == Intent::Close);
    }
    bool needsRelease(uint32_t token) const { return token && token == mandatoryRelease; }
private:
    uint32_t nextGeneration = 0, generation = 0, mandatoryRelease = 0;
    uint32_t startedAt = 0, deferredAt = 0;
    int initialState = 0;
    bool committed = false, released = false, changed = false;
    Intent deferred = Intent::None;
    Intent queuedIntent = Intent::None;
};
