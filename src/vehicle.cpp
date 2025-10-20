/****************************************************************************
 * RATGDO HomeKit for ESP32
 * https://ratcloud.llc
 * https://github.com/PaulWieland/ratgdo
 *
 * Copyright (c) 2023-24 David A Kerr... https://github.com/dkerr64/
 * All Rights Reserved.
 * Licensed under terms of the GPL-3.0 License.
 *
 */

// C/C++ language includes
// None

// Arduino includes
#include <Wire.h>
#include <vl53l4cx_class.h>
#include "Ticker.h"

// RATGDO project includes
#include "ratgdo.h"
#include "led.h"
#include "vehicle.h"
#include "homekit.h"
#include "config.h"

// Logger tag
static const char *TAG = "ratgdo-vehicle";
bool vehicle_setup_done = false;

VL53L4CX distanceSensor(&Wire, SHUTDOWN_PIN);

static const int MIN_DISTANCE = 20; // ignore bugs crawling on the distance sensor

int16_t vehicleDistance = 0;
int16_t vehicleThresholdDistance = 1000; // set by user
char vehicleStatus[16] = "Away";         // or Arriving or Departing or Parked
bool vehicleStatusChange = false;

static bool vehicleDetected = false;
static bool vehicleArriving = false;
static bool vehicleDeparting = false;
static unsigned long lastChangeAt = 0;
static unsigned long presence_timer = 0; // to be set by door open action
static unsigned long vehicle_motion_timer = 0;
static std::vector<int16_t> distanceMeasurement(20, -1);

void calculatePresence(int16_t distance);

void setup_vehicle()
{
    VL53L4CX_Error rc = VL53L4CX_ERROR_NONE;
    RINFO(TAG, "=== Setup VL53L4CX time-of-flight sensor ===");

    if (vehicle_setup_done)
    {
        RINFO(TAG, "Vehicle setup already completed, skipping reinitialization");
        return;
    }

    Wire.begin(19, 18);
    distanceSensor.begin();
    rc = distanceSensor.InitSensor(0x59);
    if (rc != VL53L4CX_ERROR_NONE)
    {
        RERROR(TAG, "VL53L4CX failed to initialize error: %d", rc);
        return;
    }
    rc = distanceSensor.VL53L4CX_SetDistanceMode(VL53L4CX_DISTANCEMODE_LONG);
    if (rc != VL53L4CX_ERROR_NONE)
    {
        RERROR(TAG, "VL53L4CX_SetDistanceMode error: %d", rc);
        return;
    }
    rc = distanceSensor.VL53L4CX_StartMeasurement();
    if (rc != VL53L4CX_ERROR_NONE)
    {
        RERROR(TAG, "VL53L4CX_StartMeasurement error: %d", rc);
        return;
    }

    enable_service_homekit_vehicle();
    vehicleThresholdDistance = userConfig->getVehicleThreshold() * 10; // convert centimeters to millimeters
    vehicle_setup_done = true;
}

void vehicle_loop()
{
    if (!vehicle_setup_done)
        return;

    uint8_t dataReady = 0;
    if ((distanceSensor.VL53L4CX_GetMeasurementDataReady(&dataReady) == 0) && (dataReady > 0))
    {
        VL53L4CX_MultiRangingData_t distanceData;
        if (distanceSensor.VL53L4CX_GetMultiRangingData(&distanceData) == 0)
        {
            int16_t dist = 0;
            // Multiple objects could be found, only record the furthest away
            for (int i = 0; i < distanceData.NumberOfObjectsFound; i++)
            {
                if (distanceData.RangeData[i].RangeStatus == 0)
                    dist = std::max(dist, distanceData.RangeData[i].RangeMilliMeter);
            }
            // If a distance found, add it to our vehicle presence vector.
            if (dist > 0)
                calculatePresence(dist);
            distanceSensor.VL53L4CX_ClearInterruptAndStartMeasurement();
        }
    }

    unsigned long current_millis = millis();
    // Vehicle Arriving Clear Timer
    if (vehicleArriving && (current_millis > vehicle_motion_timer))
    {
        vehicleArriving = false;
        strlcpy(vehicleStatus, vehicleDetected ? "Parked" : "Away", sizeof(vehicleStatus));
        vehicleStatusChange = true;
        RINFO(TAG, "Vehicle status: %s", vehicleStatus);
        notify_homekit_vehicle_arriving(vehicleArriving);
    }
    // Vehicle Departing Clear Timer
    if (vehicleDeparting && (current_millis > vehicle_motion_timer))
    {
        vehicleDeparting = false;
        strlcpy(vehicleStatus, vehicleDetected ? "Parked" : "Away", sizeof(vehicleStatus));
        vehicleStatusChange = true;
        RINFO(TAG, "Vehicle status: %s", vehicleStatus);
        notify_homekit_vehicle_departing(vehicleDeparting);
    }
}

void setArriveDepart(bool vehiclePresent)
{
    if (vehiclePresent)
    {
        if (!vehicleArriving)
        {
            vehicleArriving = true;
            vehicleDeparting = false;
            vehicle_motion_timer = lastChangeAt + MOTION_TIMER_DURATION;
            strlcpy(vehicleStatus, "Arriving", sizeof(vehicleStatus));
            laser.flash(PARKING_ASSIST_TIMEOUT);
            notify_homekit_vehicle_arriving(vehicleArriving);
        }
    }
    else
    {
        if (!vehicleDeparting)
        {
            vehicleArriving = false;
            vehicleDeparting = true;
            vehicle_motion_timer = lastChangeAt + MOTION_TIMER_DURATION;
            strlcpy(vehicleStatus, "Departing", sizeof(vehicleStatus));
            notify_homekit_vehicle_departing(vehicleDeparting);
        }
    }
}

void calculatePresence(int16_t distance)
{
    if (distance < MIN_DISTANCE)
        return;

    bool allInRange = true;
    bool AllOutOfRange = true;
    int32_t sum = 0;

    distanceMeasurement.insert(distanceMeasurement.begin(), distance);
    distanceMeasurement.pop_back();
    for (int16_t value : distanceMeasurement)
    {
        if (value >= vehicleThresholdDistance || value == -1)
            allInRange = false;
        if (value < vehicleThresholdDistance && value != -1)
            AllOutOfRange = false;
        sum += value;
    }
    // calculate average of all distances... to smooth out changes
    // and convert from millimeters to centimeters
    vehicleDistance = sum / distanceMeasurement.size() / 10;

    // Test for change in vehicle presence
    bool priorVehicleDetected = vehicleDetected;
    if (allInRange)
        vehicleDetected = true;
    if (AllOutOfRange)
        vehicleDetected = false;
    if (vehicleDetected != priorVehicleDetected)
    {
        led.flash();
        // if change occurs with arrival/departure window then record motion,
        // presence timer is set when door opens.
        lastChangeAt = millis();
        if (lastChangeAt < presence_timer)
        {
            setArriveDepart(vehicleDetected);
        }
        else
        {
            strlcpy(vehicleStatus, vehicleDetected ? "Parked" : "Away", sizeof(vehicleStatus));
        }
        vehicleStatusChange = true;
        RINFO(TAG, "Vehicle status: %s", vehicleStatus);
        notify_homekit_vehicle_occupancy(vehicleDetected);
    }
}

// if notified of door opening, set timeout during which we check for arriving/departing vehicle (looking forward)
void doorOpening()
{
    if (!vehicle_setup_done)
        return;

    presence_timer = millis() + PRESENCE_DETECT_DURATION;
}

// if notified of door closing, check for arrived/departed vehicle within time window (looking back)
void doorClosing()
{
    if (!vehicle_setup_done)
        return;

    if ((millis() > PRESENCE_DETECT_DURATION) && ((millis() - lastChangeAt) < PRESENCE_DETECT_DURATION))
    {
        setArriveDepart(vehicleDetected);
        RINFO(TAG, "Vehicle status: %s", vehicleStatus);
    }
}
