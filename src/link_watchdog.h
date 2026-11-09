/****************************************************************************
 * Network link watchdog decision logic (no platform dependencies).
 *
 * The device can stay associated to the access point while its link stops
 * passing traffic (observed: 45-100% loss, multi-second RTT, cleared only by
 * reboot). Nothing raises a disconnect event in that state, so nothing
 * recovers it. The caller pings the gateway periodically and feeds each
 * ping session's sent/received counts here. A sustained-loss window first
 * forces a WiFi reconnect; a second bad window after that reboots.
 */
#pragma once
#include <stdint.h>

// Calibration knobs: tune from field logs (syslog "Link" lines).
#define LINK_CHECK_INTERVAL_MS (30 * 1000) // one ping session every 30s
#define LINK_PINGS_PER_CHECK 5             // pings per session
#define LINK_WINDOW_CHECKS 4               // sessions per evaluation window (~2 min)
#define LINK_BAD_LOSS_PCT 30               // window loss that counts as degraded
#define LINK_RECOVERED_WINDOWS 5           // healthy windows after reconnect to call it recovered

enum LinkAction : uint8_t
{
    LINK_NONE,
    LINK_RECONNECT,
    LINK_REBOOT,
    LINK_RECOVERED,
};

struct LinkWatch
{
    bool armed = false;       // gateway has answered at least once (it does answer ping)
    bool reconnected = false; // a reconnect was tried and has not yet proven recovered
    bool skipWindow = false;  // discard the window that spans our own reconnect
    uint8_t checks = 0;
    uint8_t healthyWindows = 0;
    uint16_t sent = 0;
    uint16_t lost = 0;
};

struct LinkResult
{
    LinkAction action;
    bool evaluated;   // a window completed on this call
    uint8_t lossPct;  // loss of the completed window
};

static inline LinkResult link_watch_step(LinkWatch &w, uint32_t sent, uint32_t received)
{
    LinkResult r = {LINK_NONE, false, 0};
    if (received > sent)
        received = sent;
    if (received > 0)
        w.armed = true;
    // Never act against a gateway that has never answered ping.
    if (!w.armed || sent == 0)
        return r;

    w.sent += sent;
    w.lost += sent - received;
    if (++w.checks < LINK_WINDOW_CHECKS)
        return r;

    r.evaluated = true;
    r.lossPct = (uint8_t)((w.lost * 100u) / w.sent);
    w.checks = 0;
    w.sent = 0;
    w.lost = 0;

    if (w.skipWindow)
    {
        w.skipWindow = false;
        r.evaluated = false;
        return r;
    }

    if (r.lossPct >= LINK_BAD_LOSS_PCT)
    {
        w.healthyWindows = 0;
        if (!w.reconnected)
        {
            w.reconnected = true;
            w.skipWindow = true;
            r.action = LINK_RECONNECT;
        }
        else
        {
            r.action = LINK_REBOOT;
        }
    }
    else if (w.reconnected && ++w.healthyWindows >= LINK_RECOVERED_WINDOWS)
    {
        w.reconnected = false;
        w.healthyWindows = 0;
        r.action = LINK_RECOVERED;
    }
    return r;
}
