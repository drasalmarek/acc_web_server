from flask import Flask, render_template, request, jsonify, send_from_directory
import asyncio
import io
import re
import zipfile
from flask import send_file
from bleak import BleakClient
from collections import deque
from datetime import datetime
from pathlib import Path
import time
import threading
import signal
import sys

from raw_data_parser import process_data_file, save_to_csv

app = Flask(__name__)
FILE_PACKET_SIZE = 1024
MEASURED_DATA_DIR = Path(__file__).resolve().parent / "measured_data"
COMMAND_DELAY_SECONDS = 0.2
HEARTBEAT_INTERVAL_SECONDS = 1.0

UART_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

SENSOR_ADDR = [
    #"C6:E6:A3:FC:45:F5",
    #"EB:F8:1D:58:73:87",
    "D2:F3:34:16:59:B1"
    #"CB:71:2E:31:FC:98",
    #"E7:31:E9:B5:72:2A"
]

ENABLED_SENSORS = {
    "ADXL": True,
    "BNO": False,
    "ADC": False,
}


class BLEDevice:
    def __init__(self, address):
        self.address = address
        self.client = None
        self.loop = None
        self.pending_task = None
        self.pending_future = None
        self.pending_task_lock = threading.Lock()
        self.command_lock = asyncio.Lock()
        self.heartbeat_task = None

    async def connect(self):
        self.client = BleakClient(self.address)
        await self.client.connect()
        await self.client.start_notify(UART_TX_CHAR_UUID, ble_notification_callback)
        add_log(f"BLE připojeno: {self.address}")

    async def disconnect(self):
        if self.client:
            try:
                await self.stop_heartbeat()
                if self.client.is_connected:
                    add_log(f"Odpojování od zařízení {self.address}")
                    try:
                        await self.send_command("POW:OFF")
                    except Exception as error:
                        add_log(f"POW:OFF před odpojením selhalo: {error}")
                    try:
                        await self.client.stop_notify(UART_TX_CHAR_UUID)
                    except Exception:
                        pass
                if self.client.is_connected:
                    await self.client.disconnect()
                    add_log(f"BLE odpojeno: {self.address}")
            finally:
                self.client = None
                self.loop = None

    async def send_command(self, command):
        if not self.client or not self.client.is_connected:
            raise RuntimeError("Device is not connected")

        if not command.endswith("\n"):
            command += "\n"

        async with self.command_lock:
            add_log(f"BLE TX: {command.rstrip()}")
            await self.client.write_gatt_char(
                UART_RX_CHAR_UUID,
                command.encode("utf-8")
            )
            await asyncio.sleep(COMMAND_DELAY_SECONDS)

    async def heartbeat(self):
        while self.client and self.client.is_connected:
            started_at = time.monotonic()
            try:
                await self.send_command("SYST:COMM:HEAR")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                add_log(f"BLE heartbeat selhal: {error}")
            elapsed = time.monotonic() - started_at
            await asyncio.sleep(max(0, HEARTBEAT_INTERVAL_SECONDS - elapsed))

    def start_heartbeat(self):
        if not self.loop or self.loop.is_closed():
            raise RuntimeError("BLE event loop is not running")
        if not self.heartbeat_task or self.heartbeat_task.done():
            self.heartbeat_task = self.loop.create_task(self.heartbeat())

    async def stop_heartbeat(self):
        task = self.heartbeat_task
        self.heartbeat_task = None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def run(self, coroutine):
        if not self.loop or self.loop.is_closed():
            raise RuntimeError("BLE event loop is not running")
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        with self.pending_task_lock:
            self.pending_future = future
        try:
            return future.result()
        finally:
            with self.pending_task_lock:
                if self.pending_future is future:
                    self.pending_future = None

    def run_on_loop(self, coroutine):
        if not self.loop or self.loop.is_closed():
            raise RuntimeError("BLE event loop is not running")

        task = self.loop.create_task(coroutine)
        with self.pending_task_lock:
            self.pending_task = task
        try:
            return self.loop.run_until_complete(task)
        finally:
            with self.pending_task_lock:
                if self.pending_task is task:
                    self.pending_task = None

    def cancel_pending(self):
        with self.pending_task_lock:
            task = self.pending_task
            future = self.pending_future
            loop = self.loop
        if task and loop and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)
        if future:
            future.cancel()

    def disconnect_sync(self):
        loop = self.loop
        if loop and not loop.is_closed():
            try:
                self.run(self.disconnect())
            finally:
                loop.call_soon_threadsafe(loop.stop)


class FileReceiver:
    def __init__(self):
        self.receiving = False
        self.started = False
        self.file = None
        self.file_path = None
        self.filename = None
        self.file_size = 0
        self.rx_bytes = 0
        self.packet_buffer = bytearray()
        self.complete_event = threading.Event()

    def prepare(self, filename):
        self.abort(delete_file=False)
        self.filename = Path(filename).name
        self.complete_event = threading.Event()

    def start(self, filename, file_size):
        self.abort(delete_file=False)
        self.filename = Path(filename).name
        MEASURED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.file_path = MEASURED_DATA_DIR / self.filename
        self.file = open(self.file_path, "wb")
        self.file_size = file_size
        self.rx_bytes = 0
        self.packet_buffer = bytearray()
        self.started = True
        self.receiving = True
        self.complete_event.clear()
        add_log(f"Začínám přijímat soubor {self.filename} ({file_size} B)")

    def add_data(self, data):
        if not self.receiving or not self.file:
            return 0

        self.packet_buffer.extend(data)
        acknowledgements = 0
        while self.packet_buffer:
            remaining = self.file_size - self.rx_bytes
            block_size = min(FILE_PACKET_SIZE, remaining)
            if len(self.packet_buffer) < block_size:
                break

            block = self.packet_buffer[:block_size]
            del self.packet_buffer[:block_size]
            self.file.write(block)
            self.file.flush()
            self.rx_bytes += block_size
            acknowledgements += 1
            add_log(f"Přijato {self.rx_bytes}/{self.file_size} B")

            if self.rx_bytes >= self.file_size:
                self.finish()
                break

        return acknowledgements

    def finish(self):
        if self.file:
            self.file.close()
            self.file = None
        self.receiving = False
        self.complete_event.set()
        add_log(f"File receive complete: {self.file_path}")

    def abort(self, delete_file=False):
        file_path = self.file_path
        if self.file:
            self.file.close()
            self.file = None
        self.receiving = False
        self.started = False
        self.packet_buffer = bytearray()
        if delete_file and file_path:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass


ble_device = None
connection_status = "Disconnected"
connection_lock = threading.Lock()
cycle_lock = threading.Lock()
cycle_active = False
cycle_status = "Idle"
cycle_stop_event = threading.Event()
log_entries = deque(maxlen=500)
log_lock = threading.Lock()
configuration_feedback = {
    "ADXL": None,
    "BNO": None,
    "ADC": None,
}
configuration_lock = threading.Lock()
pending_config_key = None
measurement_sd_ready_event = None
file_receiver = FileReceiver()
control_rx_buffer = bytearray()
sd_response_buffer = bytearray()
archive_lock = threading.Lock()
shutdown_lock = threading.Lock()
shutdown_started = False


def add_log(message):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    with log_lock:
        log_entries.append(entry)
    print(entry, flush=True)


def handle_shutdown(signum, frame):
    global shutdown_started

    with shutdown_lock:
        if shutdown_started:
            return
        shutdown_started = True

    signal_name = signal.Signals(signum).name
    add_log(f"Ukončuji aplikaci ({signal_name}), vypínám zařízení")
    cycle_stop_event.set()

    device = ble_device
    if device and device.client and device.client.is_connected:
        try:
            if device.loop and device.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    device.disconnect(), device.loop
                )
                future.result(timeout=10)
            else:
                add_log("BLE event loop při ukončování neběží, odpojení dokončí worker")
        except Exception as error:
            add_log(f"BLE odpojení při ukončování selhalo: {error}")

    sys.exit(0)


def filter_enabled_sensor_commands(config_commands):
    filtered_commands = []
    for command in config_commands:
        match = re.match(r"\s*CONF:(ADXL|BNO|ADC)\b", command, re.IGNORECASE)
        if not match or ENABLED_SENSORS.get(match.group(1).upper(), True):
            filtered_commands.append(command)
        else:
            add_log(f"Ignoruji konfiguraci zakázaného snímače {match.group(1).upper()}")
    return filtered_commands


def ble_notification_callback(sender, data):
    global pending_config_key, measurement_sd_ready_event, control_rx_buffer, sd_response_buffer

    raw_data = bytes(data)

    if file_receiver.receiving:
        acknowledgement_count = file_receiver.add_data(raw_data)
        for _ in range(acknowledgement_count):
            if ble_device and ble_device.client and ble_device.client.is_connected:
                asyncio.create_task(ble_device.send_command("FIL:ACK"))
        return

    try:
        text = raw_data.decode("utf-8", errors="replace").rstrip("\r\n")
    except Exception:
        text = raw_data.hex(" ")
    add_log(f"BLE RX ({sender}): {text}")

    control_rx_buffer.extend(raw_data)
    sd_response_buffer.extend(raw_data)
    if len(sd_response_buffer) > 64:
        del sd_response_buffer[:-64]
    if re.search(rb"SD\s+Init\s+OK", sd_response_buffer, re.IGNORECASE):
        add_log("SD karta inicializována")
        if measurement_sd_ready_event is not None:
            measurement_sd_ready_event.set()

    while b"\n" in control_rx_buffer:
        line_raw, remainder = control_rx_buffer.split(b"\n", 1)
        control_rx_buffer = bytearray(remainder)
        line = line_raw.decode("utf-8", errors="replace").strip("\r")

        file_match = re.search(r"Sending file:\s*(.*?),\s*(\d+)", line)
        if file_match:
            file_receiver.start(file_match.group(1), int(file_match.group(2)))
            if control_rx_buffer:
                acknowledgement_count = file_receiver.add_data(control_rx_buffer)
                control_rx_buffer = bytearray()
                for _ in range(acknowledgement_count):
                    if ble_device and ble_device.client and ble_device.client.is_connected:
                        asyncio.create_task(ble_device.send_command("FIL:ACK"))
            break

        if "File receive complete" in line:
            file_receiver.finish()

        # Odpověď na CONF:xxx? má formát například 1,400,6 nebo 0,400.
        with configuration_lock:
            key = pending_config_key
            if key:
                match = re.search(r"\b([01])\s*,\s*(\d+)(?:\s*,\s*(1[0-5]|[0-9]))?\b", line)
                if match:
                    configuration_feedback[key] = {
                        "enabled": bool(int(match.group(1))),
                        "rate": int(match.group(2)),
                        "axes": int(match.group(3)) if match.group(3) is not None else None,
                    }
                    add_log(f"Aktuální konfigurace {key}: {configuration_feedback[key]}")


def connection_worker(address):
    global ble_device, connection_status

    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        device = BLEDevice(address)
        device.loop = loop
        ble_device = device
        try:
            connection_status = f"Connecting to {address}..."
            add_log(f"Připojování k zařízení {address}")

            loop.run_until_complete(device.connect())
            device.start_heartbeat()

            while not device.client.is_connected:
                time.sleep(0.1)

            # POW:ON se odešle okamžitě po úspěšném připojení
            loop.run_until_complete(device.send_command("POW:ON"))

            with connection_lock:
                ble_device = device
                connection_status = f"Connected to {address}"

            # Bleak musí zůstat na stejném event loopu po celou dobu připojení.
            loop.run_forever()
            return

        except Exception as error:
            add_log(f"Připojení selhalo: {error}. Opakuji za 3 s")
            connection_status = (
                f"Connection failed: {error}. Retrying..."
            )

            try:
                if device.client:
                    loop.run_until_complete(device.disconnect())
            except Exception:
                pass
            if not loop.is_closed():
                loop.close()
            time.sleep(3)
        finally:
            if not loop.is_closed():
                loop.close()


@app.route("/")
def index():
    return render_template(
        "index.html",
        sensor_addr=SENSOR_ADDR,
        enabled_sensors=ENABLED_SENSORS,
    )


@app.route("/connect", methods=["POST"])
def connect_device():
    global ble_device, connection_status

    address = request.json.get("address")

    if address not in SENSOR_ADDR:
        return jsonify({"status": "Invalid device address"}), 400

    with cycle_lock:
        if cycle_active:
            return jsonify({"status": "Measurement cycle is active"}), 409

    with connection_lock:
        if connection_status.startswith("Connecting"):
            return jsonify({"status": connection_status})

        if ble_device:
            try:
                ble_device.disconnect_sync()
            except Exception:
                pass

            ble_device = None

        connection_status = f"Connecting to {address}..."

    threading.Thread(
        target=connection_worker,
        args=(address,),
        daemon=True
    ).start()

    return jsonify({
        "status": f"Connecting to {address}. Retrying until successful..."
    })


@app.route("/logs")
def get_logs():
    with log_lock:
        return jsonify({"logs": list(log_entries)})


@app.route("/connection-status")
def get_connection_status():
    return jsonify({"status": connection_status})


@app.route("/cycle-status")
def get_cycle_status():
    with cycle_lock:
        return jsonify({"active": cycle_active, "status": cycle_status})


@app.route("/cycle-stop", methods=["POST"])
def stop_cycle():
    global cycle_status

    with cycle_lock:
        if not cycle_active:
            return jsonify({"status": "No active measurement cycle"}), 400
        cycle_stop_event.set()
        cycle_status = "Stopping measurement cycle"

    device = ble_device
    if device:
        device.cancel_pending()

    add_log("Požadavek na zastavení měřicího cyklu")
    return jsonify({"status": "Measurement cycle is stopping"})


@app.route("/files")
def get_files():
    MEASURED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        {
            "name": file_path.name,
            "size": file_path.stat().st_size,
            "download_url": f"/files/{file_path.name}",
        }
        for file_path in sorted(
            MEASURED_DATA_DIR.iterdir(),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if file_path.is_file()
    ]
    return jsonify({"files": files})


@app.route("/files/count")
def get_file_count():
    MEASURED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_count = sum(1 for file_path in MEASURED_DATA_DIR.iterdir() if file_path.is_file())
    return jsonify({"count": file_count})


@app.route("/files/clear", methods=["POST"])
def clear_measurement_files():
    if file_receiver.receiving:
        return jsonify({"status": "File transfer is still in progress"}), 409

    with archive_lock:
        MEASURED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        deleted_count = 0
        for file_path in MEASURED_DATA_DIR.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in {".bin", ".csv"}:
                file_path.unlink()
                deleted_count += 1

    add_log(f"Smazáno {deleted_count} starých měřených souborů")
    return jsonify({"status": f"Deleted {deleted_count} measurement files"})


@app.route("/files/<path:filename>")
def download_file(filename):
    return send_from_directory(
        MEASURED_DATA_DIR,
        Path(filename).name,
        as_attachment=True,
    )


@app.route("/files/download-all")
def download_all_files():
    if file_receiver.receiving:
        return jsonify({"status": "File transfer is still in progress"}), 409

    with archive_lock:
        MEASURED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        bin_files = sorted(MEASURED_DATA_DIR.glob("*.bin"))

        try:
            for bin_file in bin_files:
                add_log(f"ZIP: parsování {bin_file.name}")
                sensor_data = process_data_file(bin_file)
                save_to_csv(sensor_data, bin_file.name, MEASURED_DATA_DIR)

            for bin_file in bin_files:
                bin_file.unlink()
                add_log(f"ZIP: odstraněn binární soubor {bin_file.name}")
        except Exception as error:
            add_log(f"ZIP: parsování selhalo, BIN soubory zůstaly zachované: {error}")
            return jsonify({"status": f"Parsing failed: {error}"}), 500

        csv_files = sorted(MEASURED_DATA_DIR.glob("*.csv"))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for csv_file in csv_files:
                zip_file.write(csv_file, arcname=csv_file.name)
        archive.seek(0)

        add_log(f"ZIP: připraveno {len(csv_files)} CSV souborů")
        return send_file(
            archive,
            mimetype="application/zip",
            as_attachment=True,
            download_name="measurement-data-csv.zip",
        )


def refresh_configuration():
    global pending_config_key

    queries = {
        "ADXL": "CONF:ADXL?",
        "BNO": "CONF:BNO?",
        "ADC": "CONF:ADC?",
    }

    for key, command in queries.items():
        with configuration_lock:
            pending_config_key = key
        try:
            ble_device.run(ble_device.send_command(command))
            # Nechat zařízení čas poslat odpověď přes notifikaci.
            time.sleep(0.5)
        finally:
            with configuration_lock:
                pending_config_key = None


@app.route("/configure", methods=["POST"])
def configure_device():
    with cycle_lock:
        if cycle_active:
            return jsonify({"status": "Measurement cycle is active"}), 409

    if not ble_device or not ble_device.client or not ble_device.client.is_connected:
        return jsonify({"status": "Device not connected"}), 400

    config_commands = request.json.get("config", [])
    config_commands = filter_enabled_sensor_commands(config_commands)

    for command in config_commands:
        ble_device.run(ble_device.send_command(command))

    refresh_configuration()

    return jsonify({"status": "Configuration sent"})


@app.route("/configuration", methods=["GET"])
def get_configuration():
    with configuration_lock:
        return jsonify(configuration_feedback)


@app.route("/configuration/refresh", methods=["POST"])
def refresh_configuration_route():
    if not ble_device or not ble_device.client or not ble_device.client.is_connected:
        return jsonify({"status": "Device not connected"}), 400

    refresh_configuration()
    return jsonify({"status": "Configuration query sent"})


@app.route("/measure", methods=["POST"])
def measure():
    global ble_device, connection_status, cycle_active, cycle_status

    payload = request.json or {}
    duration = float(payload.get("duration", 0))
    period = float(payload.get("period", 0))
    address = payload.get("address")
    config_commands = payload.get("config", [])

    if address not in SENSOR_ADDR:
        return jsonify({"status": "Invalid device address"}), 400
    if duration <= 0 or period <= 0:
        return jsonify({"status": "Period and duration must be positive"}), 400

    config_commands = filter_enabled_sensor_commands(config_commands)

    with cycle_lock:
        if cycle_active:
            return jsonify({"status": "Measurement cycle is already active"}), 409
        cycle_active = True
        cycle_status = "Preparing measurement cycle"
        cycle_stop_event.clear()

    if not ble_device or not ble_device.client or not ble_device.client.is_connected:
        with cycle_lock:
            cycle_active = False
            cycle_status = "Idle"
        return jsonify({"status": "Device not connected"}), 400

    device = ble_device
    device_address = device.address
    add_log("Start cyklu: odpojuji BLE")
    try:
        device.disconnect_sync()
    except Exception as error:
        add_log(f"BLE odpojení nebylo potvrzeno: {error}")
    ble_device = None
    connection_status = "Disconnected; measurement cycle scheduled"

    delay = max(0, period * 3600 - 120)
    cycle_status = f"Scheduled; reconnecting in {int(delay)} s"
    threading.Thread(
        target=measurement_cycle_worker,
        args=(device_address, duration, period, config_commands, delay),
        daemon=True,
    ).start()

    return jsonify({"status": "Measurement cycle scheduled"})


def measurement_cycle_worker(address, duration, period, config_commands, initial_delay):
    global cycle_active, cycle_status, connection_status

    if cycle_stop_event.wait(initial_delay):
        cycle_status = "Cycle stopped"
    else:
        while not cycle_stop_event.is_set():
            run_measurement_once(address, duration, config_commands)
            if cycle_stop_event.is_set():
                break

            next_delay = max(0, period * 3600 - 120)
            cycle_status = f"Scheduled; next measurement in {int(next_delay)} s"
            if cycle_stop_event.wait(next_delay):
                break

        cycle_status = "Cycle stopped"

    connection_status = "Disconnected"
    with cycle_lock:
        cycle_active = False


def run_measurement_once(address, duration, config_commands):
    global ble_device, connection_status, cycle_active, cycle_status
    global measurement_sd_ready_event, control_rx_buffer, sd_response_buffer

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    device = None

    try:
        # Connect to device
        while not cycle_stop_event.is_set():
            try:
                cycle_status = f"Connecting to {address} for measurement"
                connection_status = f"Connecting to {address} for measurement..."
                add_log(f"Měření: připojování k zařízení {address}")
                device = BLEDevice(address)
                device.loop = loop
                ble_device = device
                measurement_sd_ready_event = threading.Event()
                control_rx_buffer = bytearray()
                sd_response_buffer = bytearray()
                device.run_on_loop(device.connect())
                device.start_heartbeat()
                device.run_on_loop(device.send_command("POW:ON"))
                add_log("Měření: POW:ON odesláno")

                cycle_status = "Waiting for SD Init OK"
                add_log("Měření: čekám na SD Init OK (timeout 60 s)")
                deadline = time.monotonic() + 60
                while not measurement_sd_ready_event.is_set() and time.monotonic() < deadline:
                    loop.run_until_complete(asyncio.sleep(0.1))

                if measurement_sd_ready_event.is_set():
                    break

                add_log("Měření: SD Init OK nepřišlo do 60 s, opakuji připojení")
                try:
                    device.run_on_loop(device.disconnect())
                except Exception as error:
                    add_log(f"Měření: odpojení po timeoutu nebylo potvrzeno: {error}")
                measurement_sd_ready_event = None
                if cycle_stop_event.wait(3):
                    return
            except Exception as error:
                add_log(f"Měření: připojení selhalo: {error}. Opakuji za 3 s")
                try:
                    if device and device.client:
                        device.run_on_loop(device.disconnect())
                except Exception:
                    pass
                if cycle_stop_event.wait(3):
                    return

        if cycle_stop_event.is_set():
            return

        measurement_sd_ready_event = None
        ble_device = device
        connection_status = f"Connected to {address} for measurement"

        for command in config_commands:
            device.run_on_loop(device.send_command(command))
        add_log("Měření: konfigurace snímačů odeslána")

        # Start the measurement
        measurement_filename = datetime.now().strftime("measurement_%Y_%m_%d_%H_%M_%S")
        device.run_on_loop(
            device.send_command(f"MEAS:START {measurement_filename}")
        )

        # Wait for the measurement to complete or be stopped
        cycle_status = f"Measuring for {duration:g} minutes"
        add_log(f"Měření: MEAS:START odesláno, soubor {measurement_filename}")
        measurement_deadline = time.monotonic() + duration * 60
        while not cycle_stop_event.is_set() and time.monotonic() < measurement_deadline:
            if not device.client or not device.client.is_connected:
                add_log("Měření přerušeno: BLE spojení vypadlo")
                return
            remaining = measurement_deadline - time.monotonic()
            loop.run_until_complete(asyncio.sleep(min(0.2, max(0, remaining))))

        if not device.client or not device.client.is_connected:
            add_log("Měření přerušeno před MEAS:STOP: BLE spojení vypadlo")
            return

        device.run_on_loop(device.send_command("MEAS:STOP"))
        add_log("Měření: MEAS:STOP odesláno")

        if cycle_stop_event.is_set():
            add_log("Měření přerušeno uživatelem")
            return

        # Read the measurement file from the device
        file_receiver.prepare(measurement_filename)
        cycle_status = "Downloading measurement file"
        device.run_on_loop(
            device.send_command(f"FIL:READ? {measurement_filename},bin")
        )
        add_log(f"Měření: FIL:READ? odesláno pro soubor {measurement_filename}")

        download_deadline = time.monotonic() + 600
        while (
            not cycle_stop_event.is_set()
            and not file_receiver.complete_event.is_set()
            and time.monotonic() < download_deadline
        ):
            if not device.client or not device.client.is_connected:
                file_receiver.abort(delete_file=True)
                add_log("Stahování přerušeno: BLE spojení vypadlo")
                return
            loop.run_until_complete(asyncio.sleep(0.1))

        if cycle_stop_event.is_set():
            file_receiver.abort(delete_file=True)
            add_log("Stahování přerušeno uživatelem")
            return

        if not device.client or not device.client.is_connected:
            file_receiver.abort(delete_file=True)
            add_log("Stahování přerušeno: BLE spojení vypadlo")
            return

        # Check if the file transfer completed successfully
        if not file_receiver.complete_event.is_set():
            file_receiver.abort(delete_file=True)
            add_log("Měření: timeout při stahování souboru")
        else:
            add_log(f"Měření: soubor uložen do {file_receiver.file_path}")

        # Parse the received file and save CSV files
        try:
            sensor_data = process_data_file(file_receiver.file_path)
            save_to_csv(sensor_data, file_receiver.filename, MEASURED_DATA_DIR)
            add_log(f"Měření: soubor {file_receiver.filename} zpracován a CSV soubory uloženy")
        except Exception as error:
            add_log(f"Měření: zpracování souboru selhalo: {error}")

        # Delete the original binary file after processing
        try:
            file_receiver.file_path.unlink()
            add_log(f"Měření: binární soubor {file_receiver.filename} odstraněn po zpracování")
        except Exception as error:
            add_log(f"Měření: odstranění binárního souboru selhalo: {error}")

        # Turn off the device and disconnect
        try:
            device.run_on_loop(device.disconnect())
        except Exception as error:
            add_log(f"BLE odpojení nebylo potvrzeno: {error}")
        connection_status = "Disconnected"
        cycle_status = "Measurement complete"
        add_log(f"Měření dokončeno: {address}")
    except Exception as error:
        cycle_status = f"Measurement failed: {error}"
        connection_status = "Disconnected"
        add_log(f"Měření selhalo: {error}")
        try:
            if device.client:
                device.run_on_loop(device.disconnect())
        except Exception:
            pass
    except asyncio.CancelledError:
        if not cycle_stop_event.is_set():
            raise
        add_log("Měření přerušeno během čekání na BLE operaci")
    finally:
        if file_receiver.receiving:
            file_receiver.abort(delete_file=True)
        if device and device.client:
            try:
                device.run_on_loop(device.disconnect())
            except Exception as error:
                add_log(f"BLE úklid po zastavení nebyl potvrzen: {error}")
        ble_device = None
        if not loop.is_closed():
            loop.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)