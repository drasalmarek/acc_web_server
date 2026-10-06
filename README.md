# File: web_app.py

from flask import Flask, render_template, request, jsonify
import asyncio
from bleak import BleakClient
import time

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
    device = BLEDevice(address)
    await device.connect()
    return jsonify({"status": "connected"})

@app.route('/send_command', methods=['POST'])
async def send_command():
    address = request.json.get('address')
    command = request.json.get('command')
    device = BLEDevice(address)
    await device.connect()
    await device.send_command(command)
    return jsonify({"status": "command sent"})

@app.route('/query_command', methods=['POST'])
async def query_command():
    address = request.json.get('address')
    command = request.json.get('command')
    device = BLEDevice(address)
    await device.connect()
    response = await device.query_command(command)
    return jsonify({"response": response})

@app.route('/measurement_cycle', methods=['POST'])
async def measurement_cycle():
    address = request.json.get('address')
    period_hours = request.json.get('period_hours')
    duration_minutes = request.json.get('duration_minutes')

    device = BLEDevice(address)
    await device.connect()

    time_to_start = (period_hours * 3600) - 120  # Start 2 minutes before the period
    await asyncio.sleep(time_to_start)

    # Send configuration commands here
    await device.send_command("CONF:ADXL ON,400")
    await device.send_command("CONF:BNO OFF,100")
    await device.send_command("CONF:ADC OFF,10000")

    # Start measurement
    await device.send_command("MEAS:START")
    await asyncio.sleep(duration_minutes * 60)  # Duration of measurement
    await device.send_command("MEAS:STOP")

    # Download data file logic here
    await device.send_command("FIL:READ? filename,postfix")

    await device.disconnect()
    return jsonify({"status": "measurement cycle complete"})

if __name__ == '__main__':
    app.run(debug=True)