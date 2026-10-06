
import argparse
import struct
import csv
from glob import glob, has_magic
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
import numpy as np

def process_data_file(file_path):
    sensor_data = {
        'adxl' : {
            'x' : [],
            'y' : [],
            'z' : [],
            'magnitude' : [],
            'active_channels' : 0,
            'timestamps' : [],
            'sampling_rates' : [],
            'time_axis' : np.array([]),    
            'data_sizes' : [],
            'avg_sampling_rate' : 0
        },

        'bno' : {
            'acc_x' : [], # everything is 2 bytes
            'acc_y' : [],
            'acc_z' : [],
            'gyr_x' : [],
            'gyr_y' : [],
            'gyr_z' : [],
            'mag_x' : [],
            'mag_y' : [],
            'mag_z' : [],
            'eul_heading' : [],
            'eul_roll' : [],
            'eul_pitch' : [],
            'quat_w' : [],
            'quat_x' : [],
            'quat_y' : [],
            'quat_z' : [],
            'lia_x' : [],
            'lia_y' : [],
            'lia_z' : [],
            'grv_x' : [],
            'grv_y' : [],
            'grv_z' : [],
            'temp' : [], # 1 byte
            'single_size' : (6*3 + 6 + 8 + 6 + 6 + 1), # 45

            'timestamps' : [],
            'data_sizes' : [],
            'sampling_rates' : [],
            'time_axis' : np.array([]),
            'avg_sampling_rate' : 0
        },

        'adc0' : {
            'values_ch1' : [],
            'values_ch2' : [],
            'timestamps' : [],
            'data_sizes' : [],
            'sampling_rates' : [],
            'time_axis' : np.array([]),
            'avg_sampling_rate' : 0
        }
    }

    def bytes_to_data(bytes_read, number_of_values):
        # Unpack 6 uint8_t values
        u = struct.unpack(f'{number_of_values*2}B', bytes_read)
        output = []
        for i in range(0, number_of_values):
            val = (u[i*2 + 1] << 8) | u[i*2]
            # Interpret as signed int16
            val = struct.unpack('<h', struct.pack('<H', val))[0]
            output.append(val)
        return output

    with open(file_path, 'rb') as bin_file:
        first_header = bin_file.read(5) # 4 bytes for global start time + 1 byte for active channels
        # HAL_GetTick() is a uint32_t copied with memcpy — assume little-endian
        global_start_time = struct.unpack('<I', first_header[0:4])[0]
        sensor_data['adxl']['active_channels'] = struct.unpack('1B', first_header[4:5])[0]
        adxl_single_size = bin(sensor_data['adxl']['active_channels']).count('1') * 2  # Each active channel contributes 2 bytes
        while True:
            header = bin_file.read(9)
            if len(header) < 9:
                break
            index = header[0]
            timestamp = struct.unpack('<I', header[1:5])[0]
            data_size = struct.unpack('<I', header[5:9])[0]
            if index == 1:
                start_time = sensor_data['adxl']['timestamps'][-1] if sensor_data['adxl']['timestamps'] else global_start_time
                sensor_data['adxl']['timestamps'].append(timestamp)
                sensor_data['adxl']['data_sizes'].append(int(data_size / adxl_single_size))
                sampling_rate = (data_size / adxl_single_size) / ((timestamp - start_time) / 1000)
                sensor_data['adxl']['sampling_rates'].append(sampling_rate)
                for _ in range(data_size//adxl_single_size):
                    bytes_read = bin_file.read(adxl_single_size)
                    if len(bytes_read) < adxl_single_size:
                        break
                    data = bytes_to_data(bytes_read, adxl_single_size // 2)  # Each channel contributes 2 bytes

                    i = 0

                    if sensor_data['adxl']['active_channels'] & 0b0001:
                        sensor_data['adxl']['x'].append(data[i] / 256.0)
                        i += 1
                    if sensor_data['adxl']['active_channels'] & 0b0010:
                        sensor_data['adxl']['y'].append(data[i] / 256.0)
                        i += 1
                    if sensor_data['adxl']['active_channels'] & 0b0100:
                        sensor_data['adxl']['z'].append(data[i] / 256.0)
                        i += 1
                    if sensor_data['adxl']['active_channels'] & 0b1000:
                        sensor_data['adxl']['magnitude'].append(data[i] / 256.0)
                        i += 1

            elif index == 2:
                start_time = sensor_data['bno']['timestamps'][-1] if sensor_data['bno']['timestamps'] else global_start_time
                sensor_data['bno']['timestamps'].append(timestamp)
                sensor_data['bno']['data_sizes'].append(int(data_size / sensor_data['bno']['single_size']))
                sampling_rate = (data_size / sensor_data['bno']['single_size']) / ((timestamp - start_time) / 1000)
                sensor_data['bno']['sampling_rates'].append(sampling_rate)
                for _ in range(data_size//sensor_data['bno']['single_size']):
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['acc_x'].append(data[0]/100.0)
                    sensor_data['bno']['acc_y'].append(data[1]/100.0)
                    sensor_data['bno']['acc_z'].append(data[2]/100.0)
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['gyr_x'].append(data[0]/16.0)
                    sensor_data['bno']['gyr_y'].append(data[1]/16.0)
                    sensor_data['bno']['gyr_z'].append(data[2]/16.0)
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['mag_x'].append(data[0]/16.0)
                    sensor_data['bno']['mag_y'].append(data[1]/16.0)
                    sensor_data['bno']['mag_z'].append(data[2]/16.0)
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['eul_heading'].append(data[0]/16.0)
                    sensor_data['bno']['eul_roll'].append(data[1]/16.0)
                    sensor_data['bno']['eul_pitch'].append(data[2]/16.0)
                    bytes_read = bin_file.read(8)
                    if len(bytes_read) < 8:
                        break
                    data = bytes_to_data(bytes_read, 4)
                    sensor_data['bno']['quat_w'].append(data[0]/16384.0)
                    sensor_data['bno']['quat_x'].append(data[1]/16384.0)
                    sensor_data['bno']['quat_y'].append(data[2]/16384.0)
                    sensor_data['bno']['quat_z'].append(data[3]/16384.0)
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['lia_x'].append(data[0]/100.0)
                    sensor_data['bno']['lia_y'].append(data[1]/100.0)
                    sensor_data['bno']['lia_z'].append(data[2]/100.0)
                    bytes_read = bin_file.read(6)
                    if len(bytes_read) < 6:
                        break
                    data = bytes_to_data(bytes_read, 3)
                    sensor_data['bno']['grv_x'].append(data[0]/100.0)
                    sensor_data['bno']['grv_y'].append(data[1]/100.0)
                    sensor_data['bno']['grv_z'].append(data[2]/100.0)
                    bytes_read = bin_file.read(1)
                    if len(bytes_read) < 1:
                        break
                    u = struct.unpack('1B', bytes_read)
                    sensor_data['bno']['temp'].append(u[0])
            elif index == 3:
                start_time = sensor_data['adc0']['timestamps'][-1] if sensor_data['adc0']['timestamps'] else global_start_time
                sensor_data['adc0']['timestamps'].append(timestamp)
                sampling_rate = (data_size / 4) / ((timestamp - start_time) / 1000)
                sensor_data['adc0']['sampling_rates'].append(sampling_rate)
                sensor_data['adc0']['data_sizes'].append(int(data_size / 4))
                for _ in range(data_size // 4):
                    bytes_read = bin_file.read(4)  # 2 bytes for CH1 + 2 bytes for CH2
                    if len(bytes_read) < 4:
                        break

                    ch1, ch2 = struct.unpack('<HH', bytes_read)  # little-endian uint16, uint16
                    sensor_data['adc0']['values_ch1'].append(ch1)
                    sensor_data['adc0']['values_ch2'].append(ch2)

        # Calculate average sampling rates excluding the last element
        if len(sensor_data['adxl']['sampling_rates']) > 1:
            rates = sensor_data['adxl']['sampling_rates'][:-1]
            sensor_data['adxl']['avg_sampling_rate'] = sum(rates) / len(rates)
        else:
            sensor_data['adxl']['avg_sampling_rate'] = sensor_data['adxl']['sampling_rates'][0] if sensor_data['adxl']['sampling_rates'] else 0

        if len(sensor_data['bno']['sampling_rates']) > 1:
            rates = sensor_data['bno']['sampling_rates'][:-1]
            sensor_data['bno']['avg_sampling_rate'] = sum(rates) / len(rates)
        else:
            sensor_data['bno']['avg_sampling_rate'] = sensor_data['bno']['sampling_rates'][0] if sensor_data['bno']['sampling_rates'] else 0

        if len(sensor_data['adc0']['sampling_rates']) > 1:
            rates = sensor_data['adc0']['sampling_rates'][:-1]
            sensor_data['adc0']['avg_sampling_rate'] = sum(rates) / len(rates)
        else: 
            sensor_data['adc0']['avg_sampling_rate'] = sensor_data['adc0']['sampling_rates'][0] if sensor_data['adc0']['sampling_rates'] else 0

        # Generate time axis for each sensor based on timestamps
        for i in range(0, len(sensor_data['adxl']['sampling_rates'])):
            partial_time = np.linspace((sensor_data['adxl']['time_axis'][-1] if sensor_data['adxl']['time_axis'].size > 0 else 0), (sensor_data['adxl']['time_axis'][-1] if sensor_data['adxl']['time_axis'].size > 0 else 0) + sensor_data['adxl']['data_sizes'][i] / sensor_data['adxl']['sampling_rates'][i], num=sensor_data['adxl']['data_sizes'][i])

            sensor_data['adxl']['time_axis'] = np.concatenate((sensor_data['adxl']['time_axis'], partial_time))

        for i in range(0, len(sensor_data['bno']['sampling_rates'])):
            partial_time = np.linspace((sensor_data['bno']['time_axis'][-1] if sensor_data['bno']['time_axis'].size > 0 else 0), (sensor_data['bno']['time_axis'][-1] if sensor_data['bno']['time_axis'].size > 0 else 0) + sensor_data['bno']['data_sizes'][i] / sensor_data['bno']['sampling_rates'][i], num=sensor_data['bno']['data_sizes'][i])

            sensor_data['bno']['time_axis'] = np.concatenate((sensor_data['bno']['time_axis'], partial_time))

        for i in range(0, len(sensor_data['adc0']['sampling_rates'])):
            partial_time = np.linspace((sensor_data['adc0']['time_axis'][-1] if sensor_data['adc0']['time_axis'].size > 0 else 0), (sensor_data['adc0']['time_axis'][-1] if sensor_data['adc0']['time_axis'].size > 0 else 0) + sensor_data['adc0']['data_sizes'][i] / sensor_data['adc0']['sampling_rates'][i], num=sensor_data['adc0']['data_sizes'][i])

            sensor_data['adc0']['time_axis'] = np.concatenate((sensor_data['adc0']['time_axis'], partial_time))

        return sensor_data

def save_to_csv(sensor_data, filename, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save ADXL data
    if sensor_data['adxl']['time_axis'].size == 0:
        pass
    else:
        adxl_file_path = output_dir / filename.replace(".bin", "_adxl.csv")
        with open(adxl_file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Time (s)', 'X (g)', 'Y (g)', 'Z (g)', 'Magnitude (g)'])
            for i in range(len(sensor_data['adxl']['time_axis'])):
                writer.writerow([
                    sensor_data['adxl']['time_axis'][i],
                    sensor_data['adxl']['x'][i] if i < len(sensor_data['adxl']['x']) else '',
                    sensor_data['adxl']['y'][i] if i < len(sensor_data['adxl']['y']) else '',
                    sensor_data['adxl']['z'][i] if i < len(sensor_data['adxl']['z']) else '',
                    sensor_data['adxl']['magnitude'][i] if i < len(sensor_data['adxl']['magnitude']) else ''
                ])

    # Save BNO data
    if sensor_data['bno']['time_axis'].size == 0:
        pass
    else:
        bno_file_path = output_dir / filename.replace(".bin", "_bno.csv")
        with open(bno_file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Time (s)', 'Acc X (m/s2)', 'Acc Y (m/s2)', 'Acc Z (m/s2)',
                            'Gyr X (deg/s)', 'Gyr Y (deg/s)', 'Gyr Z (deg/s)',
                            'Mag X (uT)', 'Mag Y (uT)', 'Mag Z (uT)',
                            'Eul Heading (deg)', 'Eul Roll (deg)', 'Eul Pitch (deg)',
                            'Quat W', 'Quat X', 'Quat Y', 'Quat Z',
                            'LIA X (m/s2)', 'LIA Y (m/s2)', 'LIA Z (m/s2)',
                            'GRV X (m/s2)', 'GRV Y (m/s2)', 'GRV Z (m/s2)',
                            'Temp (deg C)'])
            for i in range(len(sensor_data['bno']['time_axis'])):
                writer.writerow([
                    sensor_data['bno']['time_axis'][i],
                    sensor_data['bno']['acc_x'][i] if i < len(sensor_data['bno']['acc_x']) else '',
                    sensor_data['bno']['acc_y'][i] if i < len(sensor_data['bno']['acc_y']) else '',
                    sensor_data['bno']['acc_z'][i] if i < len(sensor_data['bno']['acc_z']) else '',
                    sensor_data['bno']['gyr_x'][i] if i < len(sensor_data['bno']['gyr_x']) else '',
                    sensor_data['bno']['gyr_y'][i] if i < len(sensor_data['bno']['gyr_y']) else '',
                    sensor_data['bno']['gyr_z'][i] if i < len(sensor_data['bno']['gyr_z']) else '',
                    sensor_data['bno']['mag_x'][i] if i < len(sensor_data['bno']['mag_x']) else '',
                    sensor_data['bno']['mag_y'][i] if i < len(sensor_data['bno']['mag_y']) else '',
                    sensor_data['bno']['mag_z'][i] if i < len(sensor_data['bno']['mag_z']) else '',
                    sensor_data['bno']['eul_heading'][i] if i < len(sensor_data['bno']['eul_heading']) else '',
                    sensor_data['bno']['eul_roll'][i] if i < len(sensor_data['bno']['eul_roll']) else '',
                    sensor_data['bno']['eul_pitch'][i] if i < len(sensor_data['bno']['eul_pitch']) else '',
                    sensor_data['bno']['quat_w'][i] if i < len(sensor_data['bno']['quat_w']) else '',
                    sensor_data['bno']['quat_x'][i] if i < len(sensor_data['bno']['quat_x']) else '',
                    sensor_data['bno']['quat_y'][i] if i < len(sensor_data['bno']['quat_y']) else '',
                    sensor_data['bno']['quat_z'][i] if i < len(sensor_data['bno']['quat_z']) else '',
                    sensor_data['bno']['lia_x'][i] if i < len(sensor_data['bno']['lia_x']) else '',
                    sensor_data['bno']['lia_y'][i] if i < len(sensor_data['bno']['lia_y']) else '',
                    sensor_data['bno']['lia_z'][i] if i < len(sensor_data['bno']['lia_z']) else '',
                    sensor_data['bno']['grv_x'][i] if i < len(sensor_data['bno']['grv_x']) else '',
                    sensor_data['bno']['grv_y'][i] if i < len(sensor_data['bno']['grv_y']) else '',
                    sensor_data['bno']['grv_z'][i] if i < len(sensor_data['bno']['grv_z']) else '',
                    sensor_data['bno']['temp'][i] if i < len(sensor_data['bno']['temp']) else ''
                ])

    # Save ADC0 data
    if sensor_data['adc0']['time_axis'].size == 0:
        pass
    else:
        adc0_file_path = output_dir / filename.replace(".bin", "_adc0.csv")
        with open(adc0_file_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Time (s)', 'CH1 Value', 'CH2 Value'])
            for i in range(len(sensor_data['adc0']['time_axis'])):
                writer.writerow([
                    sensor_data['adc0']['time_axis'][i],
                    sensor_data['adc0']['values_ch1'][i] if i < len(sensor_data['adc0']['values_ch1']) else '',
                    sensor_data['adc0']['values_ch2'][i] if i < len(sensor_data['adc0']['values_ch2']) else ''
                ])

def parse_input_file(source, output_dir=None):
    parsed_source = urlparse(source)
    is_url = parsed_source.scheme in {"http", "https", "file"}

    if not is_url:
        file_path = Path(source).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError(f"Input file not found: {file_path}")
        filename = file_path.name
        target_dir = Path(output_dir) if output_dir else file_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        return process_data_file(file_path), filename, target_dir

    filename = Path(unquote(parsed_source.path)).name
    if not filename or not filename.lower().endswith(".bin"):
        raise ValueError("The input URL must point to a .bin file")

    target_dir = Path(output_dir) if output_dir else Path.cwd()
    target_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as temporary_dir:
        local_file = Path(temporary_dir) / filename
        with urlopen(source, timeout=60) as response, open(local_file, "wb") as output_file:
            while chunk := response.read(1024 * 1024):
                output_file.write(chunk)
        sensor_data = process_data_file(local_file)

    return sensor_data, filename, target_dir


def expand_input_sources(sources):
    expanded_sources = []
    for source in sources:
        parsed_source = urlparse(source)
        if parsed_source.scheme in {"http", "https", "file"} or not has_magic(source):
            expanded_sources.append(source)
            continue

        matches = sorted(glob(source))
        if not matches:
            raise FileNotFoundError(f"No files matched: {source}")
        expanded_sources.extend(matches)

    return expanded_sources


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process binary sensor data and save to CSV.")
    parser.add_argument(
        "files",
        nargs="+",
        help="Path, wildcard, symbolic link, or URL to one or more .bin files",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output directory for generated CSV files (default: input directory or current directory for URLs)",
    )
    args = parser.parse_args()

    for source in expand_input_sources(args.files):
        sensor_data, filename, output_dir = parse_input_file(source, args.output)
        save_to_csv(sensor_data, filename, output_dir)
        print(f"Processed: {source}")
