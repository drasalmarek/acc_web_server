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

device = None

@app.route('/')
def index():
    return render_template('index.html', addresses=SENSOR_ADDR)

@app.route('/connect', methods=['POST'])
def connect_device():
    global device
    address = request.json.get('address')
    device = BLEDevice(address)
    asyncio.run(device.connect())
    return jsonify({"status": "connected"})

@app.route('/disconnect', methods=['POST'])
def disconnect_device():
    global device
    if device:
        asyncio.run(device.disconnect())
        device = None
    return jsonify({"status": "disconnected"})

@app.route('/send_command', methods=['POST'])
def send_command():
    command = request.json.get('command')
    asyncio.run(device.send_command(command))
    return jsonify({"status": "command sent"})

@app.route('/query_command', methods=['POST'])
def query_command():
    command = request.json.get('command')
    response = asyncio.run(device.query_command(command))
    return jsonify({"response": response})

def periodic_measurement(period_hours, duration_minutes):
    time.sleep((period_hours * 3600) - 120)  # Wait until 2 minutes before the period
    if device:
        asyncio.run(device.send_command("CONF:ADXL ON,400"))
        asyncio.run(device.send_command("CONF:BNO OFF,100"))
        asyncio.run(device.send_command("CONF:ADC OFF,10000"))
        asyncio.run(device.send_command("MEAS:START"))
        time.sleep(duration_minutes * 60)
        asyncio.run(device.send_command("MEAS:STOP"))
        asyncio.run(device.send_command("FIL:READ? filename,postfix"))
        asyncio.run(device.send_command("POW:OFF"))
        asyncio.run(device.disconnect())

@app.route('/start_measurement_cycle', methods=['POST'])
def start_measurement_cycle():
    period_hours = request.json.get('period_hours')
    duration_minutes = request.json.get('duration_minutes')
    threading.Thread(target=periodic_measurement, args=(period_hours, duration_minutes)).start()
    return jsonify({"status": "measurement cycle started"})

if __name__ == '__main__':
    app.run(debug=True)