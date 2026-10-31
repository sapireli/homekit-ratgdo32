/****************************************************************************
 * RATGDO HomeKit
 * https://ratcloud.llc
 * https://github.com/PaulWieland/ratgdo
 *
 * Copyright (c) 2023-25 David A Kerr... https://github.com/dkerr64/
 * All Rights Reserved.
 * Licensed under terms of the GPL-3.0 License.
 *
 */

// RATGDO project includes
#include "ratgdo.h"
#include "led.h"

// Logger tag
// static const char *TAG = "ratgdo-led";

// Construct the singleton object for LED access
LED led(LED_BUILTIN, LED_BUILTIN_ON_STATE);
#ifdef RATGDO32_DISCO
LED laser(LASER_PIN);
#endif

// Constructor for LED class
LED::LED(uint8_t gpio_num, uint8_t state)
{
    pin = gpio_num;
    activeState = onState = state;
    // off is opposite of on, which can be zero or one.
    currentState = offState = (onState == 1) ? 0 : 1;
    idleState = (activeState == 1) ? 0 : 1;
#ifndef ESP32
    LEDtimer = Ticker();
#endif
    pinMode(pin, OUTPUT);
}

bool LED::setupFlashTimer()
{
#ifdef ESP32
    if (!flashTimerSetup)
    {
        flashTimerSetup = true;
        esp_timer_create_args_t args{};
        args.callback = flashExpired;
        args.arg = this;
        args.dispatch_method = ESP_TIMER_TASK;
        args.name = "LED flash";
        if (esp_timer_create(&args, &flashTimer) != ESP_OK)
            flashTimer = nullptr;
    }
    return flashTimer != nullptr;
#else
    return true;
#endif
}

#ifdef ESP32
void LED::flashExpired(void *arg)
{
    auto *light = static_cast<LED *>(arg);
    light->idle();
    // Keep admission closed until idle() and its notification have finished.
    light->flashPending.store(false, std::memory_order_release);
}
#endif

void LED::on()
{
    digitalWrite(pin, onState);
    currentState = onState;
    if (stateChangeCallback)
        stateChangeCallback(state());
}

void LED::off()
{
    digitalWrite(pin, offState);
    currentState = offState;
    if (stateChangeCallback)
        stateChangeCallback(state());
}

void LED::idle()
{
    digitalWrite(pin, idleState);
    currentState = idleState;
    if (stateChangeCallback)
        stateChangeCallback(state());
}

void LED::setIdleState(uint8_t state)
{
    // 0 = LED flashes on (off when idle)
    // 1 = LED flashes off (on when idle)
    // 2 = LED disabled (active and idle both off)
    if (state == 2)
    {
        idleState = activeState = offState;
    }
    else
    {
        idleState = state ? onState : offState;
        // active state is opposite of idle state which can be zero or one.
        activeState = (idleState == 1) ? 0 : 1;
    }
}


void LED::flash(uint64_t ms)
{
#ifdef ESP32
    // The handle and raw callback remain stable for this global LED's lifetime.
    // An expired timer may still have its callback queued or running.
    if (!flashTimer || ms == 0 || ms > UINT64_MAX / 1000)
        return;
    bool expected = false;
    if (!flashPending.compare_exchange_strong(expected, true, std::memory_order_acquire))
        return;
    if (pin != UINT8_MAX)
        digitalWrite(pin, activeState);
    currentState = activeState;
    if (stateChangeCallback)
        stateChangeCallback(state());
    if (esp_timer_start_once(flashTimer, ms * 1000) != ESP_OK)
    {
        idle(); // Failed starts must not leave the laser illuminated.
        flashPending.store(false, std::memory_order_release);
    }
#else
    // Don't flash if we are already in a flash.
    if (!LEDtimer.active())
    {
        digitalWrite(pin, activeState);
        currentState = activeState;
        if (stateChangeCallback)
            stateChangeCallback(state());
        LEDtimer.once_ms(ms, [this]()
                         { this->idle(); });
    }
#endif
}
