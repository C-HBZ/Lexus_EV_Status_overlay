import sys

# ===========================================================
# CONFIGURATION
# ===========================================================

# --- Vehicle ---
USERNAME = "email"
PASSWORD = "password"
VIN = "VIN-code"
BRAND = "L"

# --- Refresh ---
TOYOTA_POLL_INTERVAL_SECONDS = 45 * 60       # Read Toyota's cached status every 45 minutes
CHARGING_REFRESH_INTERVAL_SECONDS = 30 * 60  # Ask the car for fresh data every 30 minutes while charging
MAX_DATA_AGE_SECONDS = 2 * 60 * 60           # Ask the car for fresh data when vehicle data is over 2 hours old
VEHICLE_REFRESH_COOLDOWN_SECONDS = 2 * 60 * 60
REFRESH_SETTLE_SECONDS = 60                   # Allow time for the car to respond before reading again
API_TIMEOUT_SECONDS = 25

# --- Battery thresholds ---
LOW_BATTERY_ALERT_THRESHOLD = 30
CRITICAL_BATTERY_THRESHOLD = 25
WARNING_BATTERY_THRESHOLD = 35

# --- Window ---
WINDOW_WIDTH = 100
WINDOW_HEIGHT = 162
WINDOW_MARGIN_LEFT = 0
WINDOW_MARGIN_BOTTOM = 0

# --- Sleep schedule ---
# No Toyota API reads or vehicle refresh requests are made outside this period.
# Use 24-hour HH:MM values. Overnight schedules such as 22:00 to 07:00 are supported.
ACTIVE_START_TIME = "06:00"
ACTIVE_END_TIME = "21:00"
SLEEP_CHECK_INTERVAL_SECONDS = 60

# ===========================================================


# --- 1. PYTHON 3.9 PYDANTIC / PYTOYODA COMPATIBILITY PATCH ---
if sys.version_info < (3, 10):
    import typing
    import eval_type_backport

    _orig_etb = eval_type_backport.eval_type_backport

    def _patched_etb(*args, **kwargs):
        if not args:
            return typing.Any
        val = args[0]
        if isinstance(val, str):
            val = typing.ForwardRef(val)
        elif not isinstance(val, typing.ForwardRef):
            try:
                val = typing.ForwardRef(str(val))
            except Exception:
                pass
        try:
            return _orig_etb(val, *args[1:3])
        except Exception:
            return typing.Any

    eval_type_backport.eval_type_backport = _patched_etb
    try:
        import pydantic._internal._typing_extra as _te
        _te.eval_type_backport = _patched_etb
    except ImportError:
        pass

# --- 2. HISHEL 1.X COMPATIBILITY SHIM FOR PYTOYODA ---
import hishel
import httpx

if not hasattr(hishel, "AsyncCacheClient"):
    class _HishelAsyncCacheClientShim(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            storage = kwargs.pop("storage", None)
            controller = kwargs.pop("controller", None)
            kwargs.pop("ttl", None)
            if "transport" not in kwargs and hasattr(hishel, "AsyncCacheTransport"):
                try:
                    kwargs["transport"] = hishel.AsyncCacheTransport(
                        storage=storage, controller=controller
                    )
                except Exception:
                    pass
            super().__init__(*args, **kwargs)

    hishel.AsyncCacheClient = _HishelAsyncCacheClientShim

# -----------------------------------------------------------
import os
import time
import asyncio
import subprocess
from datetime import datetime, time as dt_time
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QFrame
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from pytoyoda import MyT

# Prevent Qt High-DPI scaling from altering X11 display scaling
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

# Force X11 display context
if "DISPLAY" not in os.environ:
    os.environ["DISPLAY"] = ":0"





def trigger_low_battery_beep():
    """Set system audio volume to 80% and play a short warning tone."""
    cmd = (
        "amixer set Master 80% >/dev/null 2>&1; "
        "timeout 1.5s speaker-test -D hw:Headphones -t sine -f 1000 2>/dev/null || "
        "timeout 1.5s speaker-test -D plughw:1,0 -t sine -f 1000 2>/dev/null"
    )
    try:
        subprocess.run(cmd, shell=True, capture_output=True)
    except Exception as exc:
        print(f"[AUDIO ERROR] Failed to play alert beep: {exc}")


def parse_config_time(value):
    return datetime.strptime(value, "%H:%M").time()


def is_within_active_period(now=None):
    now = now or datetime.now().astimezone()
    current = now.time().replace(tzinfo=None)
    start = parse_config_time(ACTIVE_START_TIME)
    end = parse_config_time(ACTIVE_END_TIME)

    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def is_charging_status(status):
    return str(status).strip().lower() in {"charging", "charge", "on"}


class ApiWorker(QThread):
    # battery, status, range, battery level, vehicle timestamp, error
    data_updated = pyqtSignal(str, str, str, int, object, str)

    def __init__(self):
        super().__init__()
        self.last_vehicle_refresh_request = None
        self.last_known_charging = False

    async def _create_logged_in_client(self):
        client = MyT(username=USERNAME, password=PASSWORD, brand=BRAND)
        await asyncio.wait_for(client.login(), timeout=API_TIMEOUT_SECONDS)
        return client

    async def _get_electric_status(self, client):
        return await asyncio.wait_for(
            client._api.get_vehicle_electric_status(VIN),
            timeout=API_TIMEOUT_SECONDS,
        )

    async def _request_vehicle_refresh(self, client):
        await asyncio.wait_for(
            client._api.refresh_electric_realtime_status(VIN),
            timeout=API_TIMEOUT_SECONDS,
        )

    def _refresh_allowed(self, now):
        if self.last_vehicle_refresh_request is None:
            return True
        if self.last_known_charging:
            interval = CHARGING_REFRESH_INTERVAL_SECONDS
        else:
            interval = VEHICLE_REFRESH_COOLDOWN_SECONDS
        return (now - self.last_vehicle_refresh_request).total_seconds() >= interval

    async def _fetch_status(self):
        client = await self._create_logged_in_client()
        response = await self._get_electric_status(client)
        payload = response.payload
        now = datetime.now().astimezone()

        vehicle_timestamp = payload.last_update_timestamp
        if vehicle_timestamp is not None:
            vehicle_timestamp = vehicle_timestamp.astimezone()
            data_age = max(0, (now - vehicle_timestamp).total_seconds())
        else:
            data_age = float("inf")

        self.last_known_charging = is_charging_status(payload.charging_status)

        refresh_due = (
            self.last_known_charging
            or data_age > MAX_DATA_AGE_SECONDS
        ) and self._refresh_allowed(now)

        if refresh_due and is_within_active_period():
            print("[INFO] Requesting fresh status from vehicle")
            await self._request_vehicle_refresh(client)
            self.last_vehicle_refresh_request = now
            await asyncio.sleep(REFRESH_SETTLE_SECONDS)

            # Recheck the sleep boundary before making the follow-up Toyota read.
            if is_within_active_period():
                response = await self._get_electric_status(client)
                payload = response.payload

        return payload

    def run(self):
        while True:
            if not is_within_active_period():
                time.sleep(SLEEP_CHECK_INTERVAL_SECONDS)
                continue

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    payload = loop.run_until_complete(self._fetch_status())
                finally:
                    loop.close()

                battery_level = int(payload.battery_level)
                battery = f"{battery_level}%"
                charging = is_charging_status(payload.charging_status)
                status = "Charging" if charging else "Not Charging"

                # Use the AC-adjusted range as the displayed range, falling back if absent.
                range_value = payload.ev_range_with_ac or payload.ev_range
                if range_value:
                    miles_value = round(range_value.value * 0.621371)
                    ev_range = f"{miles_value} miles"
                else:
                    ev_range = "N/A"

                vehicle_timestamp = payload.last_update_timestamp
                if vehicle_timestamp is not None:
                    vehicle_timestamp = vehicle_timestamp.astimezone()

                self.data_updated.emit(
                    battery,
                    status,
                    ev_range,
                    battery_level,
                    vehicle_timestamp,
                    "",
                )

                # Never sound the alert while the vehicle reports that it is charging.
                if battery_level < LOW_BATTERY_ALERT_THRESHOLD and not charging:
                    trigger_low_battery_beep()

                wait_seconds = (
                    CHARGING_REFRESH_INTERVAL_SECONDS
                    if charging
                    else TOYOTA_POLL_INTERVAL_SECONDS
                )

            except Exception as exc:
                print(f"[ERROR] API Request Failed: {exc}")
                err_msg = "Timeout" if isinstance(exc, asyncio.TimeoutError) else "API Error"
                self.data_updated.emit("", "", "", 0, None, err_msg)
                wait_seconds = TOYOTA_POLL_INTERVAL_SECONDS

            time.sleep(wait_seconds)


class LexusEVOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.start_worker()

    def init_ui(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.SubWindow
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)

        self.container = QFrame()
        self.container.setObjectName("Container")

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(0)

        self.lbl_title = QLabel("LEXUS EV")
        self.lbl_title.setStyleSheet(
            "color: #AAAAAA; font-family: Helvetica; font-size: 15px; "
            "font-weight: bold; background: transparent; margin-bottom: -30px;"
        )

        self.lbl_battery = QLabel("--%")
        self.lbl_battery.setStyleSheet(
            "color: #FFFFFF; font-family: Helvetica; font-size: 44px; "
            "font-weight: bold; background: transparent; margin-top: -4px; "
            "margin-bottom: -4px;"
        )

        self.lbl_range = QLabel("-- miles")
        self.lbl_range.setStyleSheet(
            "color: #FFFFFF; font-family: Helvetica; font-size: 18px; "
            "background: transparent; margin-top: -2px; margin-bottom: -2px;"
        )

        self.lbl_status = QLabel("Initialising...")
        self.lbl_status.setStyleSheet(
            "color: #888888; font-family: Helvetica; font-size: 14px; "
            "background: transparent; margin-top: 0px;"
        )

        self.lbl_vehicle_time = QLabel("--:--")
        self.lbl_vehicle_time.setStyleSheet(
            "color: #777777; font-family: Helvetica; font-size: 11px; "
            "background: transparent; margin-top: 1px;"
        )

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_battery)
        layout.addWidget(self.lbl_range)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.lbl_vehicle_time)

        root_layout.addWidget(self.container)
        self.setLayout(root_layout)

        screen = QApplication.primaryScreen().geometry()
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.move(
            WINDOW_MARGIN_LEFT,
            screen.height() - WINDOW_HEIGHT - WINDOW_MARGIN_BOTTOM,
        )

        self._set_container_style("rgba(40, 40, 40, 0.50)")

    def _set_container_style(self, bg_color):
        self.container.setStyleSheet(
            f"""
            QFrame#Container {{
                background-color: {bg_color};
                border-radius: 16px;
            }}
            """
        )

    def update_ui(self, battery, status, ev_range, battery_level, vehicle_timestamp, error):
        if error:
            self.lbl_status.setText(f"Err: {error}")
            self.lbl_status.setStyleSheet(
                "color: #FF5555; font-family: Helvetica; font-size: 14px; "
                "background: transparent;"
            )
            return

        if battery_level <= CRITICAL_BATTERY_THRESHOLD:
            bat_color = "#FF5555"
            bg_color = "rgba(255, 85, 85, 0.32)"
        elif battery_level <= WARNING_BATTERY_THRESHOLD:
            bat_color = "#FFAA00"
            bg_color = "rgba(255, 170, 0, 0.32)"
        else:
            bat_color = "#FFFFFF"
            bg_color = "rgba(46, 125, 50, 0.35)"

        self._set_container_style(bg_color)
        self.lbl_battery.setText(battery)
        self.lbl_battery.setStyleSheet(
            f"color: {bat_color}; font-family: Helvetica; font-size: 44px; "
            "font-weight: bold; background: transparent; margin-top: -4px; "
            "margin-bottom: -4px;"
        )
        self.lbl_range.setText(ev_range)
        self.lbl_status.setText(status)
        self.lbl_status.setStyleSheet(
            "color: #888888; font-family: Helvetica; font-size: 14px; "
            "background: transparent; margin-top: 0px;"
        )
        self.lbl_vehicle_time.setText(
            vehicle_timestamp.strftime("%H:%M") if vehicle_timestamp else "--:--"
        )

    def start_worker(self):
        self.worker = ApiWorker()
        self.worker.data_updated.connect(self.update_ui)
        self.worker.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    overlay = LexusEVOverlay()
    overlay.show()
    sys.exit(app.exec_())
