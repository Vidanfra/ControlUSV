import time
import math
import serial
import threading
import zmq
from pydantic import ValidationError

import sys
import os
# Add the project root to sys.path to resolve 'src' when running directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# System imports
from src.core.models import ImuMessage
from src.core.messaging import Topics, get_zmq_url


class WT901Driver:
    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, on_data_callback=None):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        
        # This callback is executed when a 0x53 (Angles) frame arrives
        self.on_data_callback = on_data_callback

        # Shared sensor data accumulator
        self.data = {
            "ax": 0.0, "ay": 0.0, "az": 0.0,    
            "wx": 0.0, "wy": 0.0, "wz": 0.0,      
            "roll": 0.0, "pitch": 0.0, "yaw": 0.0,
            "mx": 0.0, "my": 0.0, "mz": 0.0,      
            "temp": 0.0                             
        }

    def start(self):
        self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=1)
        self.running = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.ser:
            self.ser.close()

    def _to_int16(self, lo, hi):
        val = (hi << 8) | lo
        return val - 0x10000 if val & 0x8000 else val

    def _to_uint16(self, lo, hi):
        return (hi << 8) | lo

    def _checksum_ok(self, frame):
        return (sum(frame[:-1]) & 0xFF) == frame[-1]

    def _read_loop(self):
        buf = bytearray()
        while self.running:
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
                if data:
                    buf.extend(data)

                # Process frames
                while len(buf) >= 11:
                    # Find header
                    try:
                        idx = buf.index(0x55)
                    except ValueError:
                        buf.clear()
                        break

                    if idx + 11 > len(buf):
                        break  # wait for full frame

                    frame = buf[idx:idx+11]
                    buf = buf[idx+11:]  # consume frame

                    if not self._checksum_ok(frame):
                        continue

                    pid = frame[1]
                    self._parse_frame(pid, frame[2:10])
            except Exception as e:
                print(f"WT901 Driver read error: {e}")
                time.sleep(0.1)

    def _parse_frame(self, pid, payload):
        def parse_temp_from_bytes(lo, hi):
            raw = self._to_uint16(lo, hi)
            return raw / 100.0, raw

        if pid == 0x51:  # Acceleration
            ax = self._to_int16(payload[0], payload[1]) / 32768.0 * 16 * 9.8
            ay = self._to_int16(payload[2], payload[3]) / 32768.0 * 16 * 9.8
            az = self._to_int16(payload[4], payload[5]) / 32768.0 * 16 * 9.8

            temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

            if -40.0 <= temp_c <= 85.0:
                self.data.update({"ax": ax, "ay": ay, "az": az, "temp": temp_c})
            else:
                self.data.update({"ax": ax, "ay": ay, "az": az})

        elif pid == 0x52:  # Angular velocity
            wx = self._to_int16(payload[0], payload[1]) / 32768.0 * 2000
            wy = self._to_int16(payload[2], payload[3]) / 32768.0 * 2000
            wz = self._to_int16(payload[4], payload[5]) / 32768.0 * 2000

            temp_c, temp_raw = parse_temp_from_bytes(payload[6], payload[7])

            if -40.0 <= temp_c <= 85.0:
                self.data.update({"wx": wx, "wy": wy, "wz": wz, "temp": temp_c})
            else:
                self.data.update({"wx": wx, "wy": wy, "wz": wz})

        elif pid == 0x53:  # Angles
            roll = self._to_int16(payload[0], payload[1]) / 32768.0 * 180
            pitch = self._to_int16(payload[2], payload[3]) / 32768.0 * 180
            yaw = self._to_int16(payload[4], payload[5]) / 32768.0 * 180
            self.data.update({"roll": roll, "pitch": pitch, "yaw": yaw})
            
            # Since 0x53 is usually the last packet in the 51-52-53-54 burst
            # we trigger the callback to push the full dictionary upwards.
            if self.on_data_callback:
                self.on_data_callback(self.data)

        elif pid == 0x54:  # Magnetometer
            mx = self._to_int16(payload[0], payload[1])
            my = self._to_int16(payload[2], payload[3])
            mz = self._to_int16(payload[4], payload[5])
            self.data.update({"mx": mx, "my": my, "mz": mz})


class ImuNode:
    def __init__(self, serial_port="/dev/serial0", baud_rate=9600, mag_declination=0.0, user_offset=0.0):
        """
        Connects the WT901 IMU to the internal ZMQ data bus.
        """
        self.mag_declination = mag_declination
        self.user_offset = user_offset
        
        # QGC / MAVLink NED body frame mapping (copied from old parser)
        self.QGC_AXIS_MAP = {
            "mx_sign": 1,      # magnetometer X
            "my_sign": 1,      # magnetometer Y
            "mz_sign": 1       # magnetometer Z
        }

        # ZMQ Context & Socket Setup
        self.context = zmq.Context()
        self.pub_socket = self.context.socket(zmq.PUB)
        
        bus_url = get_zmq_url() # Gets the central IPC/TCP URL
        self.pub_socket.connect(bus_url)
        print(f"[IMU Node] Publisher connected to ZMQ Bus: {bus_url}")

        # Instantiate Driver and register callback
        self.driver = WT901Driver(
            serial_port=serial_port, 
            baud_rate=baud_rate, 
            on_data_callback=self.publish_imu_data
        )

    def calculate_mag_heading(self, mx, my):
        """
        Returns magnetic compass heading [0,360) degrees from raw mag values, 
        applying declination and user offset.
        """
        mx_mapped = mx * self.QGC_AXIS_MAP.get("mx_sign", 1)
        my_mapped = my * self.QGC_AXIS_MAP.get("my_sign", 1)
        
        # WT901C-TTL: heading = atan2(my, mx) (sensor X forward, Y right)
        heading_rad = math.atan2(my_mapped, mx_mapped)
        heading_deg = math.degrees(heading_rad)
        
        # Normalize to [0,360)
        heading_deg = (heading_deg + 360.0) % 360.0
        
        # Apply declination and user offset
        heading_deg = (heading_deg + self.mag_declination + self.user_offset) % 360.0
        return heading_deg

    def publish_imu_data(self, raw_data_dict):
        """
        Driver invokes this every time an 'Angles (0x53)' frame is fully parsed.
        """
        ts = time.time()
        
        # Calculate heading
        m_heading = self.calculate_mag_heading(raw_data_dict["mx"], raw_data_dict["my"])

        try:
            # Map into Pydantic Model
            msg = ImuMessage(
                timestamp=ts,
                roll=raw_data_dict["roll"],
                pitch=raw_data_dict["pitch"],
                yaw=raw_data_dict["yaw"],
                ax=raw_data_dict["ax"],
                ay=raw_data_dict["ay"],
                az=raw_data_dict["az"],
                wx=raw_data_dict["wx"],
                wy=raw_data_dict["wy"],
                wz=raw_data_dict["wz"],
                mx=raw_data_dict["mx"],
                my=raw_data_dict["my"],
                mz=raw_data_dict["mz"],
                temp=raw_data_dict["temp"],
                mag_heading=m_heading
            )
            
            # Serialize
            json_str = msg.model_dump_json()
            
            # Publish!
            # Format: 'topic payload'
            self.pub_socket.send_string(f"{Topics.SENSOR_IMU.value} {json_str}")
            
        except ValidationError as e:
            print(f"[IMU Node] Data validation error dropping frame: {e}")

    def run(self):
        print("[IMU Node] Starting driver thread...")
        self.driver.start()
        try:
            while True:
                # Node loop simply sleeps, the worker thread triggers the callback
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[IMU Node] Keyboard Interrupt detected. Shutting down...")
            self.shutdown()

    def shutdown(self):
        self.driver.stop()
        self.pub_socket.close()
        self.context.term()
        print("[IMU Node] Shutdown complete.")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="WT901 IMU Driver - standalone test or ZMQ node")
    parser.add_argument("--mode", choices=["test", "node"], default="test",
                        help="'test' = standalone serial read (no ZMQ), 'node' = full ZMQ publisher")
    parser.add_argument("--port", default="/dev/serial0", help="Serial port (default: /dev/serial0)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--declination", type=float, default=2.5, help="Magnetic declination in degrees")
    args = parser.parse_args()

    if args.mode == "node":
        # Full ZMQ publisher mode
        node = ImuNode(serial_port=args.port, baud_rate=args.baud, mag_declination=args.declination)
        node.run()
    else:
        # Standalone test - read and print sensor data (no ZMQ needed)
        received_count = [0]

        def on_data(data):
            received_count[0] += 1
            print(
                f"Accel: {data['ax']:7.2f}, {data['ay']:7.2f}, {data['az']:7.2f} | "
                f"Angles: {data['roll']:7.2f}, {data['pitch']:7.2f}, {data['yaw']:7.2f} | "
                f"Gyro: {data['wx']:7.2f}, {data['wy']:7.2f}, {data['wz']:7.2f} | "
                f"Mag: {data['mx']:6.0f}, {data['my']:6.0f}, {data['mz']:6.0f} | "
                f"Temp: {data['temp']:.2f} °C"
            )

        driver = WT901Driver(args.port, baud_rate=args.baud, on_data_callback=on_data)
        driver.start()
        print(f"[TEST] WT901 driver started on {args.port} @ {args.baud} baud")
        print("[TEST] Waiting for data (Ctrl+C to stop)...\n")

        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass

        driver.stop()
        print(f"\n[TEST] Stopped. Total frames received: {received_count[0]}")
