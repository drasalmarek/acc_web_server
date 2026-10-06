# app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time
import threading

app = Flask(__name__)

SENSOR_ADDR = ["C6:E6:A3:FC:45:F5", "EB:F8:1D:58:73:87", "D2:F3:34:16:59:B1", "CB:71:2E:31:FC:98", "E7:31:E9:B5:72:2A"]

class BLEDevice:
    def __init__(self, address):
        self.address = address
        self.client = None

    async def connect(self):
        self.client = BleakClient(self.address)
        await self.client.connect()

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def send_command(self, command):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(UART_RX_CHAR_UUID, command.encode())

    async def query_command(self, command):
        if self.client and self.client.is_connected:
            response = await self.client.read_gatt_char(UART_TX_CHAR_UUID)
            return response.decode()

@app.route('/')
def index():
    return render_template('index.html', sensor_addr=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
def connect_device():
    address = request.json.get('address')
    device = BLEDevice(address)
    asyncio.run(device.connect())
    return jsonify({"status": "connected"})

@app.route('/send_command', methods=['POST'])
def send_command():
    address = request.json.get('address')
    command = request.json.get('command')
    device = BLEDevice(address)
    asyncio.run(device.connect())
    asyncio.run(device.send_command(command))
    return jsonify({"status": "command sent"})

@app.route('/query_command', methods=['POST'])
def query_command():
    address = request.json.get('address')
    command = request.json.get('command')
    device = BLEDevice(address)
    asyncio.run(device.connect())
    response = asyncio.run(device.query_command(command))
    return jsonify({"response": response})

def periodic_measurement(address, period, duration):
    time.sleep(period * 3600 - 120)  # Wait until 2 minutes before the period
    device = BLEDevice(address)
    asyncio.run(device.connect())
    # Send configuration commands here
    # Start measurement command
    time.sleep(duration * 60)  # Wait for the duration of the measurement
    # Download data file
    # Send power off command
    asyncio.run(device.send_command("POW:OFF"))
    asyncio.run(device.disconnect())

@app.route('/start_measurement_cycle', methods=['POST'])
def start_measurement_cycle():
    address = request.json.get('address')
    period = request.json.get('period')
    duration = request.json.get('duration')
    threading.Thread(target=periodic_measurement, args=(address, period, duration)).start()
    return jsonify({"status": "measurement cycle started"})

if __name__ == '__main__':
    app.run(debug=True)