#pragma once

// Compatibility helpers to bridge Arduino-ESP32 3.x (IDF 5) changes with
// libraries that were written against the older 2.x core.

#include <esp_idf_version.h>

extern "C"
{
#include <esp_now.h>
#include <driver/touch_pad.h>
}

#if ESP_IDF_VERSION_MAJOR >= 5

// -----------------------------------------------------------------------------
// touchSetCycles() was removed from the public Arduino API in core 3.x. Provide
// a shim that maps to the new ESP-IDF 5 touch driver functions so legacy code
// continues to compile. Values are passed through without reinterpretation,
// mirroring the old behaviour (sleep cycles, measure cycles).
// -----------------------------------------------------------------------------
#if !defined(TOUCHSETCYCLES_COMPAT_DEFINED)
#define TOUCHSETCYCLES_COMPAT_DEFINED 1
extern "C" inline void touchSetCycles(uint16_t measureCycles, uint16_t sleepCycles)
{
#if defined(touch_pad_set_measurement_clock_cycles)
    touch_pad_set_measurement_clock_cycles(measureCycles);
    touch_pad_set_measurement_interval(sleepCycles);
#else
    touch_pad_set_meas_time(sleepCycles, measureCycles);
#endif
}
#endif

// -----------------------------------------------------------------------------
// ESPNOW send callback signature changed to use wifi_tx_info_t in IDF 5. Capture
// requests that still use the legacy const uint8_t* MAC signature and adapt
// them on the fly.
// -----------------------------------------------------------------------------
namespace esp_now_compat
{
    using LegacySendCallback = void (*)(const uint8_t *, esp_now_send_status_t);

    inline LegacySendCallback legacy_send_cb = nullptr;

    inline void shim_send_cb(const esp_now_send_info_t *info, esp_now_send_status_t status)
    {
        const uint8_t *mac = nullptr;
        if (info != nullptr && info->des_addr != nullptr)
        {
            mac = info->des_addr;
        }
        if (legacy_send_cb != nullptr)
        {
            legacy_send_cb(mac, status);
        }
    }

    inline esp_err_t register_send_cb(LegacySendCallback cb)
    {
        legacy_send_cb = cb;
        return ::esp_now_register_send_cb(static_cast<esp_now_send_cb_t>(shim_send_cb));
    }
} // namespace esp_now_compat

// Overload esp_now_register_send_cb for the legacy signature. Libraries that
// were built against the 2.x core will continue to call this without changes.
inline esp_err_t esp_now_register_send_cb(esp_now_compat::LegacySendCallback cb)
{
    return esp_now_compat::register_send_cb(cb);
}

#endif // ESP_IDF_VERSION_MAJOR >= 5
