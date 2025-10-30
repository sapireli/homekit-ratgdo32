/****************************************************************************
 * RATGDO HomeKit for ESP32
 * https://ratcloud.llc
 * https://github.com/PaulWieland/ratgdo
 *
 * Copyright (c) 2023-24 David A Kerr... https://github.com/dkerr64/
 * All Rights Reserved.
 * Licensed under terms of the GPL-3.0 License.
 *
 * Contributions acknowledged from
 * Thomas Hagan... https://github.com/tlhagan
 *
 */

// RATGDO project includes
#include "ratgdo.h"
#include "config.h"
#include "comms.h"
#include "drycontact.h"

// Logger tag
static const char *TAG = "ratgdo-drycontact";

static bool drycontact_setup_done = false;
static bool dryContactCommandsEnabled = false;

void onOpenSwitchPress();
void onCloseSwitchPress();
void onOpenSwitchRelease();
void onCloseSwitchRelease();

// Define OneButton objects for open/close pins
OneButton buttonOpen(DRY_CONTACT_OPEN_PIN, true, true); // Active low, with internal pull-up
OneButton buttonClose(DRY_CONTACT_CLOSE_PIN, true, true);
bool dryContactDoorOpen = false;
bool dryContactDoorClose = false;
bool previousDryContactDoorOpen = false;
bool previousDryContactDoorClose = false;

void setup_drycontact()
{
    RINFO(TAG, "=== Setting up dry contact protocol");

    if (drycontact_setup_done)
    {
        RINFO(TAG, "Dry contact setup already completed, skipping reinitialization");
        return;
    }

    if (doorControlType == 0)
        doorControlType = userConfig->getGDOSecurityType();

    dryContactCommandsEnabled = userConfig->getDcCommandEnable();
    RINFO(TAG, "Dry-contact command mode %s", dryContactCommandsEnabled ? "enabled" : "disabled");

    doorState = DoorState::Unknown;

    pinMode(DRY_CONTACT_OPEN_PIN, INPUT_PULLUP);
    pinMode(DRY_CONTACT_CLOSE_PIN, INPUT_PULLUP);

    // Attach OneButton handlers
    buttonOpen.attachPress(onOpenSwitchPress);
    buttonOpen.attachClick(onOpenSwitchRelease);
    buttonOpen.attachLongPressStop(onOpenSwitchRelease);
    buttonClose.attachPress(onCloseSwitchPress);
    buttonClose.attachClick(onCloseSwitchRelease);
    buttonClose.attachLongPressStop(onCloseSwitchRelease);

    drycontact_setup_done = true;
}

void drycontact_loop()
{
    if (!drycontact_setup_done)
        return;

    // Poll OneButton objects
    buttonOpen.tick();
    buttonClose.tick();

    const bool secMode = (doorControlType == 1 || doorControlType == 2);
    const bool commandMode = dryContactCommandsEnabled && secMode;

    if (doorControlType == 3)
    {
        if (dryContactDoorOpen)
        {
            doorState = DoorState::Open;
        }

        if (dryContactDoorClose)
        {
            doorState = DoorState::Closed;
        }

        if (!dryContactDoorClose && !dryContactDoorOpen)
        {
            if (previousDryContactDoorClose)
            {
                doorState = DoorState::Opening;
            }
            else if (previousDryContactDoorOpen)
            {
                doorState = DoorState::Closing;
            }
        }

        if (previousDryContactDoorOpen != dryContactDoorOpen)
        {
            previousDryContactDoorOpen = dryContactDoorOpen;
        }

        if (previousDryContactDoorClose != dryContactDoorClose)
        {
            previousDryContactDoorClose = dryContactDoorClose;
        }
    }
    else if (commandMode)
    {
        if (dryContactDoorOpen)
        {
            bool shouldClose = (garage_door.current_state == GarageDoorCurrentState::CURR_OPEN ||
                                garage_door.current_state == GarageDoorCurrentState::CURR_OPENING);
            if (shouldClose)
            {
                RINFO(TAG, "Dry-contact door command -> close");
                close_door();
            }
            else
            {
                RINFO(TAG, "Dry-contact door command -> open");
                open_door();
            }
            // clear state flag (release handler sets false as well)
            dryContactDoorOpen = false;
        }

        if (dryContactDoorClose)
        {
            bool targetLightState = !garage_door.light;
            RINFO(TAG, "Dry-contact light command -> %s", targetLightState ? "on" : "off");
            set_light(targetLightState);
            dryContactDoorClose = false;
        }
    }
    else
    {
        // Dry contacts unused in this mode; clear latched state so presses do not accumulate.
        dryContactDoorOpen = false;
        dryContactDoorClose = false;
    }
}

/*************************** DRY CONTACT CONTROL OF DOOR ***************************/
// Functions for sensing GDO open/closed
void onOpenSwitchPress()
{
    dryContactDoorOpen = true;
    RINFO(TAG, "Open switch pressed");
}

void onCloseSwitchPress()
{
    dryContactDoorClose = true;
    RINFO(TAG, "Close switch pressed");
}

void onOpenSwitchRelease()
{
    dryContactDoorOpen = false;
    RINFO(TAG, "Open switch released");
}

void onCloseSwitchRelease()
{
    dryContactDoorClose = false;
    RINFO(TAG, "Close switch released");
}
