# Lexus EV Status Overlay

A lightweight, always-on-top desktop overlay for a Raspberry Pi or Linux system. It displays the latest available status for a Lexus electric vehicle using the Toyota/Lexus connected-services API through `pytoyoda`.

The current script is configured for a Lexus vehicle using brand code `L`, and has been developed around a Lexus RZ 300e.

## Information displayed

The overlay shows:

- battery charge percentage;
- estimated driving range in miles;
- charging status;
- the local `HH:MM` time associated with the latest successful vehicle status reading.

The displayed range uses the API's air-conditioning-adjusted EV range when available. If that value is unavailable, the script falls back to the standard EV range.

## Status colours

The overlay changes colour according to the configured battery thresholds:

- **Normal:** battery level above the warning threshold;
- **Warning:** battery level at or below the warning threshold;
- **Critical:** battery level at or below the critical threshold.

The default thresholds are:

```python
LOW_BATTERY_ALERT_THRESHOLD = 30
CRITICAL_BATTERY_THRESHOLD = 25
WARNING_BATTERY_THRESHOLD = 35
```

## Refresh behaviour

The script distinguishes between two different operations:

1. **Reading Toyota's cached status**, which retrieves the most recent information already held by Toyota.
2. **Requesting a fresh vehicle status**, which asks Toyota to contact the car and may wake its telematics systems.

By default, the script:

- reads Toyota's cached status every 45 minutes;
- asks the vehicle for a fresh status if the stored vehicle data is more than two hours old;
- asks the vehicle for fresh status every 30 minutes while the car reports that it is charging;
- waits 30 seconds after requesting a vehicle refresh before reading the status again;
- prevents repeat non-charging vehicle refreshes within the configured two-hour cooldown period.

These settings are intended to balance useful data freshness against unnecessary vehicle wake-ups and associated use of the car's 12-volt battery.

## Sleep schedule

The script can be prevented from contacting either Toyota or the vehicle outside a configured active period.

The default active period is:

```python
ACTIVE_START_TIME = "07:00"
ACTIVE_END_TIME = "22:00"
```

Times use the Raspberry Pi's local system time and must be entered in 24-hour `HH:MM` format.

An overnight active period is also supported. For example:

```python
ACTIVE_START_TIME = "22:00"
ACTIVE_END_TIME = "07:00"
```

If the start and end times are identical, the script treats the service as active all day.

While outside the active period, the overlay remains open but the worker makes no Toyota API reads and sends no vehicle refresh requests. It checks once per minute to determine whether the active period has begun.

## Audible low-battery alert

When the reported battery level is below `LOW_BATTERY_ALERT_THRESHOLD`, the script attempts to:

- set the Linux master audio volume to 80%;
- play a short 1 kHz tone through the configured headphone audio device.

The audible alert is suppressed whenever the vehicle reports that it is charging.

The current alert runs after each successful eligible status check while the battery remains below the threshold. It is not limited to a single alert when the threshold is crossed.

## Configuration

The intended user-editable settings are grouped in the configuration area of the script.

### Vehicle

```python
USERNAME = "email@domain.dom"
PASSWORD = "password"
VIN = "VINnumber"
BRAND = "L"
```

- `USERNAME`: Toyota/Lexus connected-services account email address.
- `PASSWORD`: account password.
- `VIN`: full vehicle identification number.
- `BRAND`: `L` for Lexus.

> **Security note:** the current script stores credentials in plain text. Restrict access to the file and avoid publishing or sharing it. Environment variables or a protected credentials file would be safer for a longer-term deployment.

### Refresh

```python
TOYOTA_POLL_INTERVAL_SECONDS = 45 * 60
CHARGING_REFRESH_INTERVAL_SECONDS = 30 * 60
MAX_DATA_AGE_SECONDS = 2 * 60 * 60
VEHICLE_REFRESH_COOLDOWN_SECONDS = 2 * 60 * 60
REFRESH_SETTLE_SECONDS = 30
API_TIMEOUT_SECONDS = 25
```

- `TOYOTA_POLL_INTERVAL_SECONDS`: interval between cached status reads while not charging.
- `CHARGING_REFRESH_INTERVAL_SECONDS`: interval between vehicle refresh cycles while charging.
- `MAX_DATA_AGE_SECONDS`: maximum acceptable age of vehicle-supplied data before requesting a refresh.
- `VEHICLE_REFRESH_COOLDOWN_SECONDS`: minimum interval between non-charging vehicle refresh requests.
- `REFRESH_SETTLE_SECONDS`: delay after requesting a refresh before re-reading data.
- `API_TIMEOUT_SECONDS`: maximum time allowed for individual login and API operations.

### Battery thresholds

```python
LOW_BATTERY_ALERT_THRESHOLD = 30
CRITICAL_BATTERY_THRESHOLD = 25
WARNING_BATTERY_THRESHOLD = 35
```

The low-battery alert threshold controls the audible warning. The critical and warning thresholds control the visual colour scheme.

### Window

```python
WINDOW_WIDTH = 100
WINDOW_HEIGHT = 162
WINDOW_MARGIN_LEFT = 0
WINDOW_MARGIN_BOTTOM = 0
```

These values control the overlay's size and its position relative to the bottom-left corner of the primary screen.

### Sleep schedule

```python
ACTIVE_START_TIME = "07:00"
ACTIVE_END_TIME = "22:00"
SLEEP_CHECK_INTERVAL_SECONDS = 60
```

`SLEEP_CHECK_INTERVAL_SECONDS` controls how frequently the inactive worker checks whether the active period has started.

## Vehicle timestamp

The small `HH:MM` indicator is derived from `last_update_timestamp` returned by the electric-status API. It represents the time of the latest status reading supplied by the vehicle, not merely the time at which the Raspberry Pi queried Toyota.

The timestamp is converted from the API's timezone to the Raspberry Pi's configured local timezone. The Pi should therefore have the correct timezone configured.

To check it:

```bash
timedatectl
```

On a UK-based Pi, the timezone would normally be:

```text
Europe/London
```

## Requirements

The script requires:

- Python 3;
- PyQt5;
- `pytoyoda`;
- `pydantic` and `eval-type-backport` for the Python 3.9 compatibility path;
- `hishel` and `httpx`;
- an X11 graphical desktop session;
- `amixer` and `speaker-test` if the audible warning is required.

The script includes compatibility workarounds for:

- Python 3.9 type annotations used by current `pytoyoda` models;
- versions of `hishel` that no longer expose `AsyncCacheClient` as expected by `pytoyoda`.

## Example dependency installation

Package names and installation methods can vary by Raspberry Pi OS version. A typical starting point is:

```bash
sudo apt update
sudo apt install -y python3-pyqt5 alsa-utils
python3 -m pip install --user pytoyoda pydantic eval-type-backport hishel httpx
```

If the script is already working on the Pi, do not reinstall or upgrade packages unnecessarily, as the compatibility shims reflect the versions currently installed.

## Running the overlay

From the directory containing the script:

```bash
python3 lexus_overlay_updated.py
```

The script sets `DISPLAY=:0` if `DISPLAY` is not already present. It expects an active X11 graphical session on that display.

## Running automatically at sign-in

For a desktop overlay, it should normally be started after the graphical desktop session begins. The exact approach depends on the Raspberry Pi OS desktop and how the Pi is configured.

The process needs access to:

- the active X11 display;
- the configured user's Python packages;
- the audio device if audible alerts are enabled;
- network access to Toyota/Lexus connected services.

## Error handling

If an API operation fails, the overlay displays either:

```text
Err: Timeout
```

or:

```text
Err: API Error
```

The last successfully displayed battery, range and vehicle time remain visible. The worker waits until the next scheduled poll before trying again.

Detailed exception information is also printed to the process output.

## Important operational notes

### API logging

`pytoyoda` may emit detailed debug output containing sensitive information, potentially including:

- account details;
- VIN;
- request headers;
- authentication tokens;
- API response data.

Do not share unredacted logs. If credentials or live authentication tokens are exposed, change the account password and revoke sessions where possible.

### Unofficial API dependency

This script relies on `pytoyoda` and Toyota/Lexus connected-service interfaces that may change without notice. A future library or API change may require updates to the compatibility shims, authentication flow, endpoint calls or response-field handling.

### Vehicle wake-ups

The script deliberately limits requests for fresh vehicle data. Reducing refresh intervals may cause more frequent vehicle wake-ups and could increase demand on the vehicle's 12-volt electrical system.

## Current display layout

The default overlay is a small, frameless window positioned at the bottom-left of the primary display. It shows:

```text
LEXUS EV
100%
226 miles
Not Charging
09:13
```

The final line is the locally converted time of the latest vehicle-supplied status.

## File

The current script is:

```text
lexus_overlay_updated.py
```
