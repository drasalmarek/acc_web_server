# app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time
import threading

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

def measurement_cycle(address, config, period_hours, duration_minutes):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    worker = BLEWorker(address)

    async def run_cycle():
        await worker.connect()
        time.sleep(120)  # Wait for 2 minutes before sending commands
        for cmd in config:
            await worker.send_command(cmd)
            time.sleep(0.5)  # Delay between commands
        time.sleep(duration_minutes * 60)  # Duration of measurement
        await worker.send_command("POW:OFF")
        await worker.disconnect()

    loop.run_until_complete(run_cycle())

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start_measurement', methods=['POST'])
def start_measurement():
    data = request.json
    address = data['address']
    config = data['config']
    period_hours = data['period_hours']
    duration_minutes = data['duration_minutes']

    threading.Thread(target=measurement_cycle, args=(address, config, period_hours, duration_minutes)).start()
    return jsonify({"status": "Measurement cycle started."})

if __name__ == '__main__':
    app.run(debug=True)