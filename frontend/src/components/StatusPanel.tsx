# File: web_app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time

app = Flask(__name__)

SENSOR_ADDR = ["C6:E6:A3:FC:45:F5", "EB:F8:1D:58:73:87", "D2:F3:34:16:59:B1", "CB:71:2E:31:FC:98", "E7:31:E9:B5:72:2A"]

class BLEWorker:
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
            response = await self.client.read_gatt_char(UART_TX_CHAR_UUID)
            return response.decode()

@app.route('/')
def index():
    return render_template('index.html', sensor_addr=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
async def connect_device():
    address = request.json.get('address')
    worker = BLEWorker(address)
    await worker.connect()
    return jsonify({"status": "connected"})

@app.route('/configure', methods=['POST'])
async def configure_device():
    address = request.json.get('address')
    commands = request.json.get('commands')
    worker = BLEWorker(address)
    await worker.connect()
    
    for command in commands:
        await worker.send_command(command)
    
    return jsonify({"status": "configured"})

@app.route('/start_measurement', methods=['POST'])
async def start_measurement():
    address = request.json.get('address')
    period = request.json.get('period')  # in hours
    duration = request.json.get('duration')  # in minutes

    worker = BLEWorker(address)
    await worker.connect()

    # Schedule measurement
    time_to_wait = (period * 3600) - 120  # 2 minutes before the period
    await asyncio.sleep(time_to_wait)

    # Send measurement commands
    await worker.send_command("MEAS:START")
    await asyncio.sleep(duration * 60)  # wait for the duration of the measurement
    await worker.send_command("MEAS:STOP")

    # Download data file (implementation depends on your data handling)
    await worker.send_command("FIL:READ? filename")

    await worker.disconnect()
    return jsonify({"status": "measurement completed"})

if __name__ == '__main__':
    app.run(debug=True)