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
    "adxl": {"enabled": False, "rate": 400},
    "bno": {"enabled": False, "rate": 100},
    "adc": {"enabled": False, "rate": 10000}
}

# Global variables
client = None
measurement_thread = None

@app.route('/')
def index():
    return render_template('index.html', sensor_addr=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
def connect_device():
    global client
    mac_address = request.json.get('mac_address')
    if client is not None and client.is_connected:
        return jsonify({"status": "error", "message": "Already connected to a device."})

    client = BleakClient(mac_address)
    try:
        asyncio.run(client.connect())
        return jsonify({"status": "success", "message": f"Connected to {mac_address}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/configure', methods=['POST'])
def configure_measurements():
    global measurement_params
    measurement_params["adxl"]["enabled"] = request.json.get('adxl_enabled', False)
    measurement_params["adxl"]["rate"] = request.json.get('adxl_rate', 400)
    measurement_params["bno"]["enabled"] = request.json.get('bno_enabled', False)
    measurement_params["bno"]["rate"] = request.json.get('bno_rate', 100)
    measurement_params["adc"]["enabled"] = request.json.get('adc_enabled', False)
    measurement_params["adc"]["rate"] = request.json.get('adc_rate', 10000)
    return jsonify({"status": "success", "message": "Measurement parameters configured."})

@app.route('/start_measurement_cycle', methods=['POST'])
def start_measurement_cycle():
    global measurement_thread
    period_hours = request.json.get('period_hours', 0)
    duration_minutes = request.json.get('duration_minutes', 0)

    if measurement_thread is not None and measurement_thread.is_alive():
        return jsonify({"status": "error", "message": "Measurement cycle already running."})

    measurement_thread = threading.Thread(target=measurement_cycle, args=(period_hours, duration_minutes))
    measurement_thread.start()
    return jsonify({"status": "success", "message": "Measurement cycle started."})

def measurement_cycle(period_hours, duration_minutes):
    time_to_wait = (period_hours * 3600) - 120  # Wait until 2 minutes before the period
    time.sleep(time_to_wait)

    # Send configuration commands
    if measurement_params["adxl"]["enabled"]:
        asyncio.run(client.write_gatt_char("CONF:ADXL ON," + str(measurement_params["adxl"]["rate"])))
    if measurement_params["bno"]["enabled"]:
        asyncio.run(client.write_gatt_char("CONF:BNO ON," + str(measurement_params["bno"]["rate"])))
    if measurement_params["adc"]["enabled"]:
        asyncio.run(client.write_gatt_char("CONF:ADC ON," + str(measurement_params["adc"]["rate"])))

    # Start measurement
    asyncio.run(client.write_gatt_char("MEAS:START"))

    # Wait for the duration of the measurement
    time.sleep(duration_minutes * 60)

    # Stop measurement and download data
    asyncio.run(client.write_gatt_char("MEAS:STOP"))
    # Add logic to download data file here

    # Power off the device
    asyncio.run(client.write_gatt_char("POW:OFF"))
    asyncio.run(client.disconnect())

if __name__ == '__main__':
    app.run(debug=True)