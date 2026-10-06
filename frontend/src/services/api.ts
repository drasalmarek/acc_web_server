# File: web_app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time

app = Flask(__name__)

# Configuration
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

    async def send_command(self, command):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(UART_RX_CHAR_UUID, command.encode())

    async def query_command(self, command):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(UART_RX_CHAR_UUID, command.encode())
            time.sleep(0.1)  # Wait for response
            response = await self.client.read_gatt_char(UART_TX_CHAR_UUID)
            return response.decode()

@app.route('/')
def index():
    return render_template('index.html', sensor_addr=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
async def connect_device():
    address = request.json.get('address')
    device = BLEDevice(address)
    await device.connect()
    return jsonify({"status": "connected"})

@app.route('/configure', methods=['POST'])
async def configure_device():
    address = request.json.get('address')
    commands = request.json.get('commands')
    device = BLEDevice(address)
    await device.connect()
    
    for command in commands:
        await device.send_command(command)
    
    return jsonify({"status": "configured"})

@app.route('/start_measurement', methods=['POST'])
async def start_measurement():
    address = request.json.get('address')
    period = request.json.get('period')
    duration = request.json.get('duration')
    
    device = BLEDevice(address)
    await device.connect()
    
    # Schedule measurement
    time.sleep(period * 3600 - 120)  # Wait until 2 minutes before the period
    await device.send_command("MEAS:START")
    time.sleep(duration * 60)  # Wait for the duration of the measurement
    await device.send_command("MEAS:STOP")
    
    # Download data file logic here (not implemented)
    
    await device.send_command("POW:OFF")
    await device.disconnect()
    
    return jsonify({"status": "measurement completed"})

if __name__ == '__main__':
    app.run(debug=True)