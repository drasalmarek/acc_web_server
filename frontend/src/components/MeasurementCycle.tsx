# File: web_app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time
import threading

app = Flask(__name__)

# Configuration
SENSOR_ADDR = ["C6:E6:A3:FC:45:F5", "EB:F8:1D:58:73:87", "D2:F3:34:16:59:B1", "CB:71:2E:31:FC:98", "E7:31:E9:B5:72:2A"]
measurement_params = {
    "adxl": {"enabled": False, "frequency": 400},
    "bno": {"enabled": False, "frequency": 100},
    "adc": {"enabled": False, "frequency": 10000}
}

# Global variables
client = None
measurement_thread = None

def connect_device(address):
    global client
    client = BleakClient(address)
    asyncio.run(client.connect())

def disconnect_device():
    global client
    if client and client.is_connected:
        asyncio.run(client.disconnect())

def send_command(command):
    global client
    if client and client.is_connected:
        asyncio.run(client.write_gatt_char(UART_TX_CHAR_UUID, command.encode()))

def start_measurement_cycle(period_hours, duration_minutes):
    global measurement_thread
    if measurement_thread is not None and measurement_thread.is_alive():
        return "Measurement cycle already running."

    def measurement_cycle():
        time.sleep((period_hours * 3600) - 120)  # Wait until 2 minutes before the period
        for param, config in measurement_params.items():
            if config["enabled"]:
                send_command(f"CONF:{param.upper()} ON,{config['frequency']}")
                time.sleep(0.2)
                send_command(f"CONF:{param.upper()}?")
                time.sleep(0.2)
        time.sleep(duration_minutes * 60)
        send_command("MEAS:START")
        time.sleep(60)  # Wait for measurement to complete
        send_command("MEAS:STOP")
        time.sleep(0.2)
        send_command("FIL:READ? filename,postfix")
        time.sleep(0.2)
        disconnect_device()

    measurement_thread = threading.Thread(target=measurement_cycle)
    measurement_thread.start()
    return "Measurement cycle started."

@app.route('/')
def index():
    return render_template('index.html', sensor_addr=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
def connect():
    address = request.json.get('address')
    connect_device(address)
    return jsonify({"status": "Connected to device."})

@app.route('/disconnect', methods=['POST'])
def disconnect():
    disconnect_device()
    return jsonify({"status": "Disconnected from device."})

@app.route('/start_measurement', methods=['POST'])
def start_measurement():
    period_hours = request.json.get('period_hours')
    duration_minutes = request.json.get('duration_minutes')
    return jsonify({"status": start_measurement_cycle(period_hours, duration_minutes)})

@app.route('/configure', methods=['POST'])
def configure():
    param = request.json.get('param')
    enabled = request.json.get('enabled')
    frequency = request.json.get('frequency')
    if param in measurement_params:
        measurement_params[param]["enabled"] = enabled
        measurement_params[param]["frequency"] = frequency
    return jsonify({"status": "Configuration updated."})

if __name__ == '__main__':
    app.run(debug=True)